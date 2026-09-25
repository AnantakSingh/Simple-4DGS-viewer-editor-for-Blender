"""Build the installable zip (plain Python, no Blender needed):

    python dev/build_zip.py [output folder]

All files go inside one top-level folder, `blender_4dgs_viewer_editor/`, so the same
zip installs both ways:
  * Blender 4.2+ extension: Preferences > Get Extensions > Install from Disk
    (Blender accepts one top-level folder holding blender_manifest.toml)
  * classic add-on: Preferences > Add-ons > Install legacy Add-on (needs __init__.py
    inside a folder, plus bl_info)
"""
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = "blender_4dgs_viewer_editor"
SRC = os.path.join(ROOT, "source", PKG)


def version():
    with open(os.path.join(SRC, "blender_manifest.toml"), encoding="utf-8") as f:
        manifest = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M).group(1)
    with open(os.path.join(SRC, "__init__.py"), encoding="utf-8") as f:
        legacy = re.search(r'"version":\s*\((\d+),\s*(\d+),\s*(\d+)\)', f.read())
    legacy = ".".join(legacy.groups())
    if manifest != legacy:
        sys.exit(f"version mismatch: blender_manifest.toml {manifest} vs bl_info {legacy}")
    return manifest


def build(out_dir):
    out = os.path.join(out_dir, f"{PKG}-{version()}.zip")
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirnames, filenames in os.walk(SRC):
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__" and not d.startswith("."))
            for name in sorted(filenames):
                if name.startswith(".") or name.endswith((".pyc", ".pyo")):
                    continue
                path = os.path.join(dirpath, name)
                arc = PKG + "/" + os.path.relpath(path, SRC).replace(os.sep, "/")
                z.write(path, arc)
                count += 1
    print(f"created {out} ({count} files, inside {PKG}/)")
    return out


if __name__ == "__main__":
    build(os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else ROOT)
