"""Closed-loop tuning: turn a measurement into a decision, not a guess.

Neither community config does this. Both ship one fixed set of values and hope
it suits your machine. But the right knob depends entirely on *which resource
you are actually waiting on*:

* **GPU-bound** -- frames take as long as the GPU is busy. Cutting physics or
  ragdolls changes nothing. The only lever that matters is pixels: resolution
  scale, texture streaming, effects. SpeedyLock can size the render scale from
  arithmetic instead of vibes (see ``suggest_render_scale``).
* **CPU-bound** -- the GPU finishes early and waits. Cutting resolution here is
  wasted visual quality for zero frames. The lever is simulation cost: ragdolls,
  breakable debris, particle fallback, UI framerate.

PresentMon records ``msGPUActive`` per frame, so the split is measurable:
``sum(msGPUActive) / sum(msBetweenPresents)`` is the share of each frame the GPU
was working. Near 1.0 means GPU-bound; well below means it is waiting.

That ratio is the one piece of "own tech" here, and it is not a trick -- it is
just refusing to apply a fix before diagnosing the problem.
"""

from __future__ import annotations

import math

# Above this the GPU is saturated: the frame interval is the GPU's own time.
GPU_BOUND = 0.93
# Below this the GPU is idle long enough that something else is the limit.
CPU_BOUND = 0.75

VERDICT_LABEL = {
    "gpu": "GPU-bound",
    "cpu": "CPU-bound (or waiting on something that is not the GPU)",
    "mixed": "balanced -- neither side is clearly the limit",
    "unknown": "unknown",
}

# A downscale smaller than this is not worth losing sharpness over.
WORTH_IT = 0.95

RENDER_SCALE_KEY = "setting.mat_viewportscale"


def gpu_ratio(capture):
    """GPU busy time as a fraction of frame time, or None if unmeasurable.

    Returns None rather than a number whenever the measurement cannot be
    trusted:

    * **All-zero GPU column.** PresentMon writes the column with GPU tracking
      enabled even on a machine or driver where it cannot be measured. Treating
      that as 0% busy would produce a confident, completely wrong "CPU-bound"
      verdict and send someone hunting phantom CPU limits.
    * **Ratio above 1.5.** A busy fraction cannot exceed 1.0; a larger value
      means the columns are not what we think they are, so the honest answer is
      "unknown" rather than a guess.
    """
    if capture is None or not getattr(capture, "gpu_times", None):
        return None
    frames = capture.frametimes
    gpu = capture.gpu_times
    count = min(len(frames), len(gpu))
    if count < 10:
        return None
    total = sum(frames[:count])
    if total <= 0:
        return None
    busy = sum(gpu[:count])
    if busy <= 0:
        return None
    ratio = busy / total
    if ratio > 1.5:
        return None
    return ratio


def classify(ratio):
    """Map a GPU ratio onto a bottleneck verdict."""
    if ratio is None:
        return "unknown"
    if ratio >= GPU_BOUND:
        return "gpu"
    if ratio <= CPU_BOUND:
        return "cpu"
    return "mixed"


def suggest_render_scale(mean_fps, target_fps, floor=0.5, ceiling=1.0):
    """Render scale needed to reach `target_fps` when pixel-bound.

    Fill rate scales with *pixel count*, so the linear scale factor is the
    square root of the frame ratio: going from 60 to 120fps needs half the
    pixels, which is a scale of sqrt(0.5) = 0.71, not 0.5.

    Returns None when the target is already met, or when the required change is
    smaller than WORTH_IT -- recommending a 1% downscale is noise, because you
    lose sharpness for something you cannot feel. Capped at 0.5 because below
    that the game is genuinely unreadable and you should be buying a GPU.
    """
    if not mean_fps or mean_fps <= 0 or not target_fps or target_fps <= 0:
        return None
    if target_fps <= mean_fps:
        return None
    scale = math.sqrt(mean_fps / target_fps)
    if scale > WORTH_IT:
        return None
    return max(floor, min(ceiling, round(scale, 2)))


