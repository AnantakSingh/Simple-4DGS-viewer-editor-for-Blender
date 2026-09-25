"""Timeline frame -> take frame mapping (trim, speed, reverse, looping, freeze, remap).

Everything here is pure arithmetic on a settings object (Object.b4d) so it can be
unit-tested without Blender. Indices are 0-based positions in the full take;
the user-facing trim/freeze/remap values are 1-based take frames.

Speed is handled by a Clock: how far into the take we are at a timeline frame.
With a constant speed that is (t - start) * speed. With a keyframed speed (per
take and/or the scene's Playback Speed) it is the speed summed frame by frame
from the start, so speed ramps play smoothly instead of jumping.
"""
import math

REMAP_PATH = "b4d.remap_frame"
SPEED_PATH = "b4d.speed"
SCENE_SPEED_PATH = "b4d_speed"
_EPS = 1e-6
_SEARCH_LIMIT = 1_000_000       # frames; guards against speed curves stuck at 0


class Clock:
    """Take-time elapsed since `start` at timeline frames, for a constant or per-frame speed."""

    def __init__(self, start, speed=1.0, speed_at=None):
        self.start = start
        self.speed = max(speed, 0.0)
        self.speed_at = speed_at        # callable(frame) -> speed, or None for constant

    def _rate(self, frame):
        return max(self.speed_at(frame), 0.0) if self.speed_at else self.speed

    def elapsed(self, t):
        if self.speed_at is None:
            return (t - self.start) * self.speed
        if t >= self.start:
            return sum(self._rate(f) for f in range(self.start, t))
        return -sum(self._rate(f) for f in range(t, self.start))

    def local_at(self, t):
        return math.floor(self.elapsed(t) + _EPS)

    def first_frame_showing(self, local):
        """First timeline frame whose position is >= `local` (None if it is never reached)."""
        if self.speed_at is None:
            if self.speed <= 0:
                return self.start if local <= 0 else None
            return self.start + math.ceil(local / self.speed - _EPS)
        t, acc = self.start, 0.0
        if local <= 0:                  # walk backwards while the previous frame still qualifies
            while t - self.start > -_SEARCH_LIMIT:
                prev = acc - self._rate(t - 1)
                if math.floor(prev + _EPS) < local:
                    return t
                acc, t = prev, t - 1
            return t
        while t - self.start < _SEARCH_LIMIT:
            if math.floor(acc + _EPS) >= local:
                return t
            acc += self._rate(t)
            t += 1
        return None


def default_clock(s):
    return Clock(s.start_frame, s.speed)


def trim_range(s, n):
    """(first, last) 0-based take indices kept by the trim, always valid for n >= 1."""
    lo = min(max(s.trim_in, 1), n) - 1
    hi = (s.trim_out if s.trim_out > 0 else n) - 1
    return lo, min(max(hi, lo), n - 1)


def trimmed_length(s, n):
    lo, hi = trim_range(s, n)
    return hi - lo + 1


def timeline_span(s, n, clock=None):
    """(first, last) timeline frames of one pass of the take."""
    clock = clock or default_clock(s)
    end = clock.first_frame_showing(trimmed_length(s, n))
    if end is None:                     # never finishes (speed 0): report a long span
        end = s.start_frame + 100_000
    return s.start_frame, max(s.start_frame, end - 1)


def timeline_length(s, n, clock=None):
    first, last = timeline_span(s, n, clock)
    return last - first + 1


def local_at(s, timeline_frame, clock=None):
    """Unwrapped position (0 = first trimmed frame) at a timeline frame, before range handling."""
    return (clock or default_clock(s)).local_at(timeline_frame)


def timeline_frame_for_local(s, local, clock=None):
    """First timeline frame at which `local` (0-based trimmed position) is shown."""
    t = (clock or default_clock(s)).first_frame_showing(local)
    return s.start_frame if t is None else t


def take_index(s, timeline_frame, n, remap_value=None, clock=None):
    """0-based take index to show at `timeline_frame`, or None to show nothing."""
    lo, hi = trim_range(s, n)
    length = hi - lo + 1
    if s.freeze:
        return min(max(s.freeze_frame - 1, lo), hi)
    if s.use_time_remap:
        value = s.remap_frame if remap_value is None else remap_value
        return min(max(int(round(value)) - 1, lo), hi)

    local = local_at(s, timeline_frame, clock)
    if not 0 <= local < length:
        mode = s.out_of_range
        if mode == "HIDE":
            return None
        if mode == "HOLD":
            local = min(max(local, 0), length - 1)
        elif mode == "LOOP":
            local %= length
        elif mode == "PING_PONG":
            period = 2 * length - 2
            if period <= 0:
                local = 0
            else:
                local %= period
                if local >= length:
                    local = period - local
    if s.reverse:
        local = length - 1 - local
    return lo + local


# --------------------------------------------------------------------------- animation access

def find_fcurve(id_data, path):
    """(fcurve collection, fcurve) animating `path` on an ID, or (None, None).

    Handlers run before Blender evaluates animation for the new frame, so animated
    values are read straight from the F-Curves. Supports legacy and layered (4.4+) actions.
    """
    ad = getattr(id_data, "animation_data", None)
    action = ad.action if ad else None
    if action is None:
        return None, None
    fcurves = getattr(action, "fcurves", None)
    if fcurves is not None:
        try:
            fc = fcurves.find(path)
            if fc is not None:
                return fcurves, fc
        except (AttributeError, RuntimeError):
            pass
    slot = getattr(ad, "action_slot", None)
    for layer in getattr(action, "layers", ()):
        for strip in layer.strips:
            channelbag = strip.channelbag(slot) if slot is not None and hasattr(strip, "channelbag") else None
            if channelbag is not None:
                fc = channelbag.fcurves.find(path)
                if fc is not None:
                    return channelbag.fcurves, fc
    return None, None


def remap_value(obj, frame):
    """The keyframed Take Frame (b4d.remap_frame) at `frame`, or None if it isn't animated."""
    _coll, fc = find_fcurve(obj, REMAP_PATH)
    return fc.evaluate(frame) if fc is not None else None


def clock_for(obj, scene):
    """Clock combining the take's Speed and the scene's Playback Speed, keyframed or not."""
    s = obj.b4d
    master = getattr(scene, SCENE_SPEED_PATH, 1.0)
    _c, take_fc = find_fcurve(obj, SPEED_PATH)
    _c, scene_fc = find_fcurve(scene, SCENE_SPEED_PATH)
    if take_fc is None and scene_fc is None:
        return Clock(s.start_frame, s.speed * master)

    def speed_at(frame):
        a = take_fc.evaluate(frame) if take_fc is not None else s.speed
        b = scene_fc.evaluate(frame) if scene_fc is not None else master
        return a * b
    return Clock(s.start_frame, speed_at=speed_at)


def clear_animation(id_data, path):
    coll, fc = find_fcurve(id_data, path)
    if fc is not None:
        coll.remove(fc)
