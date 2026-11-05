"""Knowledge base of Deadlock / Source 2 console variables.

SpeedyLock's whole design premise is that it refuses to emit anything it
cannot justify. Every convar the tool is willing to write must appear here
with a status that records how confident we are, and profiles are only
allowed to reference *writable* ones.

Statuses
--------
verified   : Confirmed to exist and work in Deadlock (community-documented).
documented : Ships in OptiLock's published configs. Real convar, value not
             independently verified here. Writable, because a competitive
             player has already been running it.
generic    : Standard Source 2 convar. Harmless; may be a no-op on some builds.
risky      : A real convar with a downside. Never written without --experimental.
cheat      : Cheat-flagged or information-gathering. Never written, ever.
unknown    : Believed to exist but unconfirmed. Never written.

The `cheat` and `unknown` buckets matter. Most "optimization configs" you
find online are 40 lines long and half of them do nothing, because the author
copy-pasted Source 1 commands into a Source 2 game. A few of them are worse
than useless -- `r_drawothermodels 2` is a wallhack and will get you banned.
SpeedyLock is deliberately short.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Optional


class Status(str, Enum):
    VERIFIED = "verified"
    DOCUMENTED = "documented"
    GENERIC = "generic"
    RISKY = "risky"
    CHEAT = "cheat"
    UNKNOWN = "unknown"


class Convar(object):
    """One row of the knowledge base."""

    __slots__ = ("name", "status", "default", "description")

    def __init__(self, name, status, default, description):
        # type: (str, Status, Optional[str], str) -> None
        self.name = name
        self.status = status
        self.default = default
        self.description = description

    def is_writable(self, experimental=False):
        # type: (bool) -> bool
        """Whether SpeedyLock may emit this convar."""
        if self.status in (Status.VERIFIED, Status.GENERIC, Status.DOCUMENTED):
            return True
        # RISKY convars exist and work, but carry a real downside. Opt-in only.
        if self.status is Status.RISKY and experimental:
            return True
        # CHEAT and UNKNOWN are never written, not even with --experimental.
        return False

    def __repr__(self):
        return "Convar(%r, %r)" % (self.name, self.status.value)


def _c(name, status, default, description):
    return Convar(name, status, default, description)


CONVARS = {}  # type: Dict[str, Convar]


def _add(*rows):
    for row in rows:
        CONVARS[row.name] = row


_add(
    # ------------------------------------------------------------------ verified
    _c(
        "fps_max",
        Status.VERIFIED,
        "400",
        "Gameplay framerate cap. 0 = uncapped. Cap just under your 1% low "
        "for steadier frametimes and lower input latency.",
    ),
    _c(
        "fps_max_ui",
        Status.VERIFIED,
        "120",
        "Menu/HUD framerate cap. The UI is drawn by Panorama and does not need "
        "to run at 300fps; lowering it gives the game back CPU time.",
    ),
    _c(
        "fps_max_tools",
        Status.VERIFIED,
        "120",
        "Framerate cap used while in tool/demo views.",
    ),
    _c(
        "cl_input_enable_raw_keyboard",
        Status.VERIFIED,
        "0",
        "Read the keyboard directly, bypassing the Windows input stack. Cuts a "
        "little input latency and removes OS key-filtering.",
    ),
    _c(
        "engine_low_latency_sleep_after_client_tick",
        Status.VERIFIED,
        "0",
        "Sleep *after* the client tick instead of spinning before it. Lowers "
        "end-to-end latency without the CPU spin of a bare busy-wait.",
    ),
    _c(
        "cl_interp_ratio",
        Status.VERIFIED,
        "2",
        "Interpolation buffer multiplier. 1 = one update of buffer, the legal "
        "minimum. Less buffer means less delay on other players' positions.",
    ),
    _c(
        "cl_updaterate",
        Status.VERIFIED,
        "60",
        "Requested server snapshot rate. 60 matches Deadlock's tickrate; asking "
        "for more just wastes bandwidth.",
    ),
    _c(
        "cl_ragdoll_limit",
        Status.VERIFIED,
        "8",
        "Maximum simultaneous ragdolls. 0 disables them: a large, pure-CPU win "
        "in teamfights and the closest thing to a free framerate.",
    ),
    _c(
        "func_break_max_pieces",
        Status.VERIFIED,
        "16",
        "Maximum debris pieces spawned by breakable props. 0 removes the physics "
        "cost of destructible clutter.",
    ),
    _c(
        "citadel_healthbars_enabled",
        Status.VERIFIED,
        "1",
        "Draw health bars above units. Cosmetic; Panorama overhead only.",
    ),
    _c(
        "citadel_hud_visible",
        Status.VERIFIED,
        "1",
        "Toggle the in-game HUD. Not for real play, but useful for measuring "
        "how much of your framerate the HUD is costing you.",
    ),
    _c(
        "citadel_damage_text_lifetime",
        Status.VERIFIED,
        "1.5",
        "Seconds a floating damage number stays on screen. Lower = fewer "
        "simultaneously-animated Panorama labels.",
    ),
    # ------------------------------------------------------------------- generic
    _c(
        "engine_no_focus_sleep",
        Status.GENERIC,
        "20",
        "Milliseconds to sleep per frame while the game is unfocused. Higher "
        "values let the GPU idle when you alt-tab instead of rendering an "
        "invisible window at full speed.",
    ),
    _c(
        "snd_mixahead",
        Status.GENERIC,
        "0.05",
        "Audio mixing buffer in seconds. Lower = less audio latency, at the cost "
        "of possible crackle on heavily loaded systems. 0.025 is a safe step.",
    ),
    # --------------------------------------------------------------------- risky
    _c(
        "cl_resend",
        Status.RISKY,
        "0.5",
        "Seconds between retransmits of unreliable packets. Some guides set 0 "
        "to 'reduce ping'; that also removes your safety net on a lossy line "
        "and can cause rubber-banding. Opt-in via --experimental only.",
    ),
    _c(
        "cl_interp",
        Status.RISKY,
        None,
        "Absolute interpolation time. On Source 2 this is normally derived from "
        "cl_interp_ratio and the server tickrate, so forcing it is a good way "
        "to desync your own hit registration. Opt-in via --experimental only.",
    ),
    # --------------------------------------------------------------------- cheat
    _c(
        "cl_disable_ragdolls",
        Status.CHEAT,
        "false",
        "Cheat-flagged, so it does nothing in a normal live match. People put "
        "this in their configs and believe it works. It does not.",
    ),
    _c(
        "r_drawothermodels",
        Status.CHEAT,
        "0",
        "2 makes enemy models render through walls. This is a wallhack.",
    ),
    _c(
        "mat_wireframe",
        Status.CHEAT,
        "0",
        "Renders geometry as wireframe. Sometimes sold as a 'performance tweak'; "
        "it is a cheat-flagged developer view and it is not faster.",
    ),
    _c(
        "sv_cheats",
        Status.CHEAT,
        "0",
        "Server-side cheat gate. Client configs cannot enable it and trying is "
        "a fast way to look suspicious.",
    ),
    # ------------------------------------------------------------------- unknown
    _c(
        "mat_queue_mode",
        Status.UNKNOWN,
        None,
        "Source 1 material threading. Removed in Source 2; still copy-pasted "
        "into Deadlock configs constantly. Included here so SpeedyLock can "
        "refuse to write it.",
    ),
    _c(
        "r_shadows",
        Status.UNKNOWN,
        None,
        "Source 1 shadow toggle. Deadlock exposes shadows through the video "
        "settings menu, not this convar.",
    ),
    _c(
        "cl_forcepreload",
        Status.UNKNOWN,
        None,
        "Source 1 asset preloading. Removed in Source 2.",
    ),
)


_DOCUMENTED_BLURB = (
    "Ships in OptiLock's published configs (GPL-3.0). A real convar that "
    "competitive players run, but SpeedyLock has not independently verified "
    "its effect; the default shown is OptiLock's value, not Valve's."
)


def register_documented(mapping):
    # type: (dict) -> int
    """Add convars supplied by a published config, without overriding ours.

    Curated entries always win, so a convar we already classified as ``risky``
    or ``cheat`` stays that way no matter who ships it. Returns how many were
    added.
    """
    added = 0
    for name in sorted(mapping):
        if name in CONVARS:
            continue
        CONVARS[name] = _c(name, Status.DOCUMENTED, mapping[name], _DOCUMENTED_BLURB)
        added += 1
    return added


def get(name):
    # type: (str) -> Optional[Convar]
    return CONVARS.get(name)


def is_writable(name, experimental=False):
    # type: (str, bool) -> bool
    """True only if the convar is in the KB and safe to emit."""
    cvar = CONVARS.get(name)
    return bool(cvar and cvar.is_writable(experimental))


def by_status(status):
    # type: (Status) -> list
    return sorted((c for c in CONVARS.values() if c.status is status), key=lambda c: c.name)


def load_cvarlist(path):
    # type: (object) -> dict
    """Parse a convar dump into {name: flags}.

    Accepts the two shapes in circulation: the pipe table used by OptiLock's
    cvarlist.md (``name | default | flags | description``) and a plain console
    ``cvarlist`` dump (``name = "value" (flags)``). Pointing SpeedyLock at a
    dump from *your* game build is the only way to validate convars against the
    live executable, so the list is never vendored with the tool.
    """
    import re

    entries = {}  # type: dict
    pipe_row = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\|")
    console_row = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"')
    with open(str(path), "r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.rstrip("\r\n")
            pipe = pipe_row.match(line)
            if pipe:
                parts = [cell.strip() for cell in line.split("|")]
                entries[pipe.group(1)] = parts[2] if len(parts) > 2 else ""
                continue
            console = console_row.match(line)
            if console:
                entries[console.group(1)] = ""
    return entries
