# Blender 4DGS Viewer/Editor

View, edit and render **4D Gaussian splat (4DGS) captures** in Blender: sequences of 3DGS `.ply` frames. Import a take, press play, and the performer moves in the viewport in real time. The same result renders in **EEVEE and Cycles**.

## Quick start

1. **Download** `blender_4dgs_viewer_editor-2.3.1.zip` from the [Releases page](https://github.com/AnantakSingh/Simple-4DGS-viewer-editor-for-Blender/releases). Don't unzip it.
2. **Install:** in Blender, go to *Edit › Preferences › Get Extensions › ⌄ › Install from Disk…* and pick the zip. (It also installs as a classic add-on: *Preferences › Add-ons › ⌄ › Install legacy Add-on…*.)
3. **Import:** go to *File › Import › 4DGS Splat Sequence*. Pick a take `.zip`, the folder of `.ply` frames, or any `.ply` inside it. You can also drag the `.zip` into the viewport.
4. **Play:** press <kbd>Space</kbd>. The first import of a take converts it in the background (about 20 s for 900 frames on an SSD). After that it opens instantly.

Every control is in the viewport sidebar: press <kbd>N</kbd> and open the **Splats** tab.

For a full walk-through, see the **[Usage Guide](USAGE_GUIDE.md)**. For how it works, see the **[Technical Reference](TECHNICAL.md)**.

## What it does

| | |
|---|---|
| **One-step import** | Takes a `.zip`, a folder, or a single `.ply`. The take is converted once into a fast cache in a background process, with a progress bar and cancel/resume. |
| **Real-time playback** | About 30 fps with 100k+ splats per frame in the EEVEE rendered viewport (RTX 5070 Ti laptop). A *Playback Detail* slider helps on slower GPUs. |
| **EEVEE + Cycles** | A custom splat shader renders both engines to match. Cycles gets exact transparency and correct ray-traced compositing. |
| **Timing edits** | Trim start/end, Split at playhead, Cut a range (with close-gap), Speed, Reverse, Loop / Ping-Pong / Hold / Hide, Freeze Frame, and keyframable **Time Remap**. |
| **Playback speed** | A scene-wide **Playback Speed** plus per-take **Speed**. Neither changes the frame rate. Both can be keyframed for smooth speed ramps, and both apply to renders. |
| **Crop** | Crop Left, Right, Front, Back, Bottom and Top in the take's own upright space, with a soft **Feather**. A free-form **Crop Box** object can also crop, and can be inverted. Everything is keyframable. |
| **Look** | Size, Opacity (fades), Min Opacity, Max Radius (floater clean-up), Density, Exposure, Saturation, Hue Shift, Tint. |
| **Echoes** | Onion-skin motion trails of earlier frames. |
| **Many takes** | Each take is its own object, with its own settings, timing and position. |
| **Two cache modes** | **Compact** (default): the most stable and fastest option, about 3 GB per 900-frame take, with slightly flatter shading. **Full-quality colour** (optional, or upgrade later): keeps each splat's view-dependent colour and evaluates it toward the camera or viewport eye, exactly as 3DGS viewers do. It matches an independent reference at **68 dB PSNR** (visually identical), with a 4× larger cache. Each shoot is **flagged**: the plugin measures whether the capture has view-dependent colour and how much compact drops for that shoot. See [Cache quality](TECHNICAL.md#cache-quality). |
| **Small .blend files** | Splats aren't saved in the .blend; they're streamed from the cache. |

## Repository contents

| Path | What |
|---|---|
| `README.md` | This overview. |
| `USAGE_GUIDE.md` | Step-by-step guide for artists: import, playback, every panel, recipes, troubleshooting. |
| `TECHNICAL.md` | Pipeline, data and cache formats, rendering maths, performance, development. |
| `CHANGELOG.md` | Version history. |
| `LICENSE` | GPL-3.0-or-later (like Blender). |
| `source/blender_4dgs_viewer_editor/` | Extension source code. |
| `dev/` | Automated tests (see [TECHNICAL.md](TECHNICAL.md#development-testing-and-release)). |

The installable zip is attached to each [release](https://github.com/AnantakSingh/Simple-4DGS-viewer-editor-for-Blender/releases). Don't use GitHub's green *Code › Download ZIP*: that's the whole repository, not an installable add-on. To build it yourself from `source/`, see [Building a release](TECHNICAL.md#development-testing-and-release).

## Requirements

- **Blender 4.2 or newer**, tested on **5.1 and 5.2**. Windows is tested; the code is cross-platform.
- A GPU that runs EEVEE comfortably. For Cycles, an NVIDIA (OptiX/CUDA) or other supported GPU is recommended.
- Disk space for the cache, per 900-frame take of about 100k splats: about **3 GB compact** (default) or **12 GB full quality** (the source PLYs are about 20 GB).
- Input: 4DGS takes as sequences of binary little-endian 3DGS `.ply` frames (one file per frame), zipped or unzipped.
