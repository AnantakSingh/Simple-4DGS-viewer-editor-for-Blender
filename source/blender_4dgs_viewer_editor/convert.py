"""4DGS (3DGS .ply sequence) -> splat cache converter.

This module has no Blender dependency (numpy only). The add-on runs it as a child
process with Blender's bundled Python, and it can also be run by hand to
pre-convert takes, e.g. on another machine:

    python convert.py <take folder | any .ply in it | take .zip> <cache folder> [--workers N]

Cache layout (version 2):
    <cache>/meta.json            written last; its presence marks a complete cache
    <cache>/frames/NNNNNN.npy    one structured array per frame, SPLAT_DTYPE, 34 B/splat,
                                 sorted by importance so any prefix is a good LOD subset
    <cache>/frames/NNNNNN.sh.npy optional (--sh, "full-quality colour"): float16 (n, 3 + 3k),
                                 same order: base = 0.5 + C0*f_dc (unclamped) then f_rest
                                 channel-major, k = 3/8/15 coefficients for SH degree 1/2/3
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import zipfile

import numpy as np

try:                                    # inside Blender: part of the extension package
    from . import sh as _sh
except ImportError:                     # run as a script / multiprocessing child
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import sh as _sh

CACHE_VERSION = 2
SH_C0 = 0.28209479177387814

SPLAT_DTYPE = np.dtype([
    ("pos", "<f4", 3),      # position, source coordinates
    ("rot", "<f2", 4),      # unit quaternion (w, x, y, z)
    ("scale", "<f2", 3),    # per-axis standard deviation (linear)
    ("color", "<f2", 3),    # linear-light RGB from the SH DC term
    ("opacity", "<f2"),     # 0..1
])

PLY_TYPES = {
    "float": "<f4", "float32": "<f4", "double": "<f8", "float64": "<f8",
    "uchar": "u1", "uint8": "u1", "char": "i1", "int8": "i1",
    "ushort": "<u2", "uint16": "<u2", "short": "<i2", "int16": "<i2",
    "uint": "<u4", "uint32": "<u4", "int": "<i4", "int32": "<i4",
}
REQUIRED = ("x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
            "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3")
FRAME_RE = re.compile(r"(\d+)\.ply$", re.IGNORECASE)


# --------------------------------------------------------------------------- source discovery

class Source:
    """An ordered list of .ply frames living in a folder or inside a .zip."""

    def __init__(self, kind, root, frames, take):
        self.kind = kind            # "folder" | "zip"
        self.root = root            # folder path or zip path
        self.frames = frames        # [(frame_number, name_or_member, size)]
        self.take = take

    @property
    def signature(self):
        h = hashlib.sha1()
        for num, name, size in self.frames:
            h.update(f"{num}:{os.path.basename(name)}:{size};".encode())
        return h.hexdigest()[:16]

    def open_reader(self):
        return FrameReader(self)


def _take_name(path):
    name = os.path.basename(os.path.normpath(path))
    for suffix in (".zip", ".ply"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
    return name or "Splats"


def _numbered(names_sizes):
    frames = []
    for name, size in names_sizes:
        m = FRAME_RE.search(name)
        if m:
            frames.append((int(m.group(1)), name, size))
    frames.sort()
    return frames


def find_source(path):
    """Resolve a user-picked path (take folder, a .ply inside it, or a .zip) to a Source."""
    path = os.path.abspath(path)
    if os.path.isfile(path) and path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            members = [(i.filename, i.file_size) for i in z.infolist()
                       if not i.is_dir() and i.filename.lower().endswith(".ply")]
        # A zip may hold several folders; use the one with the most frames.
        by_dir = {}
        for name, size in members:
            by_dir.setdefault(os.path.dirname(name), []).append((name, size))
        if not by_dir:
            raise ValueError(f"No .ply frames found in {path}")
        best_dir = max(by_dir, key=lambda d: len(by_dir[d]))
        frames = _numbered(by_dir[best_dir])
        take = os.path.basename(best_dir) or _take_name(path)
        if not frames:
            raise ValueError(f"No numbered .ply frames found in {path}")
        return Source("zip", path, frames, _take_name(take))

    if os.path.isfile(path):
        path = os.path.dirname(path)
    if not os.path.isdir(path):
        raise ValueError(f"Not a folder, .ply or .zip: {path}")

    # The chosen folder, or the sub-folder (up to 3 levels deep) with the most frames.
    best = None
    base_depth = path.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(path):
        if dirpath.count(os.sep) - base_depth >= 3:
            dirnames[:] = []
        plys = [f for f in filenames if f.lower().endswith(".ply")]
        if plys and (best is None or len(plys) > len(best[1])):
            best = (dirpath, plys)
    if best is None:
        raise ValueError(f"No .ply frames found in {path}")
    folder, plys = best
    frames = _numbered((os.path.join(folder, f), os.path.getsize(os.path.join(folder, f))) for f in plys)
    if not frames:
        raise ValueError(f"No numbered .ply frames found in {folder}")
    return Source("folder", folder, frames, _take_name(folder))


class FrameReader:
    """Reads raw frame bytes / arrays. Opens its own zip handle (one per process)."""

    def __init__(self, source):
        self.source = source
        self._zip = zipfile.ZipFile(source.root) if source.kind == "zip" else None

    def read(self, index):
        _num, name, _size = self.source.frames[index]
        if self._zip is not None:
            with self._zip.open(name) as f:
                return parse_ply(f.read(), name)
        with open(name, "rb") as f:
            return parse_ply(f.read(), name)

    def close(self):
        if self._zip is not None:
            self._zip.close()


# --------------------------------------------------------------------------- PLY -> splats

def parse_ply(buf, name="<ply>"):
    end = buf.find(b"end_header")
    if not buf.startswith(b"ply") or end < 0:
        raise ValueError(f"{name}: not a PLY file")
    body = buf.index(b"\n", end) + 1
    header = buf[:body].decode("ascii", "replace").splitlines()
    if not any(l.strip() == "format binary_little_endian 1.0" for l in header):
        raise ValueError(f"{name}: only binary little-endian PLY is supported")
    count, fields, in_vertex, offset = 0, [], False, body
    for line in header:
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "element":
            in_vertex = parts[1] == "vertex"
            if in_vertex:
                count = int(parts[2])
        elif parts[0] == "property" and in_vertex:
            if parts[1] == "list":
                raise ValueError(f"{name}: list properties on vertices are not supported")
            fields.append((parts[2], PLY_TYPES[parts[1]]))
    missing = [f for f in REQUIRED if f not in dict(fields)]
    if missing:
        raise ValueError(f"{name}: not a Gaussian splat PLY (missing {', '.join(missing)})")
    return np.frombuffer(buf, dtype=np.dtype(fields), count=count, offset=offset)


def _srgb_to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def sh_degree_of(data):
    """SH degree stored in a parsed PLY (0 if it has no f_rest properties)."""
    rest = sum(1 for name in data.dtype.names if name.startswith("f_rest_"))
    per_channel = {0: 0, 3: 1, 8: 2, 15: 3}.get(rest // 3)
    if per_channel is None or rest % 3:
        raise ValueError(f"unsupported number of f_rest properties: {rest}")
    return per_channel


def to_splats(data, with_sh=False):
    """(splats, sh) for one parsed frame. `sh` is None unless with_sh and the PLY has SH."""
    dc = np.stack([data["f_dc_0"], data["f_dc_1"], data["f_dc_2"]], axis=1).astype(np.float64)
    color = _srgb_to_linear(np.clip(0.5 + SH_C0 * dc, 0.0, 1.0))
    opacity = 1.0 / (1.0 + np.exp(-data["opacity"].astype(np.float64)))
    scale = np.exp(np.stack([data["scale_0"], data["scale_1"], data["scale_2"]], axis=1).astype(np.float64))
    rot = np.stack([data["rot_0"], data["rot_1"], data["rot_2"], data["rot_3"]], axis=1).astype(np.float64)
    rot /= np.maximum(np.linalg.norm(rot, axis=1, keepdims=True), 1e-12)

    s = np.sort(scale, axis=1)
    order = np.argsort(-(opacity * s[:, 2] * s[:, 1]), kind="stable")

    out = np.empty(len(data), dtype=SPLAT_DTYPE)
    out["pos"] = np.stack([data["x"], data["y"], data["z"]], axis=1)[order]
    out["rot"] = rot[order]
    out["scale"] = scale[order]
    out["color"] = color[order]
    out["opacity"] = opacity[order]

    sh = None
    rest_names = sorted((n for n in data.dtype.names if n.startswith("f_rest_")), key=lambda n: int(n[7:]))
    if with_sh and rest_names:
        sh_degree_of(data)                                             # validates the layout
        rest = np.stack([data[n] for n in rest_names], axis=1)          # channel-major, as in 3DGS
        sh = np.concatenate([0.5 + SH_C0 * dc, rest], axis=1)[order].astype(np.float16)
    return out, sh


# --------------------------------------------------------------------------- cache

def analyse_view_dependence(source, frames=5, splats=20000, directions=64, seed=0):
    """How much colour a compact cache drops for this shoot.

    Samples `frames` evenly spaced frames, up to `splats` random splats each, and
    `directions` random view directions. For each splat and direction it measures how
    far the full colour (SH degrees 1-3) moves from the base colour a compact cache
    keeps, in 8-bit display levels (worst channel). Returns a dict for meta.json:
    degree, mean_levels, p95_levels, frames, rating (none / negligible / minor / visible).
    """
    n = len(source.frames)
    count = max(1, min(frames, n))
    picks = sorted({round(i * (n - 1) / max(count - 1, 1)) for i in range(count)})
    rng = np.random.default_rng(seed)
    dirs = rng.normal(size=(directions, 3))
    dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
    shifts, degree = [], None
    reader = source.open_reader()
    try:
        for index in picks:
            data = reader.read(index)
            deg = sh_degree_of(data)
            degree = deg if degree is None else min(degree, deg)
            if deg == 0:
                continue
            k = _sh.COEFFS[deg]
            sel = rng.choice(len(data), min(len(data), splats), replace=False)
            dc = np.stack([data[f"f_dc_{c}"][sel] for c in range(3)], axis=1).astype(np.float64)
            names = sorted((f for f in data.dtype.names if f.startswith("f_rest_")), key=lambda f: int(f[7:]))
            rest = np.stack([data[f][sel] for f in names], axis=1).astype(np.float64).reshape(len(sel), 3, -1)[:, :, :k]
            base = 0.5 + SH_C0 * dc
            delta = np.einsum("nck,dk->ndc", rest, _sh.basis(dirs, deg))
            full = np.clip(base[:, None, :] + delta, 0.0, 1.0)
            shifts.append((np.abs(full - np.clip(base, 0.0, 1.0)[:, None, :]).max(axis=2) * 255).ravel())
    finally:
        reader.close()
    if not degree or not shifts:
        return {"degree": 0, "mean_levels": 0.0, "p95_levels": 0.0, "frames": len(picks), "rating": "none"}
    values = np.concatenate(shifts)
    mean = float(values.mean())
    rating = "negligible" if mean < 1.0 else "minor" if mean < 3.0 else "visible"
    return {"degree": int(degree), "mean_levels": round(mean, 2),
            "p95_levels": round(float(np.percentile(values, 95)), 1), "frames": len(picks), "rating": rating}


def view_dependence_flag(meta):
    """One-line, human-readable flag: does this cache drop the shoot's view-dependent colour?"""
    meta = meta or {}
    vd = meta.get("view_dependence")
    if meta.get("sh_requested") and meta.get("sh_degree"):
        return f"Full quality: this shoot's view-dependent colour (SH degree {meta['sh_degree']}) is kept"
    if vd is None:
        return None
    if vd["degree"] == 0:
        return "This shoot has no view-dependent colour: the compact cache is lossless"
    return (f"Compact cache drops this shoot's view-dependent colour: SH degree {vd['degree']}, "
            f"avg {vd['mean_levels']:.1f} / p95 {vd['p95_levels']:.0f} levels ({vd['rating']})")


