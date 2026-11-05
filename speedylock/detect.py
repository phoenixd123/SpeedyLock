"""Locate the Deadlock install and guess a sensible starting profile.

Everything here is best-effort and must never raise on a machine it does not
understand. A user with an unusual Steam layout should always be able to pass
--game-dir or --profile and get on with it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ENV_GAME_DIR = "SPEEDYLOCK_GAME_DIR"

# Subdirectory that must exist for a candidate path to count as Deadlock.
_MARKER = ("game", "citadel")


def _candidate_roots():
    """Well-known Steam library locations, most common first."""
    home = Path.home()
    roots = []
    if sys.platform.startswith("win"):
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            base = os.environ.get(env)
            if base:
                roots.append(Path(base) / "Steam" / "steamapps" / "common" / "Deadlock")
        for drive in ("C", "D", "E", "F", "G"):
            roots.append(Path("%s:/Steam/steamapps/common/Deadlock" % drive))
            roots.append(
                Path("%s:/SteamLibrary/steamapps/common/Deadlock" % drive)
            )
            roots.append(
                Path("%s:/Games/SteamLibrary/steamapps/common/Deadlock" % drive)
            )
    else:
        for base in (
            home / ".steam" / "steam",
            home / ".local" / "share" / "Steam",
            home / ".steam" / "root",
        ):
            roots.append(base / "steamapps" / "common" / "Deadlock")
    return roots


def looks_like_deadlock(path):
    # type: (Path) -> bool
    try:
        return path.is_dir() and (path.joinpath(*_MARKER)).is_dir()
    except OSError:
        return False


def find_install(explicit=None):
    # type: (object) -> Path
    """Return the Deadlock install directory.

    Order: explicit argument, then $SPEEDYLOCK_GAME_DIR, then known Steam
    library paths. Raises FileNotFoundError with an actionable message.
    """
    if explicit:
        path = Path(explicit).expanduser()
        if not looks_like_deadlock(path):
            raise FileNotFoundError(
                "%s does not look like a Deadlock install (no game/citadel "
                "inside it)." % path
            )
        return path

    env = os.environ.get(ENV_GAME_DIR)
    if env:
        path = Path(env).expanduser()
        if looks_like_deadlock(path):
            return path

    for path in _candidate_roots():
        if looks_like_deadlock(path):
            return path

    raise FileNotFoundError(
        "Could not find Deadlock. Pass --game-dir pointing at the folder that "
        "contains game/citadel (usually "
        "Steam/steamapps/common/Deadlock), or set %s." % ENV_GAME_DIR
    )


def cfg_dir(install):
    # type: (Path) -> Path
    return Path(install).joinpath("game", "citadel", "cfg")


def _run(cmd, timeout=4):
    """Run a probe command, returning stdout or None. Never raises."""
    try:
        out = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
        if out.returncode != 0:
            return None
        return out.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return None


def gpu_name():
    """Best-effort GPU description string, or None."""
    if sys.platform.startswith("win"):
        for cmd in (
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_VideoController | "
                "Select-Object -ExpandProperty Name",
            ],
            ["wmic", "path", "win32_VideoController", "get", "name"],
        ):
            out = _run(cmd)
            if out:
                lines = [l.strip() for l in out.splitlines() if l.strip()]
                lines = [l for l in lines if l.lower() not in ("name",)]
                if lines:
                    return lines[0]
        return None

    out = _run(["lspci"])
    if out:
        for line in out.splitlines():
            if any(k in line for k in ("VGA", "3D controller", "Display")):
                return line.split(":", 2)[-1].strip()
    return None


def cpu_name():
    # type: () -> object
    if sys.platform.startswith("win"):
        out = _run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_Processor).Name",
            ]
        )
        if out and out.strip():
            return out.strip().splitlines()[0]
        return None
    try:
        with open("/proc/cpuinfo", "r") as fh:
            for line in fh:
                if line.lower().startswith("model name"):
                    value = line.split(":", 1)[-1].strip()
                    # Containers and odd kernels sometimes put junk here; only
                    # accept something that actually looks like a CPU name.
                    if value and any(ch.isalpha() for ch in value):
                        return value
                    break
    except OSError:
        pass
    return None


# Substrings that mark hardware we should not push a "balanced" config at.
_LOW_END_HINTS = (
    "intel(r) uhd",
    "uhd graphics",
    "intel hd",
    "hd graphics",
    "iris xe",
    "vega 8",
    "radeon graphics",  # APU branding
    "microsoft basic",
    "llvmpipe",
    "gt 1030",
    "gt 710",
    "gt 730",
    "mx150",
    "mx250",
    "mx350",
    "mx450",
    "gtx 750",
    "gtx 760",
    "gtx 950",
    "gtx 960",
    "rx 550",
    "rx 560",
)


def guess_profile(gpu=None):
    """Pick a starting profile from the GPU string.

    Deliberately conservative: we only jump to ``potato`` on hardware that is
    actually thin, and default to ``balanced`` when we cannot tell. The wrong
    guess in the other direction would just make the game ugly for no reason.
    """
    if not gpu:
        return "balanced"
    lowered = gpu.lower()
    for hint in _LOW_END_HINTS:
        if hint in lowered:
            return "potato"
    return "balanced"