def cap_options(stats, refresh=None):
    """Cap candidates from a frametime analysis.

    `stable` holds the 1% low. With a VRR display there is no point capping
    above the refresh rate, and the long-standing guidance is a few frames
    under it so the VRR window is never escaped -- that is the `vrr` option.
    `tick` aligns to the 60Hz server tick so every tick gets equal frames.
    """
    stable = int(stats["stable_cap"])
    options = {
        "stable": stable,
        "fast": int(stats["common_cap"]),
        "tick": max(30, (stable // 60) * 60),
        "vrr": None,
        "refresh": None,
    }
    if refresh and refresh > 0:
        options["refresh"] = int(refresh)
        options["vrr"] = max(30, min(stable, int(refresh) - 3))
    return options


def recommendation(stats, capture, refresh=None):
    """Everything the CLI needs: verdict, ratio, caps, render scale."""
    ratio = gpu_ratio(capture)
    verdict = classify(ratio)
    caps = cap_options(stats, refresh)

    scale = None
    if verdict == "gpu":
        target = refresh if refresh else caps["stable"]
        scale = suggest_render_scale(stats["mean_fps"], target)

    cap = caps["vrr"] if caps["vrr"] is not None else caps["stable"]
    return {
        "ratio": ratio,
        "verdict": verdict,
        "caps": caps,
        "cap": cap,
        "render_scale": scale,
    }


def advice(result):
    """The concrete, ordered actions for a verdict."""
    verdict = result["verdict"]
    caps = result["caps"]
    cap = result["cap"]
    lines = []

    if verdict == "gpu":
        lines.append(
            "GPU-bound: you are waiting on pixels. Physics and ragdoll convars "
            "will not help."
        )
        scale = result["render_scale"]
        if scale:
            lines.append(
                "Lower render scale to %.2f -- that is ~%d%% fewer pixels, sized "
                "from your own framerate." % (scale, round((1 - scale * scale) * 100))
            )
        else:
            lines.append(
                "You are within ~5% of your target: not worth losing sharpness over."
            )
        lines.append(
            "Shadows and AA are already off in this profile; resolution is the "
            "only large lever left."
        )
    elif verdict == "cpu":
        lines.append(
            "GPU is not the limit: cutting resolution buys you nothing here. "
            "Do not turn pixels down any further."
        )
        lines.append(
            "Use --profile potato: it zeroes ragdolls and breakable debris, which "
            "are the simulation costs charged per tick."
        )
        lines.append(
            "Add --cpu-relief: it stops the client stepping dormant entities, "
            "batches particle work, and moves physics and snapshot reads onto "
            "worker threads. `speedy cpu` lists exactly what it writes."
        )
        lines.append("Add -high to launch options for CPU scheduling headroom.")
    elif verdict == "mixed":
        lines.append(
            "Neither side is saturated. Cap the framerate first -- steadier "
            "frametimes often feel like more frames than a higher average does."
        )
    else:
        lines.append(
            "No GPU busy column in this capture, so the bottleneck is unknown. "
            "PresentMon only records it with GPU tracking enabled: -track_gpu on "
            "1.x, --track_gpu 1 on 2.x. The column is msGPUActive (1.x), GPUBusy "
            "(2.3) or MsGPUBusy (2.4+); SpeedyLock reads all three."
        )

    lines.append("Cap to %d (holds your 1%% low)." % cap)
    if caps["vrr"] is not None and caps["vrr"] != cap:
        lines.append(
            "For a %dHz VRR display, %d is the sub-refresh option."
            % (caps["refresh"], caps["vrr"])
        )
    if caps["tick"] != cap and caps["tick"] >= 60:
        lines.append(
            "%d is the tick-aligned option (one framerate per 60Hz server tick)."
            % caps["tick"]
        )
    return lines


def install_command(result, profile="balanced", game_dir=None):
    """The exact command that applies a recommendation."""
    parts = [
        "python speedy.py install",
        "--profile %s" % profile,
        "--fps-cap %d" % result["cap"],
    ]
    if result["verdict"] == "gpu" and result["render_scale"]:
        parts.append("--render-scale %.2f" % result["render_scale"])
    if result["verdict"] == "cpu":
        parts.append("--cpu-relief")
    if game_dir:
        parts.append('--game-dir "%s"' % game_dir)
    return " ".join(parts)
