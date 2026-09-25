# Blender 4DGS Viewer/Editor: Technical Reference

How the pipeline works, what the data looks like, and how to develop and release the extension.

- [Pipeline overview](#pipeline-overview)
- [Input: 4DGS takes](#input-4dgs-takes)
- [Conversion and the cache format](#conversion-and-the-cache-format)
- [Cache quality](#cache-quality)
- [Playback](#playback)
- [Geometry Nodes: "4DGS Splats"](#geometry-nodes-b4d-splats)
- [Material: "4DGS Splat"](#material-b4d-splat)
- [Timing model](#timing-model)
- [Editing operations](#editing-operations)
- [Performance](#performance)
- [Source layout](#source-layout)
- [Development, testing and release](#development-testing-and-release)
- [Design decisions](#design-decisions)
- [Limitations and roadmap](#limitations-and-roadmap)

---

## Pipeline overview

```
 take .zip / folder of .ply frames
            │  convert.py (child process, Blender's Python + numpy, up to 8 workers)
            ▼
 <take>.splatcache/ ── meta.json + frames/NNNNNN.npy   (34 B/splat, importance-sorted)
            │  playback.py (frame_change_pre handler, ~5 ms/frame)
            ▼
 take object (vertex-only mesh) with point attributes
   splat_rot · splat_scale · splat_color · splat_opacity
            │  "4DGS Splats" Geometry Nodes modifier (crop, clean-up, colour, per-splat maths)
            ▼
 point cloud: one sphere per splat + splat_center, splat_ax/ay/az, colour, opacity
            │  "4DGS Splat" material (ray-space Gaussian, Dithered in EEVEE / exact in Cycles)
            ▼
 viewport / EEVEE render / Cycles render
```

Each take is a normal Blender object with an `Object.b4d` property group (`props.py`). All per-take state lives there and in its modifier inputs, so takes can be duplicated, split and saved like any other object.

## Input: 4DGS takes

A take is one binary little-endian 3DGS PLY per frame, with a frame number at the end of each file name (e.g. `frame.0000001.ply`). Takes are often zipped *stored* (uncompressed), so they can be read straight from the zip without extracting; compressed zips work too, just more slowly. Each vertex is one Gaussian with 62 floats (248 bytes):

| Property | Meaning | Converted to |
|---|---|---|
| `x y z` | centre | position (unchanged, source space) |
| `nx ny nz` | normals: all zero in the sample take | ignored |
| `f_dc_0..2` | SH degree-0 colour | `srgb_to_linear(clamp(0.5 + 0.28209479·f_dc))` |
| `f_rest_0..44` | SH degrees 1–3 (view-dependent colour) | kept as float16 in full-quality caches (`.sh.npy`); dropped in compact caches |
| `opacity` | logit | `sigmoid(opacity)`. In the sample take nearly every splat sits at about **0.20** |
| `scale_0..2` | log std-dev | `exp(scale)`: 1.5–7 cm radius (3σ) in the sample take |
| `rot_0..3` | quaternion (w, x, y, z) | normalised |

**Coordinates:** metres; **Y-down** (the floor at y≈0, the head at y≈−1.75); the performer faces **+Z**. On import (*Up Axis −Y*) the object gets rotation (−90°, 0°, 180°), which maps source −Y → +Z (up) and source +Z → −Y, so the performer faces Blender's Front view.

The sample take used for all measurements below: a full-body performance, 890 frames, 82k–118k splats per frame, 20 GB of PLYs.

The sample take also contains `ply-manifest.txt`, which lists compressed SPZ packages; the viewer only uses the PLY frames.

## Conversion and the cache format

`convert.py` has no Blender dependency (numpy only). The add-on runs it as
`<Blender python> -I convert.py <source> <cache> --machine [--workers N]` and reads `PROGRESS i n` / `ERROR msg` / `DONE` lines from stdout. It also runs by hand for batch pre-conversion:

```bash
"C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" convert.py "D:\takes\MyTake.ply.zip" "D:\caches\MyTake.splatcache"
```

**Source discovery** (`find_source`):
- **A `.zip`:** use the folder inside it with the most `.ply` members.
- **A `.ply`:** use its folder.
- **A folder:** use the sub-folder, up to 3 levels deep, with the most `.ply` files.

Frames are ordered by the trailing number of the file name. The **signature** is a SHA-1 of (frame number, file name, size) for every frame. It identifies the source without reading 20 GB.

**Cache layout (version 2):**

```
<take>.splatcache/
  meta.json          written last (atomic rename) → its presence means "complete"
  source.sig         signature of the source the frames came from (for safe resume)
  frames/000001.npy     one structured numpy array per frame
  frames/000001.sh.npy  full quality only: float16 (n, 3 + 3k), same order: base = 0.5 + C0·f_dc (unclamped),
                        then f_rest channel-major; k = 3 / 8 / 15 coefficients for SH degree 1 / 2 / 3
```

A full-quality cache is 34 + 96 = 130 B/splat for degree 3 (about 12 GB for the sample take, vs 2.8 GB compact). `meta.json` records `sh_requested` and `sh_degree`. Converting with `--sh` into an existing compact cache **upgrades it in place**: base frames are kept, and only the `.sh.npy` files are added.

Per-splat record (`SPLAT_DTYPE`, 34 bytes, about 7× smaller than the PLY):

| Field | Type | Notes |
|---|---|---|
| `pos` | float32 ×3 | full precision; float16 would quantise to about 1 mm |
| `rot` | float16 ×4 | unit quaternion w, x, y, z |
| `scale` | float16 ×3 | σ per local axis |
| `color` | float16 ×3 | linear RGB |
| `opacity` | float16 | 0–1 |

Records are **sorted by importance** (`opacity × σ_max × σ_mid`, i.e. approximate screen coverage). Any prefix of a frame is then a sensible level of detail. *Density*, *Playback Detail* and *Echo Density* just take a prefix, with no random sampling and no flicker.

`meta.json` holds `version`, `take`, `source`, `source_kind`, `signature`, `frame_numbers`, `counts`, `max_count`, `sh_requested`, `sh_degree`, `bounds_min/max` (source space, over the whole take) and `dtype`.

**Resume:** frames are written as `*.tmp.npy` and renamed. A re-run skips existing frames when `source.sig` matches. A different source clears `frames/` first.

**Cache location:** *next to the take* (`<parent>/<take>.splatcache`); if that folder isn't writable, the extension's user folder (`bpy.utils.extension_path_user`); or a user-chosen *Cache Folder* (`<folder>/<take>-<sig8>.splatcache`).

## Cache quality

A **compact** cache (the default: most stable and fastest) is lossy in exactly one way that matters. A **full-quality** cache is visually lossless. Measured on frames 1, 300 and 701 of the sample take:

| What the cache changes | Measured effect | Visible? |
|---|---|---|
| float16 colour | ≤ 0.04 of one 8-bit level | no |
| float16 opacity | ≤ 0.00006 | no |
| float16 size (σ) | ≤ 0.3 % of the splat size | no |
| float16 rotation | ≤ 0.05° (mean 0.01°) | no |
| float32 position | exact | no |
| importance sort | a reorder only | no |
| float16 SH coefficients (full quality) | colours within 0.0011 linear of the reference | no |
| **compact only: dropped SH degrees 1–3** (view-dependent colour) | per splat: mean 7, p95 19 levels. **Final image: mean 7–8.5 levels, p95 15–17, PSNR about 30 dB** on the performer | **yes**: slightly flatter, lighter shading; less contrast in folds and fabric |

**Verification** (`dev/test_quality.py`, frame 300, 1080p EEVEE, 128 samples). An independent reference sets every splat's colour straight from the original PLY (3DGS SH toward the camera) and bypasses the plugin's colour code:

| Render | vs reference |
|---|---|
| Full-quality colour (plugin) | mean 0.03 levels, p99 1 level, **PSNR 68 dB**: identical |
| Compact cache | mean 7.4 levels, p99 19 levels, PSNR 30.7 dB |

The compact-cache numbers compare an EEVEE render with a render where every splat gets its full SH colour, evaluated toward the camera (as 3DGS rasterisers do). Frames 300 and 600 were rendered from the front and 90° to the side.

**Not caused by the cache**, but also differing from a reference 3DGS viewer: EEVEE's dithered transparency (grain until samples converge); the ray-space Gaussian evaluation instead of 3DGS's screen-space EWA projection with its 0.3 px low-pass dilation (slightly crisper here); and the *Density* / *Playback Detail* sliders when below 1.

### How full-quality colour is evaluated

`sh.py` evaluates the 3DGS SH basis (degrees 0–3, the reference rasteriser's constants and sign conventions) with numpy, once per splat and per frame, for the direction from the viewpoint to the splat centre in source coordinates: `srgb = clamp(base + Σ basis_k(dir)·f_rest_k, 0, 1)`, then converted to linear. Inputs larger than 16k splats are split into chunks and run on a thread pool (numpy releases the GIL): about 10 ms for 110k splats instead of 32 ms single-threaded. `dev/test_sh.py` checks it against a loop-by-loop transcription of the reference `computeColorFromSH` (error < 3×10⁻⁷).

**Viewpoint** (`playback.viewpoint`):
- **Renders and background mode:** the scene camera (perspective: its position; orthographic: its view direction).
- **Interactive:** the largest 3D viewport, preferring Rendered / Material Preview shading. Camera view uses the camera; otherwise the viewport's eye (or view direction when orthographic).

A 0.25 s timer (`_watch_view`) re-colours the splats already in the mesh when the viewpoint moves more than 5 mm (or 0.1°) while paused, rewriting only `splat_color`. During playback, each frame change evaluates colours for the current viewpoint. `render_init` forces a refresh so stills and animations use the render camera.

**Animated cameras:** `frame_change_pre` runs before Blender evaluates the new frame's animation, so colours use the camera position one frame late. The view direction barely changes between frames, so this isn't visible.

## Playback

`playback.py` registers `frame_change_pre`, `animation_playback_post`, `render_init/complete/cancel`, `load_post`, `undo_post/redo_post` and `save_pre/post` handlers.

For each visible take object, on every frame change:
1. `timing.take_index()` maps the timeline frame to a take frame. Echo frames are added at `frame − k·spacing`.
2. The splat count is `counts[i] × Density × (Playback Detail while playing and not rendering)` (× Echo Density for echoes).
3. The frame array is loaded (32-frame LRU per cache) and sliced. Echo copies get `opacity × fade^k`, then everything is concatenated.
4. With full-quality colour, the matching `.sh.npy` slice is loaded, and `splat_color` is evaluated toward the current viewpoint (see above).
5. The mesh is replaced: `clear_geometry()`, `vertices.add(n)`, and `foreach_set` of `position` plus the four `splat_*` point attributes. That takes about 4–6 ms for 110k splats (compact), or 17–22 ms with full-quality colour.

A key of (cache, [(index, count, fade)…]) per object skips redundant uploads. **Undo/redo/load** clear the keys (their mesh data may be stale). **save_pre** empties the meshes so a `.blend` stays about 0.1 MB, and **save_post** reloads them. **render_init** sets a flag so renders always use full Density; *Lock Interface* is enabled by *Set Up Viewing*, because the handler swaps mesh data during renders.

The attribute is `splat_color`, never `color`: Cycles point clouds don't read an attribute called `color`, and it renders black.

## Geometry Nodes: "4DGS Splats"

One shared node group (rebuilt automatically when `SHADING_VERSION` changes), used by a **Splats** modifier on every take. Its inputs are per-object and keyframable:

| Input | Effect |
|---|---|
| Size | multiplies σ (and so the proxy radius and inverse transform) |
| Opacity | multiplies opacity |
| Min Opacity | removes splats below it (a floor of 1e-4 always applies) |
| Max Splat Radius | removes splats with 3σ_max above it (0 = off) |
| Crop Left/Right/Front/Back/Bottom/Top | fraction of the take bounds cut from each side, in *upright* space |
| Crop Feather | metres over which opacity ramps to 0 towards any crop plane |
| Use Crop Box / Crop Box / Invert Crop Box | keep only the inside (or outside) of an object's −1…1 cube |
| Exposure / Saturation / Hue Shift / Tint | HSV adjust → × tint → × 2^exposure |
| Upright, Bounds Min/Max (hidden) | set by the add-on: source→upright rotation and upright take bounds |

Graph outline:

```
pos ─► Rotate(Upright) ─► rel = p − BoundsMin ─► six inside-distances (m) ─► d = min
        d < 0 → cropped            feather = clamp(d / Feather)
pos ─► Transform Point(inverse(Object Info[Crop Box].Transform, relative)) ─► |p|∞ ≤ 1 → inside
remove = cropped ∨ (UseBox ∧ (inside ⇔ Invert)) ∨ opacity' < MinOpacity ∨ 3σmax > MaxRadius
opacity' = opacity · Opacity · feather                         → splat_opacity
colour'  = HSV(hue+shift, sat·Saturation, v) · Tint · 2^Exposure → splat_color
rows     = Rotate(e_i, rot) / σ_i  (i = x, y, z)               → splat_ax/ay/az
centre   = pos                                                  → splat_center
Delete(remove) → Mesh to Points(radius = 3·σ_max) → drop splat_rot/scale → Set Material
```

The crop works in **upright take space** with bounds over the whole take. So *Top* is always the head end, whatever the object's transform, and a crop plane doesn't move as the performer moves. The crop box uses the box's transform **relative to the take object**, so both can move freely.

## Material: "4DGS Splat"

For every hit on a splat's proxy sphere:

```
p  = A · (P_obj − centre)        A = rows splat_ax/ay/az = (R·S)^-1   (σ-space)
v  = normalize(A · V_obj)        V = incoming ray direction, world → object
d² = |p|² − (p·v)²               squared distance of the ray from the centre, in σ units
α  = opacity · exp(−d²/2)        · [α > 1/255] · [front face]
shader = mix(Transparent, Emission(splat_color), α)
```

This is exact for an anisotropic 3D Gaussian along a ray: in whitened space the ray's closest approach gives the peak density. Because α depends only on the ray, not on where it hits the proxy, the proxy shape doesn't matter as long as it encloses 3σ. Back faces are transparent, so each ray counts each splat once.

- **EEVEE:** `Dithered` render method (order-independent stochastic transparency), converging with samples.
- **Cycles:** exact transparency. Grazing rays cross many overlapping proxy spheres, so *Transparent Max Bounces* must be about 512 (128 leaves dark silhouette edges).
- **Colour:** splat colours are display sRGB, so the *Standard* view transform reproduces them 1:1 (AgX/Filmic wash them out).

## Timing model

`timing.py` is pure Python (unit-tested without Blender). With `lo, hi` = the trimmed take range (0-based) and `L = hi − lo + 1`:

```
freeze        → clamp(freeze_frame − 1)
time remap    → clamp(round(F(t)) − 1)           F = keyframed b4d.remap_frame, evaluated directly
otherwise     local = floor(elapsed(t))
                elapsed(t) = (t − start) · v                     (constant speed)
                elapsed(t) = Σ_{f=start}^{t−1} v(f)              (either speed keyframed)
                v = take Speed (b4d.speed) × scene Playback Speed (Scene.b4d_speed)
              outside [0, L): Hold → clamp · Loop → mod L · Ping-Pong → mirror, period 2L−2 · Hide → none
              reverse → L − 1 − local
              index = lo + local
```

A `Clock` object wraps `elapsed(t)` and its inverse, `first_frame_showing(local)` (a forward/backward search when keyframed). Trims, Split, Cut, Reset Timing and Fit Timeline all use it, so they stay correct under speed ramps. Summing per frame is O(t − start) F-Curve evaluations per take and frame, which is negligible for takes of a few thousand frames. Speed never changes `scene.render.fps`.

Handlers run *before* Blender evaluates animation for the new frame, so the speed and remap F-Curves are evaluated directly (legacy `action.fcurves` and 4.4+ layered actions/channelbags are both supported).

## Editing operations

All editing operations are ordinary undoable operators (`editing.py`):

| Operator | Implementation |
|---|---|
| Trim Start / End | Sets `trim_in` / `trim_out` from the take frame under the playhead. *Trim Start* sets `start_frame` to the first timeline frame that showed it, so the footage doesn't move. Reverse-aware. |
| Split | Duplicates the object (mesh copied; cache, modifier inputs and animation shared). A: `trim_out = idx`. B: `trim_in = idx+1`, `start = first frame showing idx`. Both get *Hide* outside. Reverse-aware. |
| Cut Range | Front or back cuts become trims; a middle cut is a split with B `trim_in = b+1` and `start = end(A)+1` (Close Gap) or the original timing. |
| Reset Timing | Restores `start_frame` so the untrimmed footage keeps its alignment, then clears trims/speed (including speed keyframes)/reverse/freeze/remap. |
| Key Take Frame | On first use, enables Time Remap with the current take frame; keys `b4d.remap_frame`. |
| Add/Remove Crop Box | A cube empty (display size 1) scaled to the take's world bounds; sets the modifier inputs. |

## Performance

Measured on an ASUS laptop: RTX 5070 Ti Laptop GPU (12 GB), 24 threads, 31 GB RAM, NVMe SSD. Blender 5.2, the sample take (82k–118k splats per frame).

| Task | Result |
|---|---|
| Convert 890 frames from the 21 GB zip (8 processes), compact | **17 s** → 2.8 GB cache |
| Upgrade that cache to full quality (adds `.sh.npy`) | **41 s** → 11 GB cache |
| Frame load + mesh upload, compact / full-quality colour | 4–6 ms / 17–22 ms |
| EEVEE rendered-viewport playback, full detail, full-quality colour | **27.3 fps** |
| EEVEE rendered-viewport playback, full detail, compact colour | **29.8 fps** |
| … with crop + feather + colour grade | 29.8 fps |
| … with 3 echoes (echo density 0.8) | 21.7 fps |
| EEVEE final render, 1920×1080, 64 samples | 0.6–1.8 s/frame |
| Cycles final render, 1920×1080, 128 samples, OptiX | about 20 s/frame |

Other proxy approaches were measured during development and rejected:

| Proxy | Playback fps | Why it was rejected |
|---|---|---|
| Icosahedron **instances** | 9 | 100k instance draw calls; the CPU-side instance sync dominates |
| **Realized** icosahedra (one 2M-triangle mesh) | 1.9 | the full mesh re-extracts to the GPU every frame |
| **Point cloud** spheres (current) | 29.8 | one draw call; only point data changes per frame |

## Source layout

| File | Role |
|---|---|
| `blender_manifest.toml` | extension manifest (id `blender_4dgs_viewer_editor`, Blender ≥ 4.2, `files` permission) |
| `__init__.py` | registers the modules |
| `convert.py` | PLY parsing, conversion, cache format, CLI (no bpy) |
| `jobs.py` | background conversion process, progress polling, cancel (kills the process tree) |
| `props.py` | `Object.b4d` settings, `Scene.b4d_speed` (Playback Speed), add-on preferences, cache location |
| `timing.py` | timeline → take-frame mapping, speed `Clock`, F-Curve lookup (no bpy apart from the objects passed in) |
| `sh.py` | 3DGS spherical-harmonic colour evaluation, threaded (numpy only) |
| `playback.py` | cache reader, mesh upload, viewpoint + view-dependent colour, handlers, view watcher |
| `shading.py` | node group + material builders, modifier-input helpers (Blender 4.x and 5.x APIs) |
| `operators.py` | import, convert, set-up viewing, up-axis, drag-and-drop `FileHandler` |
| `editing.py` | trim, split, cut, timing reset, remap keys, crop box, look reset |
| `ui.py` | Splats sidebar panels |

## Development, testing and release

Tests live in `dev/`:

```bash
# pure-Python tests: timing maths, SH colour vs the 3DGS reference formula
"<blender>/5.2/python/bin/python.exe" dev/test_timing.py
"<blender>/5.2/python/bin/python.exe" dev/test_sh.py

# end-to-end: install zip, import .zip (cached) and a folder (converted), play, render both engines, save/reopen
set BLENDER_USER_RESOURCES=%TEMP%\b4d_test_profile
blender -b --factory-startup --python dev/test_headless.py -- blender_4dgs_viewer_editor-2.2.0.zip <take.zip> <small take folder> <out dir>

# features: every crop side in world space, feather, crop box ± invert, clean-up, colour, density,
# echoes, speed, scene Playback Speed, keyframed speed ramps, trims, time remap, split, cut, fit timeline;
# renders the docs' demo images
blender -b --factory-startup --python dev/test_features.py -- blender_4dgs_viewer_editor-2.2.0.zip <take.zip> <out dir>

# full-quality colour: plugin render vs an independent PLY-based reference (PSNR), and the compact look
blender -b --factory-startup --python dev/test_quality.py -- blender_4dgs_viewer_editor-2.2.0.zip <take.zip> <out dir> [frame]
```

`BLENDER_USER_RESOURCES` points Blender at a throw-away profile, so tests never touch your real add-ons or preferences. All suites pass on **Blender 5.1 and 5.2**.

**Building a release:**
1. Bump `version` in `blender_manifest.toml` and add a `CHANGELOG.md` entry.
2. Run:
   ```bash
   blender --factory-startup --command extension build --source-dir source/blender_4dgs_viewer_editor --output-dir .
   ```
3. Run the tests against the new zip.

## Design decisions

- **Cache, not live PLY reading.** Parsing 20–30 MB per frame caps playback far below real time. The importance-sorted records make a frame a 3 MB contiguous read (plus 10 MB of SH at full quality) with free LOD.
- **SH on the CPU, not in the shader.** 45 coefficients per splat would need 15 extra vector attributes through Geometry Nodes and the material. Evaluating once per splat on the CPU matches the reference rasteriser exactly, costs about 10 ms, and keeps the GPU path unchanged.
- **A child process for conversion.** It runs its own multiprocessing pool with Blender's bundled Python (running a pool inside Blender's own process is fragile), and it never blocks the UI or takes Blender down if a file is bad.
- **A Python frame handler plus Geometry Nodes.** Geometry Nodes can't pick files per frame, so Python streams the data and Geometry Nodes does everything per splat. Geometry Nodes inputs are keyframable, which gives animated crops, fades and grades for free.
- **Stateless timing maths.** Every frame is computed from settings alone, so scrubbing, rendering out of order and network rendering all work.
- **Nothing splat-specific in the .blend.** Files stay small and caches can be shared between scenes and people.

## Limitations and roadmap

**Current limitations:**
- **No relighting:** splats carry baked lighting and ignore scene lights. The sample take's PLY normals are all zero.
- **View-dependent colour** is evaluated per splat for one viewpoint per frame, as 3DGS does. With several 3D viewports open, only the largest one's viewpoint is used interactively.
- **EEVEE** transparency is dithered: slightly grainy in motion, converging when paused or rendered.
- **Split/Cut** parts are set to *Hide* outside their range.
- **Time Remap and Freeze** disable Split/Cut/Trim buttons; reset timing first.
- **Motion blur** isn't supported (the splat count changes every frame).
- **Only binary little-endian PLY input.** SPZ packages aren't read yet.

**Roadmap ideas:**
- **Relighting:** a proxy-surface normals pass (Points to Volume → Volume to Mesh → Sample Nearest Surface), shadow casting/catching, and a lit/unlit mix.
- **SPZ input:** read compressed SPZ packages directly.
- **Export an edited take:** trimmed/cropped/graded PLY sequences, or a single USD point cloud.
- **Per-splat motion-vector blur** from frame-to-frame nearest neighbours.
