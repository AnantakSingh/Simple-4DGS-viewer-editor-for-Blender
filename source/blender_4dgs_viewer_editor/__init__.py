"""Blender 4DGS Viewer/Editor: view and edit 4D Gaussian splat (4DGS) captures in Blender.

Import a take (folder of .ply frames, one of its .ply files, or the take .zip).
The frames are converted once into a compact cache in the background, then
streamed onto a point-cloud object as the timeline plays. Renders in EEVEE and Cycles.
"""
# Used only when installed as a classic add-on (Preferences > Add-ons > Install legacy
# Add-on); Blender 4.2+ extensions read blender_manifest.toml instead.
bl_info = {
    "name": "Blender 4DGS Viewer/Editor",
    "author": "Anantak Singh",
    "version": (2, 3, 1),
    "blender": (4, 2, 0),
    "location": "File > Import > 4DGS Splat Sequence; View3D > Sidebar > Splats",
    "description": "View and edit 4D Gaussian splat (4DGS) sequences",
    "doc_url": "https://github.com/AnantakSingh/Simple-4DGS-viewer-editor-for-Blender",
    "category": "Import-Export",
}

from . import props, playback, operators, editing, ui, jobs  # noqa: E402

_modules = (props, playback, operators, editing, ui)


def register():
    for m in _modules:
        m.register()


def unregister():
    jobs.unregister()
    for m in reversed(_modules):
        m.unregister()