def write_meta(cache_dir, meta):
    path = os.path.join(cache_dir, "meta.json")
    with open(path + ".tmp", "w") as f:
        json.dump(meta, f, indent=1)
    os.replace(path + ".tmp", path)


def frame_path(cache_dir, frame_number):
    return os.path.join(cache_dir, "frames", f"{frame_number:06d}.npy")


def sh_path(cache_dir, frame_number):
    return os.path.join(cache_dir, "frames", f"{frame_number:06d}.sh.npy")


def read_meta(cache_dir):
    try:
        with open(os.path.join(cache_dir, "meta.json")) as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return None
    return meta if meta.get("version") == CACHE_VERSION else None


def cache_is_valid(cache_dir, source=None, need_sh=False):
    """Complete cache for `source`; with need_sh it must also hold view-dependent colour
    (or the source has none to hold)."""
    meta = read_meta(cache_dir)
    if meta is None or (source is not None and meta.get("signature") != source.signature):
        return False
    return not need_sh or meta.get("sh_requested", False)


_worker = {}


def _init_worker(source):
    _worker["reader"] = source.open_reader()


def _save(path, arr):
    tmp = path + ".tmp.npy"
    np.save(tmp, arr)
    os.replace(tmp, path)


def _convert_one(job):
    index, dst, sh_dst = job           # sh_dst is None when view-dependent colour isn't wanted
    if os.path.exists(dst) and (sh_dst is None or os.path.exists(sh_dst)):
        arr = np.load(dst, mmap_mode="r")          # resume / upgrade: this frame is done
    else:
        arr, sh = to_splats(_worker["reader"].read(index), with_sh=sh_dst is not None)
        if sh is not None:
            _save(sh_dst, sh)
        _save(dst, arr)
    p = arr["pos"]
    return index, len(arr), p.min(axis=0).tolist(), p.max(axis=0).tolist()


