"""Frametime analysis: turn a capture export into a defensible fps cap.

This is the part that makes SpeedyLock more than a copy-pasted convar list.

Average FPS is a bad target. What you actually feel is the slow tail: the
frames that arrive late. If you uncap, the GPU runs at 100% utilisation, sits
on the edge of its own power/thermal budget, and every extra millisecond of
some other frame lands directly in your input latency. Capping slightly below
the framerate your machine can *always* hold flattens that tail and produces a
consistent, lower-latency experience even though the number on the OSD drops.

So: read the capture, find the 1% low, and recommend the largest standard
refresh step at or below it.
"""

from __future__ import annotations

import csv
import io

# Refresh-friendly caps, ascending. People cap to refresh rate multiples.
STEPS = (30, 60, 72, 75, 90, 120, 144, 165, 180, 240, 360, 480)

# Header hints, most specific first. Checked before the generic "ms" so
# "frametime_ms" wins over an unrelated column that happens to contain "ms".
# GPU timings are deliberately NOT listed here: a capture with only a GPU column
# must not be mistaken for one that measures the frame interval.
_FRAME_HINTS = (
    "msbetweenpresents",
    "frametime",
    "frame_time",
    "frame time",
    "frametimes",
    "frame_times",
    "ft_ms",
)

# GPU *busy* time. PresentMon renames this column in every major version: 1.x
# writes msGPUActive, 2.3 writes GPUBusy, 2.4+ writes MsGPUBusy. They are the
# same measurement, so all three have to be recognised or a capture from a
# current build silently loses the GPU column and the diagnosis with it.
_GPU_BUSY_HINTS = (
    "msgpubusy",
    "gpubusy",
    "gpu_busy",
    "gpuactive",
    "gpu_active",
)

# Total GPU time. It includes time the GPU spent waiting, so it overstates how
# busy the GPU was and skews the ratio towards "GPU-bound". Used only when the
# capture has no busy column at all, and flagged so the report can say so.
_GPU_TIME_HINTS = ("msgputime", "gpu_time", "gputime")


class BenchError(Exception):
    pass


def _parse_float(cell):
    if cell is None:
        return None
    text = str(cell).strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _sniff_delimiter(text):
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        # Fall back to whichever candidate appears most in the first line.
        first = sample.splitlines()[0] if sample.splitlines() else ""
        best, best_count = ",", 0
        for delim in (",", ";", "\t", "|"):
            count = first.count(delim)
            if count > best_count:
                best, best_count = delim, count
        return best


def _classify_header_row(row):
    """Return (kind, index) if the row looks like a header with a time/fps col."""
    lowered = [c.strip().lower() for c in row]
    for i, name in enumerate(lowered):
        if not name:
            continue
        if "fps" in name:
            return ("fps", i)
    for i, name in enumerate(lowered):
        if not name:
            continue
        for hint in _FRAME_HINTS:
            if hint in name:
                return ("ms", i)
    for i, name in enumerate(lowered):
        if name in ("ms", "time", "value"):
            return ("ms", i)
    return None


