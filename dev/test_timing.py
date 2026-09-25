"""Unit tests for timing.py (plain Python, no Blender):  python dev/test_timing.py"""
import importlib.util
import os
import types

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "timing", os.path.join(HERE, "..", "source", "blender_4dgs_viewer_editor", "timing.py"))
timing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(timing)


def S(**kw):
    base = dict(start_frame=1, trim_in=1, trim_out=0, speed=1.0, reverse=False, out_of_range="HOLD",
                freeze=False, freeze_frame=1, use_time_remap=False, remap_frame=1.0)
    base.update(kw)
    return types.SimpleNamespace(**base)


def show(s, frames, n=10):
    return [timing.take_index(s, f, n) for f in frames]


def eq(a, b, msg):
    assert a == b, f"{msg}: {a} != {b}"
    print("ok ", msg)


eq(show(S(), range(0, 13)), [0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9], "hold")
eq(show(S(out_of_range="HIDE"), [0, 1, 10, 11]), [None, 0, 9, None], "hide")
eq(show(S(out_of_range="LOOP"), [10, 11, 12, 21]), [9, 0, 1, 0], "loop")
eq(show(S(out_of_range="PING_PONG", trim_out=4), range(1, 11)), [0, 1, 2, 3, 2, 1, 0, 1, 2, 3], "ping-pong")
eq(show(S(trim_in=3, trim_out=6), range(1, 6)), [2, 3, 4, 5, 5], "trim")
eq(show(S(reverse=True, trim_out=4), range(1, 6)), [3, 2, 1, 0, 0], "reverse")
eq(show(S(speed=0.5, trim_out=3), range(1, 8)), [0, 0, 1, 1, 2, 2, 2], "half speed")
eq(show(S(speed=2.0), range(1, 7)), [0, 2, 4, 6, 8, 9], "double speed")
eq(show(S(freeze=True, freeze_frame=7), [1, 50]), [6, 6], "freeze")
eq(timing.take_index(S(use_time_remap=True), 5, 10, remap_value=3.6), 3, "remap rounds")
eq(timing.timeline_span(S(start_frame=5, trim_in=3, trim_out=6, speed=0.5), 10), (5, 12), "span")
eq(timing.trim_range(S(trim_in=50, trim_out=2), 10), (9, 9), "clamped trim")

# split arithmetic: forward at playhead frame 5 (take index 4)
s = S()
idx = timing.take_index(s, 5, 10)
a, b = S(trim_out=idx, out_of_range="HIDE"), S(trim_in=idx + 1, start_frame=5, out_of_range="HIDE")
eq([timing.take_index(a, f, 10) for f in range(1, 11)] , [0, 1, 2, 3] + [None] * 6, "split A")
eq([timing.take_index(b, f, 10) for f in range(1, 11)], [None] * 4 + [4, 5, 6, 7, 8, 9], "split B")

# cut take frames 4..6 (1-based) with close-gap
a = S(trim_out=3, out_of_range="HIDE")
b = S(trim_in=7, start_frame=timing.timeline_span(a, 10)[1] + 1, out_of_range="HIDE")
merged = [timing.take_index(a, f, 10) if timing.take_index(a, f, 10) is not None else timing.take_index(b, f, 10)
          for f in range(1, 9)]
eq(merged, [0, 1, 2, 6, 7, 8, 9, None], "cut + close gap")
# ---- clocks: constant / scene multiplier / keyframed ramps --------------------------------
Clock = timing.Clock
s = S()
eq([timing.take_index(s, f, 10, clock=Clock(1, 0.5)) for f in range(1, 6)], [0, 0, 1, 1, 2],
   "scene speed 0.5 multiplies the take")
const = Clock(1, 0.5)
ramp_equiv = Clock(1, speed_at=lambda f: 0.5)
eq([const.local_at(f) for f in range(-3, 12)], [ramp_equiv.local_at(f) for f in range(-3, 12)],
   "per-frame clock matches constant clock")
eq([const.first_frame_showing(k) for k in range(-2, 5)],
   [ramp_equiv.first_frame_showing(k) for k in range(-2, 5)], "frame search matches constant clock")
ramp = Clock(1, speed_at=lambda f: 1.0 if f < 5 else 0.25)      # normal speed, then quarter speed
eq([ramp.local_at(f) for f in range(1, 14)], [0, 1, 2, 3, 4, 4, 4, 4, 5, 5, 5, 5, 6], "speed ramp is smooth")
eq(ramp.first_frame_showing(5), 9, "frame search on a ramp")
eq(timing.timeline_span(S(trim_out=6), 10, ramp), (1, 12), "span on a ramp")
paused = Clock(1, speed_at=lambda f: 0.0 if 3 <= f < 6 else 1.0)
eq([paused.local_at(f) for f in range(1, 9)], [0, 1, 2, 2, 2, 2, 3, 4], "speed 0 pauses")
eq(Clock(1, 0.0).first_frame_showing(3), None, "constant speed 0 never reaches later frames")
print("all timing tests passed")
