"""Background conversion jobs.

convert.py runs as a child process with Blender's bundled Python (which has numpy),
so conversion uses several CPU cores and never blocks the UI. A timer polls
progress and finishes the import when the cache is ready.
"""
import atexit
import os
import queue
import subprocess
import sys
import threading
import uuid

import bpy

_CONVERTER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "convert.py")
_jobs = {}          # job id -> Job


class Job:
    def __init__(self, source_path, cache_dir, workers, on_done, with_sh=False):
        self.id = uuid.uuid4().hex
        self.cache_dir = cache_dir
        self.on_done = on_done          # callable(job) run on the main thread when finished
        self.done = 0
        self.total = 0
        self.error = ""
        self.finished = False
        self.cancelled = False
        self._lines = queue.Queue()
        cmd = [sys.executable, "-I", _CONVERTER, source_path, cache_dir, "--machine"]
        if with_sh:
            cmd.append("--sh")
        if workers:
            cmd += ["--workers", str(workers)]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, bufsize=1, creationflags=flags)
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in self.proc.stdout:
            self._lines.put(line.rstrip())
        self._lines.put(None)

    @property
    def progress(self):
        return self.done / self.total if self.total else 0.0

    def poll(self):
        """Consume output; return True once the process has exited."""
        tail = []
        while True:
            try:
                line = self._lines.get_nowait()
            except queue.Empty:
                return False
            if line is None:
                self.proc.wait()
                if self.proc.returncode != 0 and not self.error and not self.cancelled:
                    self.error = "\n".join(tail[-5:]) or f"converter exited with code {self.proc.returncode}"
                return True
            if line.startswith("PROGRESS "):
                _, done, total = line.split()
                self.done, self.total = int(done), int(total)
            elif line.startswith("ERROR "):
                self.error = line[6:]
            elif not line.startswith("DONE"):
                tail.append(line)

    def cancel(self):
        self.cancelled = True
        if self.proc.poll() is None:
            if os.name == "nt":     # also stop the converter's worker processes
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                self.proc.terminate()


def start(source_path, cache_dir, workers, on_done, with_sh=False):
    job = Job(source_path, cache_dir, workers, on_done, with_sh)
    _jobs[job.id] = job
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.2)
    return job


def get(job_id):
    return _jobs.get(job_id)


def cancel(job_id):
    job = _jobs.get(job_id)
    if job:
        job.cancel()


def _redraw():
    wm = bpy.context.window_manager
    for window in (wm.windows if wm else ()):
        for area in window.screen.areas:
            if area.type in {"VIEW_3D", "PROPERTIES"}:
                area.tag_redraw()


def _tick():
    for job_id, job in list(_jobs.items()):
        if job.poll():
            job.finished = True
            del _jobs[job_id]
            try:
                job.on_done(job)
            except Exception as e:  # noqa: BLE001 - never let the timer die
                print(f"Blender 4DGS Viewer/Editor: finishing import failed: {e}")
    _redraw()
    return 0.25 if _jobs else None


def cancel_all():
    for job in list(_jobs.values()):
        job.cancel()


atexit.register(cancel_all)


def unregister():
    cancel_all()
    _jobs.clear()
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
