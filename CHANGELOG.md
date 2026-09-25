# Changelog

## 2.2.0 (2026-09-24)

- **Compact cache is the default again**: it's the most stable option (smallest, fastest playback, lowest memory). Full-Quality Colour stays available in the import dialog, and as **Upgrade to Full Quality** per take.
- First public release on GitHub.

## 2.1.0 (2026-09-24)

- **Full-quality colour** (on by default): the cache keeps each splat's view-dependent colour (spherical harmonics, float16), and playback evaluates it toward the render camera or the viewport's eye every frame. Verified against an independent reference built from the original PLY: 68 dB PSNR (visually identical), vs 30.7 dB for the compact cache.
- **Upgrade to Full Quality** button for compact caches: adds the missing colour data in place (41 s for the 890-frame sample take).
- **View-Dependent Colour** toggle per take (Look panel); the Files panel shows the cache type.
- Orbiting the viewport while paused re-colours splats for the new viewpoint.
- Threaded SH evaluation: about 10 ms per 110k-splat frame. Playback 27.3 fps with full colour (29.8 compact).
- Converter CLI: `--sh`.

## 2.0.0 (2026-09-24)

- Named **Blender 4DGS Viewer/Editor** (extension id `blender_4dgs_viewer_editor`). It reads any 4DGS take stored as a sequence of 3DGS `.ply` frames.
- Import menu: *File › Import › 4DGS Splat Sequence*. Node group and material: "4DGS Splats" / "4DGS Splat".
- Documented cache quality: float16 storage is visually lossless; dropping view-dependent colour is a visible loss (about 30 dB PSNR).

## 1.2.0 (2026-09-24)

- **Playback Speed:** a scene-wide speed control at the top of the Splats panel. It multiplies every take's own Speed, never changes the scene frame rate, and applies to renders.
- **Keyframable speed:** keyframe Playback Speed and/or a take's Speed for smooth speed ramps. Speed is added up frame by frame, so ramps don't jump. Trim, Split, Cut, Reset Timing and Fit Timeline all follow the ramp.
- Speed can now go to 0 (pause) when keyframed.
- Reset Timing also removes Speed keyframes.

## 1.1.0 (2026-09-24)

**Editing and look tools**
- **Timing:** Trim Start / Trim End at the playhead, **Split** at the playhead, **Cut Range** (with Close Gap), Speed, Reverse, Ping-Pong looping, Freeze Frame, keyframable **Time Remap** (with a *Key Take Frame* button), Fit Timeline, Reset Timing.
- **Crop:** Left / Right / Front / Back / Bottom / Top in upright take space, soft **Feather**, and a free-form **Crop Box** object with Invert. All keyframable.
- **Look:** Opacity (for fades), Max Splat Radius (floater clean-up), Density, Exposure, Saturation, Hue Shift, Tint.
- **Echoes:** onion-skin motion trails (count, spacing, fade, density).
- The sidebar is reorganised into Take / Timing / Crop / Look / Echoes / Files panels.
- Takes with the default -Y up axis now face Blender's Front view (−Y), so crop directions match the numpad views.
- Up Axis can be changed after import.

## 1.0.0 (2026-09-24)

- First release as a Blender extension.
- One-step import from a take `.zip`, its folder, or any `.ply` in it; drag-and-drop into the viewport.
- Background conversion in a child process with progress, cancel and resume. The importance-sorted cache is about 7× smaller than the PLYs and is reused automatically.
- Real-time streaming playback on a point cloud; about 30 fps at 100k+ splats in the EEVEE viewport.
- A ray-space Gaussian splat shader that matches in EEVEE and Cycles.
- Set Up Viewing: camera in front of the performer, dark backdrop, Standard colour, frame range, rendered viewport.
- Several takes per scene; small `.blend` files (splats stream from the cache).