def convert(source, cache_dir, workers=None, progress=None, with_sh=False):
    """Convert every frame of `source` into `cache_dir`. Returns the meta dict.

    with_sh also stores view-dependent colour. Upgrading an existing compact cache
    keeps its frames' layout and only adds the .sh.npy files."""
    previous = read_meta(cache_dir) or {}
    frames_dir = os.path.join(cache_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    meta_path = os.path.join(cache_dir, "meta.json")
    if os.path.exists(meta_path):
        os.remove(meta_path)
    # Frames left by an interrupted run are reused only if they came from this exact source.
    sig_path = os.path.join(cache_dir, "source.sig")
    try:
        with open(sig_path) as f:
            same_source = f.read().strip() == source.signature
    except OSError:
        same_source = False
    if not same_source:
        for name in os.listdir(frames_dir):
            if name.endswith(".npy"):
                os.remove(os.path.join(frames_dir, name))
        with open(sig_path, "w") as f:
            f.write(source.signature)
    jobs = [(i, frame_path(cache_dir, num), sh_path(cache_dir, num) if with_sh else None)
            for i, (num, _n, _s) in enumerate(source.frames)]
    total = len(jobs)
    results = [None] * total
    workers = max(1, workers or min(8, os.cpu_count() or 4))

    if workers == 1:
        _init_worker(source)
        it = map(_convert_one, jobs)
        pool = None
    else:
        from multiprocessing import Pool
        pool = Pool(workers, initializer=_init_worker, initargs=(source,))
        it = pool.imap_unordered(_convert_one, jobs, chunksize=2)
    try:
        for done, (index, count, lo, hi) in enumerate(it, 1):
            results[index] = (count, lo, hi)
            if progress:
                progress(done, total)
    finally:
        if pool is not None:
            pool.terminate()

    counts = [r[0] for r in results]
    first_sh = sh_path(cache_dir, source.frames[0][0])
    sh_requested = bool(with_sh or (previous.get("sh_requested") and os.path.exists(first_sh)))
    sh_degree = 0
    if sh_requested and os.path.exists(first_sh):
        cols = np.load(first_sh, mmap_mode="r").shape[1]            # 3 + 3k
        sh_degree = {0: 0, 3: 1, 8: 2, 15: 3}[(cols - 3) // 3]
    meta = {
        "version": CACHE_VERSION,
        "take": source.take,
        "source": source.root,
        "source_kind": source.kind,
        "signature": source.signature,
        "frame_numbers": [num for num, _n, _s in source.frames],
        "counts": counts,
        "max_count": max(counts),
        "sh_requested": sh_requested,
        "sh_degree": sh_degree,
        "view_dependence": _safe_analysis(source, previous),
        "bounds_min": np.min([r[1] for r in results], axis=0).tolist(),
        "bounds_max": np.max([r[2] for r in results], axis=0).tolist(),
        "dtype": [[n, SPLAT_DTYPE.fields[n][0].base.str, list(SPLAT_DTYPE.fields[n][0].shape)]
                  for n in SPLAT_DTYPE.names],
    }
    write_meta(cache_dir, meta)
    return meta


def _safe_analysis(source, previous):
    """The shoot's view-dependence analysis; never fails a conversion."""
    if previous.get("signature") == source.signature and previous.get("view_dependence"):
        return previous["view_dependence"]
    try:
        return analyse_view_dependence(source)
    except Exception:  # noqa: BLE001 - the flag is informative only
        return None


# --------------------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description="Convert a 4DGS (3DGS .ply) sequence into a splat cache.")
    ap.add_argument("source", help="take folder, any .ply in it, or the take .zip")
    ap.add_argument("cache", help="output cache folder")
    ap.add_argument("--workers", type=int, default=None, help="parallel processes (default: up to 8)")
    ap.add_argument("--sh", action="store_true",
                    help="also store view-dependent colour (full quality, about 4x larger cache)")
    ap.add_argument("--machine", action="store_true", help="print machine-readable progress lines")
    args = ap.parse_args(argv)

    try:
        source = find_source(args.source)
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        print(f"ERROR {e}", flush=True)
        return 2
    if cache_is_valid(args.cache, source, need_sh=args.sh):
        print("DONE cached" if args.machine else f"Cache already up to date: {args.cache}", flush=True)
        return 0

    t0 = time.time()
    if not args.machine:
        print(f"{source.take}: {len(source.frames)} frames from {source.root}", flush=True)

    def progress(done, total):
        if args.machine:
            print(f"PROGRESS {done} {total}", flush=True)
        elif done % 50 == 0 or done == total:
            print(f"  {done}/{total} frames ({time.time() - t0:.0f}s)", flush=True)

    try:
        meta = convert(source, args.cache, args.workers, progress, with_sh=args.sh)
    except Exception as e:  # noqa: BLE001 - report any failure to the parent process
        print(f"ERROR {e}", flush=True)
        return 1
    if args.machine:
        print("DONE converted", flush=True)
    else:
        print(f"Done: {len(meta['counts'])} frames, {min(meta['counts'])}-{meta['max_count']} splats, "
              f"{time.time() - t0:.0f}s -> {args.cache}")
        flag = view_dependence_flag(meta)
        if flag:
            print(flag + ("" if meta["sh_requested"] or meta["view_dependence"]["degree"] == 0
                          else ". Use --sh to keep it."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
