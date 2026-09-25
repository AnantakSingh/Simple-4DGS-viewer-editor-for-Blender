# Blender 4DGS Viewer/Editor: Usage Guide

This guide takes you from a take on disk to a finished render. No scripting or command line is needed.

**Contents**
1. [Install](#1-install)
2. [Import a take](#2-import-a-take)
3. [Watch it](#3-watch-it)
4. [The Splats sidebar](#4-the-splats-sidebar)
5. [Timing: trim, split, cut, speed](#5-timing-trim-split-cut-speed)
6. [Crop](#6-crop)
7. [Look: clean-up and colour](#7-look-clean-up-and-colour)
8. [Echoes](#8-echoes)
9. [Several takes in one scene](#9-several-takes-in-one-scene)
10. [Rendering](#10-rendering)
11. [Recipes](#11-recipes)
12. [Performance tips](#12-performance-tips)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. Install

1. Download `blender_4dgs_viewer_editor-2.2.0.zip` from the [Releases page](https://github.com/AnantakSingh/Simple-4DGS-viewer-editor-for-Blender/releases). Keep it zipped.
2. Open Blender (4.2 or newer).
3. Go to *Edit › Preferences › Get Extensions*. Click the **⌄** menu at the top right, choose **Install from Disk…**, and pick the zip.
4. Check that **Blender 4DGS Viewer/Editor** is ticked under *Add-ons*.

**Updating:** install the new `.zip` the same way; it replaces the old version. Existing `.blend` files and caches keep working.

**Optional settings** are in *Preferences › Add-ons › Blender 4DGS Viewer/Editor*:

| Setting | Meaning |
|---|---|
| **Cache Location** | *Next to the Take* (default) writes `<take>.splatcache` beside the take's folder or `.zip`. *Cache Folder* puts every cache in one place you choose, which is useful when takes are on a read-only drive or network share. |
| **Converter Processes** | CPU processes used for conversion. 0 = automatic (up to 8). |

## 2. Import a take

A take is a 4DGS capture: one 3DGS `.ply` file per frame (e.g. `frame.0000001.ply`, `frame.0000002.ply`, …), often zipped.

There are three ways to import. Use whichever is handiest:

- **File › Import › 4DGS Splat Sequence (.ply folder / .zip)**
- **Splats sidebar › Import Take…**
- **Drag** the take's `.zip` (or any of its `.ply` files) from Explorer into the 3D viewport.

In the file browser you can pick the **`.zip`**, **any `.ply`** in the take, or just **open the take folder** and press *Import*. The plugin finds the frames itself, even one or two folders deep.

### Import options

| Option | Default | What it does |
|---|---|---|
| **Frame Rate** | 30 | Sets the scene frame rate to the capture's rate. |
| **Start Frame** | 1 | Timeline frame where the take begins. |
| **Up Axis** | -Y (Y-down) | Which way is up in the source data. -Y suits most 3DGS/4DGS exports. |
| **Full-Quality Colour** | Off | Off gives the **compact** cache: the most stable and fastest option, with slightly flatter shading. On also keeps each splat's view-dependent colour, so the take looks exactly like the original capture; the cache is about 4× larger (about 12 GB instead of 3 GB for a 900-frame, 100k-splat take). You can upgrade a compact take later from the Look panel. |
| **Set Up Viewing** | On | Sets the frame range, adds a camera in front of the performer, applies a dark backdrop and the *Standard* colour view, and switches the viewport to Rendered camera view. |

### First import: conversion

The first time a take is imported, it's converted into a cache in the background. The sidebar shows a progress bar and you can keep working meanwhile. On an SSD, 890 frames (about 20 GB of PLYs) take about 20 seconds and produce a 2.8 GB compact cache. A full-quality cache takes under a minute and 11 GB.

- **Stop Conversion** pauses it. Click **Convert** later to resume where it stopped.
- Importing the same take again, in any file, finds the existing cache and opens instantly.
- Conversion never modifies the original files.

## 3. Watch it

- Press <kbd>Space</kbd> to play. Scrub the timeline to move through the take.
- The viewport starts in **Rendered** shading, looking through the **Splat Camera**. To look around freely, orbit with the middle mouse button (this leaves camera view). Press <kbd>Numpad 0</kbd> to return to the camera.
- To orbit the camera itself, rotate **Splat Camera Rig** around Z (select it, press <kbd>R</kbd> <kbd>Z</kbd>). The camera is parented to it.
- The performer faces Blender's **Front** view (<kbd>Numpad 1</kbd>).
- The splats only look right in **Material Preview** or **Rendered** shading. In Solid mode each splat shows as a grey sphere.

## 4. The Splats sidebar

Press <kbd>N</kbd> in the viewport and open the **Splats** tab.

**Splat Viewer** (top):
- **Import Take…**
- **Playback Speed**: speed of every take in the scene. See [Playback speed](#playback-speed-without-changing-the-frame-rate).
- A list of every take in the scene. Click a name to select that take. Click the eye to hide or show its splats.

**Take** (for the selected take):
- A status line: current take frame / total, splat count, and load time.
- **Up Axis**: change it only if a take comes in lying down or upside down. It resets the object's rotation.
- **Set Up Viewing**: re-runs the camera, backdrop and frame-range setup for this take. Use it after moving the take or changing its timing.
- **⟳ Reload**: re-reads the cache from disk.

Below that are the **Timing**, **Crop**, **Look**, **Echoes** and **Files** sub-panels, covered next.

> **Take frames vs timeline frames.** *Take frames* are the frames of the capture, numbered 1 to N (e.g. N = 890 for a 30-second take at 30 fps). *Timeline frames* are Blender's frames. Trims, freeze and remap use take frames; Start Frame uses timeline frames.

## 5. Timing: trim, split, cut, speed

### Buttons (they act at the playhead)

| Button | Result |
|---|---|
| **Trim Start** | Drops everything before the playhead. The rest stays where it was on the timeline. |
| **Trim End** | Drops everything after the playhead. |
| **Split** | Cuts the take into **two objects** at the playhead, like a blade cut in a video editor. Each part can then be moved, re-timed, cropped or graded on its own. |
| **Cut Range** | Removes a range of take frames from the middle. The dialog asks for *From* / *To* take frames and **Close Gap** (on: the second half moves earlier so there's no pause; off: the take just disappears for the cut section). The result is two objects. |
| **Fit Timeline** | Sets the scene start/end to cover every take in the scene. |
| **Key Take Frame** | Keys *Time Remap* (see below). |
| **Reset Timing** | Removes trims, speed, reverse, freeze and remap. The footage stays aligned where it was. |

### Settings

| Setting | Meaning |
|---|---|
| **Start Frame** | Timeline frame where the (trimmed) take begins. Change it to slide the take along the timeline. |
| **Trim Start / Trim End** | First / last take frame used. *Trim End 0* means the last frame. The label under them shows the take's length. |
| **Speed** | This take's speed: 0.5 = half speed (each frame shown twice), 2 = double speed. It's multiplied by the scene's *Playback Speed*. Keyframable (see below). |
| **Reverse** | Plays backwards. |
| **Outside Take** | What shows before and after the take: **Hold** the first/last frame, **Loop**, **Ping-Pong** (forwards, then backwards), or **Hide**. Split and Cut set their parts to *Hide* so they don't overlap. |
| **Freeze** + *Take Frame* | Shows one frame for the whole timeline, like a still. |
| **Time Remap** + *Take Frame* | Full manual control of time. The keyframable *Take Frame* value says which take frame is shown. Key it at two timeline frames to get slow motion, speed ramps, holds or rewinds. Set the keys to *Linear* interpolation in the Graph Editor for constant speed. Time Remap overrides Start, Speed, Reverse and looping. |

### Playback speed without changing the frame rate

There are two speed controls. Neither touches the scene frame rate, so renders, audio and other animation stay at the capture rate (e.g. 30 fps). Only the splat footage plays faster or slower.

| Control | Where | Affects |
|---|---|---|
| **Playback Speed** | top of the Splats panel | every take in the scene |
| **Speed** | Timing panel | this take only |

The take's effective speed is **Speed × Playback Speed**. For example, Playback Speed 0.5 turns every take into half-speed slow motion; a take set to Speed 2 under it plays at normal speed.

**Speed ramps:** both values can be keyframed (hover and press <kbd>I</kbd>, or right-click › *Insert Keyframe*). The plugin adds the speed up frame by frame, so a keyframed ramp plays smoothly, with no jumps: ease into slow motion, hold at 0 to pause, then speed back up. **Fit Timeline** and the Trim, Split and Cut buttons all account for the ramp.

Speed has no effect while **Freeze** or **Time Remap** is on, because those choose the frame directly.

**Time Remap in practice:** put the playhead where the effect should start and click **Key Take Frame**. That turns Time Remap on and keys the current frame. Move the playhead, type a new *Take Frame* value, and click **Key Take Frame** again.

## 6. Crop

**Crop sides:** **Left, Right, Front, Back, Bottom, Top** each cut away that share (0–1) of the take. They're measured in the take's own upright space, so *Top* always means the performer's head end, even if you rotate the object. Directions follow Blender's Front view (<kbd>Numpad 1</kbd>): Left = −X, Right = +X, Front = −Y (towards the camera), Back = +Y. The crop covers the whole take's extent, so a crop stays put while the performer moves through it.

**Feather:** instead of a hard cut, splats fade out over this distance inside the crop edge. Combine it with keyframed crop values for **wipes and reveals**.

**Crop Box:** **Add Crop Box** creates a box object around the take. Only splats inside it are kept. Move, rotate and scale the box freely, or animate it.
- **Use Box** switches it on and off.
- **Invert** removes the inside instead, e.g. to cut out a stand or a prop.
- **Remove Crop Box** deletes it.

**Reset Crop** clears all crop settings.

Every crop value has a keyframe dot. Hover over it and press <kbd>I</kbd>, or right-click › *Insert Keyframe*.

## 7. Look: clean-up and colour

| Setting | Use it for |
|---|---|
| **View-Dependent Colour** | Colours each splat as seen from the camera (renders, camera view) or your viewport's eye, like the original capture. Needs a full-quality cache. Turning it off shows the flatter compact look. For a compact cache, this row is an **Upgrade to Full Quality** button, which adds the missing colour data to the existing cache in place. |
| **Size** | Scale every splat. Below 1 looks crisper and more "pointy"; above 1 is softer and fills small holes. |
| **Opacity** | Fade the whole take. Keyframe it for fade-in and fade-out. |
| **Min Opacity** | Removes faint splats. *Some captures store almost every splat at about 0.2 opacity; for those this rarely helps.* |
| **Max Radius** | Removes splats larger than this radius, which cleans up big blurry "floaters". In a typical full-body capture, splats are 1.5–7 cm; try 8–10 cm. 0 = off. |
| **Density** | Share of splats drawn, most important first. Lower it for faster renders or a sparser, stylised look. |
| **Playback Detail** | Further reduction only while the timeline is playing. Paused frames and renders ignore it. Lower it if playback stutters. |
| **Exposure** | Brightness in stops. |
| **Saturation** | 0 = greyscale, 1 = original, above 1 = more vivid. |
| **Hue Shift** | Rotates colours around the colour wheel. |
| **Tint** | Multiplies all colours. |

**Reset Clean-up** and **Reset Colour** restore the defaults.

## 8. Echoes

Onion-skin motion trails: earlier frames are drawn behind the current one, each more transparent.

| Setting | Meaning |
|---|---|
| **Echoes** | How many trailing copies (0 = off). |
| **Spacing** | Timeline frames between copies. Larger values give longer trails. |
| **Fade** | Opacity of each echo relative to the previous one. |
| **Echo Density** | Share of splats per echo. Lower is lighter on the GPU. |

Echoes cost performance. Three echoes play at about 22 fps against 30 fps without.

**Files** shows the take's **Source** (folder or `.zip`) and **Cache** folder. If you move a cache, point *Cache* at its new location. **Rebuild Cache** deletes the cache and converts the take again.

## 9. Several takes in one scene

- Import each take. Each becomes its own object, listed in the Splats panel.
- Move, rotate or scale take objects like any other object. Timing, crop and look settings stay per take.
- Use **Start Frame** to arrange takes one after another. Use **Fit Timeline** afterwards.
- *Split* and *Cut Range* create extra objects for the same take. They share one cache, so they cost no extra disk space.
- To duplicate a take with different settings, use <kbd>Shift</kbd>+<kbd>D</kbd>.

## 10. Rendering

Render as usual: *Render › Render Image* (<kbd>F12</kbd>) or *Render Animation* (<kbd>Ctrl</kbd>+<kbd>F12</kbd>). The plugin loads the right frame for every rendered frame, always at full Density (Playback Detail is ignored).

| | EEVEE | Cycles |
|---|---|---|
| Speed (1080p, RTX 5070 Ti laptop) | About 1–2 s per frame | About 20 s per frame at 128 samples. Use 32–64 samples with denoising for previews |
| Transparency | Dithered: very close, slight grain | Exact |
| Tip | Raise *Render › Sampling › Render* samples for smoother results | Keep *Light Paths › Max Bounces › Transparent* at **512** or more, or the silhouette gets dark edges. *Set Up Viewing* sets this. |

For Cycles on a GPU, choose your GPU once in *Preferences › System › Cycles Render Devices* (e.g. OptiX), then set *Render › Device* to *GPU Compute*.

**Set Up Viewing** already enables *Render › Lock Interface*. Keep it on: it stops the viewport from changing the scene while frames are swapped in during a render.

Splats are self-lit: they already carry the captured lighting. Scene lights don't affect them (relighting is planned).

## 11. Recipes

**Show only the best 10 seconds (at 30 fps):**
1. Move the playhead to the start of the section and click **Trim Start**.
2. Move 300 frames later and click **Trim End**.
3. Set **Start Frame** to 1 and click **Fit Timeline**.

**Remove a mistake in the middle:** click **Cut Range**, enter the take frames to remove, and keep **Close Gap** on.

**Rearrange sections:** click **Split** at each cut point. Then change each part's **Start Frame** to reorder them, and click **Fit Timeline**.

**Waist-up shot:** set **Crop Bottom** to about 0.45 and **Feather** to 0.05–0.1 m.

**Reveal from the floor up:** at frame 1, set **Crop Top** to 1.0 and key it. At frame 60, set it to 0.0 and key it. Add a little **Feather** for a soft edge.

**Fade in / out:** keyframe **Opacity** from 0 to 1 at the start, and from 1 to 0 at the end.

**Slow-motion moment:** at the start of the moment, click **Key Take Frame**. Then, 100 frames later, key a *Take Frame* only 50 frames further on; that's half speed. After the last key the take holds that frame, so add more keys to carry on, e.g. a key 100 frames later that is 100 take frames further for normal speed. Set the keys to *Linear* in the Graph Editor.

**Whole scene in slow motion:** set **Playback Speed** to 0.5, then click **Fit Timeline** so the timeline is long enough.

**Ramp into slow motion:** key **Playback Speed** at 1.0 on frame 100 and 0.25 on frame 130, then 0.25 on frame 190 and 1.0 on frame 220. Click **Fit Timeline** afterwards.

**Freeze the final pose:** set **Outside Take** to *Hold*. The last frame stays after the take ends.

**Remove a floor patch or stand:** click **Add Crop Box**, fit the box around the patch, and tick **Invert**.

**Loop a short movement:** trim to the movement and set **Outside Take** to *Loop* or *Ping-Pong*.

## 12. Performance tips

- Playback is fastest in the **Rendered** or **Material Preview** viewport with EEVEE. Full detail runs at about 27 fps with full-quality colour, and 30 fps without, on an RTX 5070 Ti laptop.
- Full-quality colour costs about 12 ms of CPU time per 100k-splat frame. On a slow CPU, turn **View-Dependent Colour** off while editing timing, and back on to review and render.
- If playback stutters, lower **Playback Detail** to 0.5, or 0.25 on integrated graphics. Paused frames and renders still use every splat.
- Hide takes you're not working on (eye icon in the take list). Hidden takes cost nothing.
- Keep caches on an SSD. Each frame reads about 3 MB.
- Echoes multiply the splat count; keep *Echo Density* low.

## 13. Troubleshooting

| Problem | Fix |
|---|---|
| *"No .ply frames found"* | Pick the take's `.zip`, its frame folder, or one of its `.ply` files. Frame files must end in a number (`…0000123.ply`). |
| *"Not a Gaussian splat PLY"* | The PLY is a plain point cloud or mesh, not 3DGS splats. It needs the `f_dc_*`, `opacity`, `scale_*`, `rot_*` properties. |
| *"No converted cache for this take"* | The cache was moved or deleted. Point **Files › Cache** at it, or click **Convert**. |
| Conversion stopped or failed | Click **Convert** to resume. If a disk was full, free space first. The error text is shown in the panel. |
| Performer lying down or upside down | Change **Take › Up Axis**. |
| Performer faces away from the camera | Rotate **Splat Camera Rig** 180° on Z, or rotate the take object. |
| Shading looks flatter or lighter than in other 3DGS viewers | The take uses a compact cache. Click **Look › Upgrade to Full Quality**, and make sure **View-Dependent Colour** is on. |
| Colours don't follow my viewport after orbiting | Colours follow the largest 3D viewport in Rendered / Material Preview shading. They update a moment after you stop moving, and every frame while playing. |
| Take looks grey or blobby | Switch the viewport to **Rendered** or **Material Preview** (Solid mode shows proxies). |
| Colours look washed out | Use the **Standard** view transform (*Render › Colour Management*). *Set Up Viewing* sets it. |
| Dark edges in Cycles | Raise *Light Paths › Transparent* bounces to 512+. |
| Take ends too early or too late after a speed change | Click **Fit Timeline**. It follows Speed, Playback Speed and their keyframes. |
| Nothing shows at some frames | The take is *Hidden* outside its range, or a Split/Cut part isn't active there. Check **Outside Take**, **Start Frame** and **Trim**. |
| Splats vanished after editing | Check **Crop** values, **Crop Box › Use Box**, **Min Opacity** and **Max Radius**. The *Reset* buttons restore defaults. |
| File opened but no splats | Make sure the extension is installed and enabled. Splats aren't stored in the .blend; they stream from the cache. |
