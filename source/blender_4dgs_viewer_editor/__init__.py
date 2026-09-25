"""Blender 4DGS Viewer/Editor: view and edit 4D Gaussian splat (4DGS) captures in Blender.

Import a take (folder of .ply frames, one of its .ply files, or the take .zip).
The frames are converted once into a compact cache in the background, then
streamed onto a point-cloud object as the timeline plays. Renders in EEVEE and Cycles.
"""
from . import props, playback, operators, editing, ui, jobs

_modules = (props, playback, operators, editing, ui)


def register():
    for m in _modules:
        m.register()


def unregister():
    jobs.unregister()
    for m in reversed(_modules):
        m.unregister()