def parse_frametimes(text):
    """Extract a list of frame times in milliseconds from a CSV-ish export.

    Accepts PresentMon-style CSV, CapFrameX semicolon exports, tab-separated
    dumps and a plain list of numbers. Columns named with an fps unit are
    converted. Raises BenchError when nothing usable is found.
    """
    if text is None:
        raise BenchError("no input")
    text = text.lstrip("\ufeff").strip()
    if not text:
        raise BenchError("the capture file is empty")

    delimiter = _sniff_delimiter(text)
    rows = [
        row
        for row in csv.reader(io.StringIO(text), delimiter=delimiter)
        if any(str(cell).strip() for cell in row)
    ]
    if not rows:
        raise BenchError("the capture file has no data rows")

    kind, column = "ms", None
    header = _classify_header_row(rows[0])
    data_start = 0
    if header is not None:
        kind, column = header
        data_start = 1
    elif all(_parse_float(c) is None for c in rows[0]):
        # A header row we do not recognise: skip it, choose a column below.
        data_start = 1

    body = rows[data_start:]
    if not body:
        raise BenchError("the capture file has a header but no frames")

    if column is None:
        # Pick the column with the most parseable numbers.
        width = max(len(r) for r in body)
        best_index, best_hits = None, 0
        for index in range(width):
            hits = sum(1 for r in body if index < len(r) and _parse_float(r[index]) is not None)
            if hits > best_hits:
                best_index, best_hits = index, hits
        if best_index is None or best_hits < max(2, len(body) // 2):
            raise BenchError("could not find a numeric column of frame times")
        column = best_index

    values = []
    for row in body:
        if column >= len(row):
            continue
        value = _parse_float(row[column])
        if value is None or value <= 0:
            continue
        values.append(value)

    if len(values) < 10:
        raise BenchError(
            "only found %d usable samples; capture at least a few seconds of "
            "gameplay" % len(values)
        )

    if kind == "fps":
        values = [1000.0 / v for v in values]
    return values


def _worst_average(sorted_times, fraction):
    """Average of the slowest `fraction` of frames, expressed in FPS."""
    n = len(sorted_times)
    count = max(1, int(round(n * fraction)))
    slowest = sorted_times[-count:]
    return 1000.0 / (sum(slowest) / count)


def _percentile(sorted_values, fraction):
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    index = min(n - 1, max(0, int(round((n - 1) * fraction))))
    return sorted_values[index]


def suggest_cap(fps_floor):
    """Largest standard step at or below `fps_floor`."""
    cap = STEPS[0]
    for step in STEPS:
        if step <= fps_floor:
            cap = step
        else:
            break
    return cap


def analyze(times):
    """Compute the report dict for a list of frame times in milliseconds."""
    if not times:
        raise BenchError("no samples to analyse")
    ordered = sorted(times)
    n = len(ordered)
    mean_ms = sum(ordered) / n
    median_ms = _percentile(ordered, 0.5)
    p99_ms = _percentile(ordered, 0.99)
    p999_ms = _percentile(ordered, 0.999)

    one_pct_low = _worst_average(ordered, 0.01)
    point_one_pct_low = _worst_average(ordered, 0.001)
    mean_fps = 1000.0 / mean_ms if mean_ms else 0.0

    return {
        "samples": n,
        "mean_fps": mean_fps,
        "median_fps": 1000.0 / median_ms if median_ms else 0.0,
        "one_pct_low_fps": one_pct_low,
        "point_one_pct_low_fps": point_one_pct_low,
        "mean_ms": mean_ms,
        "median_ms": median_ms,
        "p99_ms": p99_ms,
        "p999_ms": p999_ms,
        # How much worse the tail is than the typical frame. >1.5 is noticeable.
        "stutter_ratio": (p99_ms / median_ms) if median_ms else 0.0,
        # Cap you can hold essentially always.
        "stable_cap": suggest_cap(one_pct_low),
        # Cap the frame *average* can hold: smoother than uncapped, still fast.
        "common_cap": suggest_cap(mean_fps),
    }


class Capture(object):
    """A parsed capture: frame intervals and, when available, GPU-busy times.

    ``frametimes`` and ``gpu_times`` are row-aligned by construction: entry i is
    the frame interval and the GPU time of the *same* frame. Column names are
    kept so the report can show what was actually measured instead of asking
    the user to trust a verdict.
    """

    __slots__ = ("frametimes", "gpu_times", "frame_column", "gpu_column")

    def __init__(self, frametimes, gpu_times, frame_column=None, gpu_column=None):
        self.frametimes = frametimes
        self.gpu_times = gpu_times
        self.frame_column = frame_column
        self.gpu_column = gpu_column

    @property
    def has_gpu(self):
        return bool(self.gpu_times)

    @property
    def gpu_fallback(self):
        """True when only total GPU time was available, not busy time."""
        name = (self.gpu_column or "").lower()
        return bool(name) and not any(hint in name for hint in _GPU_BUSY_HINTS)



def _busiest_column(body):
    width = max(len(row) for row in body)
    best_index, best_hits = None, 0
    for index in range(width):
        hits = sum(
            1 for row in body if index < len(row) and _parse_float(row[index]) is not None
        )
        if hits > best_hits:
            best_index, best_hits = index, hits
    if best_index is None or best_hits < max(2, len(body) // 2):
        return None
    return best_index


def _find_gpu_column(header):
    """`(index, name)` of the GPU busy column, falling back to total GPU time."""
    if not header:
        return None, None
    for hints in (_GPU_BUSY_HINTS, _GPU_TIME_HINTS):
        for index, name in enumerate(header):
            if any(hint in name for hint in hints):
                return index, name
    return None, None


def _column_values(body, index, kind):
    values = []
    for row in body:
        if index >= len(row):
            continue
        value = _parse_float(row[index])
        if value is None or value <= 0:
            continue
        values.append(1000.0 / value if kind == "fps" else value)
    return values


def parse_capture(text):
    """Parse a capture keeping both frame times and GPU-active times.

    The GPU column is what makes bottleneck classification possible: a frame
    that takes 6ms when the GPU was busy for 5.8ms is GPU-bound, and no amount
    of convar tweaking will help. A frame that takes 6ms with the GPU busy for
    3ms is waiting on something else, and cutting pixels is pointless.
    """
    if not text:
        raise BenchError("the capture file is empty")
    text = text.lstrip("\ufeff")
    if not text.strip():
        raise BenchError("the capture file is empty")

    delimiter = _sniff_delimiter(text)
    rows = [
        row
        for row in csv.reader(io.StringIO(text), delimiter=delimiter)
        if any(str(cell).strip() for cell in row)
    ]
    if not rows:
        raise BenchError("the capture file has no data rows")

    header = None
    body = rows
    first = rows[0]
    if _classify_header_row(first) is not None or all(
        _parse_float(cell) is None for cell in first
    ):
        header = [cell.strip().lower() for cell in first]
        body = rows[1:]
    if not body:
        raise BenchError("the capture file has a header but no frames")

    frame_kind, frame_column = "ms", None
    if header is not None:
        classified = _classify_header_row(first)
        if classified is not None:
            frame_kind, frame_column = classified
    if frame_column is None:
        frame_column = _busiest_column(body)
        if frame_column is None:
            raise BenchError("could not find a numeric column of frame times")

    frametimes = _column_values(body, frame_column, frame_kind)
    if len(frametimes) < 10:
        raise BenchError(
            "only found %d usable frames; capture at least a few seconds of "
            "gameplay" % len(frametimes)
        )

    frame_name = None
    if header is not None and frame_column < len(header):
        frame_name = header[frame_column]

    gpu_column, gpu_name = _find_gpu_column(header)
    if gpu_column == frame_column:
        # The only column that matched is the one we already read as frame
        # time; using it for both would fabricate a 100% busy GPU.
        gpu_column, gpu_name = None, None
    if gpu_column is None:
        return Capture(frametimes, [], frame_name, None)

    # Pair the two columns row by row. Extracting them independently would
    # compare frame N's interval against frame M's GPU time as soon as one row
    # is missing a value -- a silent way to produce a confident wrong verdict.
    paired_frames, paired_gpu = [], []
    for row in body:
        frame = _parse_float(row[frame_column]) if frame_column < len(row) else None
        gpu = _parse_float(row[gpu_column]) if gpu_column < len(row) else None
        # A zero GPU time is kept: it is a real reading on a frame the GPU
        # skipped, and an all-zero column is rejected later as unmeasurable
        # rather than silently reported as 0% busy.
        if frame is None or frame <= 0 or gpu is None or gpu < 0:
            continue
        paired_frames.append(1000.0 / frame if frame_kind == "fps" else frame)
        paired_gpu.append(gpu)

    if len(paired_frames) < 10:
        raise BenchError(
            "%s is in the header but only %d rows hold both a frame time and a "
            "GPU time. GPU tracking was probably enabled part-way through the "
            "capture; start it before launching the game."
            % (gpu_name, len(paired_frames))
        )
    return Capture(paired_frames, paired_gpu, frame_name, gpu_name)


def format_report(stats):
    """Human-readable report, deliberately blunt about what the numbers mean."""
    ratio = stats["stutter_ratio"]
    if ratio >= 2.0:
        verdict = "frametimes are very uneven - a cap will help a lot here"
    elif ratio >= 1.5:
        verdict = "noticeable stutter spikes - a cap will smooth this out"
    elif ratio >= 1.2:
        verdict = "mild jitter - a cap is optional"
    else:
        verdict = "already smooth - a cap is optional"

    return "\n".join(
        [
            "Frametime report",
            "  samples                 %d frames" % stats["samples"],
            "  average                 %6.1f fps  (%.2f ms)"
            % (stats["mean_fps"], stats["mean_ms"]),
            "  median                  %6.1f fps  (%.2f ms)"
            % (stats["median_fps"], stats["median_ms"]),
            "  1%% low                  %6.1f fps" % stats["one_pct_low_fps"],
            "  0.1%% low                %6.1f fps" % stats["point_one_pct_low_fps"],
            "  99th pct frametime      %6.2f ms" % stats["p99_ms"],
            "  99.9th pct frametime    %6.2f ms" % stats["p999_ms"],
            "  tail / median           %6.2fx    %s" % (ratio, verdict),
            "",
            "Recommended caps",
            "  stable  --fps-cap %-4d  holds the 1%% low; flattest frametimes"
            % stats["stable_cap"],
            "  fast    --fps-cap %-4d  holds the average; still steadier than uncapped"
            % stats["common_cap"],
            "  0 (uncapped) if you would rather have the peak number than the feel.",
        ]
    )
