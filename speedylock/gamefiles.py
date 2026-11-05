"""Manage Deadlock's ``video.txt`` and the ``ConVars`` block in ``gameinfo.gi``.

This is the layer that actually matters. ``autoexec.cfg`` is convenient but a
lot of Deadlock's visual cost is not a convar you can poke at runtime -- it is
a ``setting.*`` key in ``video.txt``, which the game reads at startup and
writes back from the video settings menu.

How the big community configs handle these files, and why this module exists:

* OptiLock ships a **complete replacement** ``gameinfo.gi`` (~46KB) that you
  drop over Valve's. That works, but it throws away your own FOV and
  ``PGIVersion``, and every game patch can invalidate it.
* For ``video.txt`` the instruction is "delete everything under deviceid and
  paste ours", which also throws away your resolution, monitor and gamma.

SpeedyLock does the opposite: it *merges*. Only keys it owns are touched, in
place, with the rest of the file preserved. Every write is backed up first and
``uninstall`` restores the backup.

Nothing here can see the real file layout of the current game build, so the
parsers are deliberately conservative: if a structure is not understood, we
raise ``GameFileError`` instead of writing something that might crash the game.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

STEAM_APP_ID = "1422450"

MARK_BEGIN = "// >>> SpeedyLock managed ConVars"
MARK_END = "// <<< SpeedyLock end <<<"

_SETTING_LINE = re.compile(r'^(\s*)"([^"]+)"(\s*)"([^"]*)"')

# Raising texture streaming past this point is documented (by OptiLock) as
# needing a separate VPK fix for Sinner's light rendering.
MIP_BIAS_FIX_THRESHOLD = 4

# Keys that are the user's hardware and display preference, not an
# optimisation. SpeedyLock never writes these, whatever a preset says.
PROTECTED_VIDEO_KEYS = frozenset(
    [
        "setting.defaultres",
        "setting.defaultresheight",
        "setting.recommendedheight",
        "setting.refreshrate_numerator",
        "setting.refreshrate_denominator",
        "setting.fullscreen",
        "setting.nowindowborder",
        "setting.fullscreen_min_on_focus_loss",
        "setting.monitor_index",
        "setting.knowndevice",
        "setting.high_dpi",
        "setting.aspectratiomode",
        "setting.r_fullscreen_gamma",
        "setting.mat_viewportscale",
        "setting.coop_fullscreen",
        "setting.useadvanced",
        "setting.light_sensitivity_mode",
        "setting.r_light_sensitivity_mode",
        "deviceid",
        "video_config",
    ]
)


class GameFileError(Exception):
    """Raised when a target file is not in a shape we are willing to edit."""


# --------------------------------------------------------------------- locating


def find_video_files(install):
    # type: (Path) -> List[Path]
    """Every ``video.txt`` the game might read for this install.

    Deadlock has used both ``game/citadel/cfg/video.txt`` and the Steam
    userdata path across builds, so a user can legitimately have either (or
    both, with one being stale). Existing files win; callers decide what to do
    when the list is empty.
    """
    install = Path(install)
    candidates = [install / "game" / "citadel" / "cfg" / "video.txt"]

    try:
        steam_root = install.parents[2]  # common -> steamapps -> steam
        userdata = steam_root / "userdata"
        if userdata.is_dir():
            for account in sorted(userdata.iterdir()):
                if not account.is_dir():
                    continue
                candidates.append(
                    account / STEAM_APP_ID / "local" / "cfg" / "video.txt"
                )
    except (IndexError, OSError):
        pass

    return [path for path in candidates if path.exists()]


def default_video_path(install):
    # type: (Path) -> Path
    return Path(install) / "game" / "citadel" / "cfg" / "video.txt"


def find_gameinfo(install):
    # type: (Path) -> Path
    return Path(install) / "game" / "citadel" / "gameinfo.gi"


# ------------------------------------------------------------------- key-values


def _structural(line):
    """Strip a trailing // comment and any quoted strings from a line.

    Used only for brace counting, so that a brace inside a quoted path or in a
    comment cannot throw off the balance check.
    """
    out = []
    in_string = False
    index = 0
    while index < len(line):
        char = line[index]
        if char == '"':
            in_string = not in_string
        elif not in_string:
            if char == "/" and index + 1 < len(line) and line[index + 1] == "/":
                break
            out.append(char)
        index += 1
    return "".join(out)


def brace_delta(text):
    """Net ``{`` minus ``}`` across the file, ignoring comments and strings."""
    total = 0
    for line in text.splitlines():
        stripped = _structural(line)
        total += stripped.count("{") - stripped.count("}")
    return total


def _sanitise(value):
    text = str(value)
    if '"' in text or "\n" in text or "\r" in text:
        raise GameFileError("refusing to write a value containing quotes or newlines: %r" % text)
    return text


# ---------------------------------------------------------------------- video


def merge_video(text, settings, allow_protected=()):
    # type: (str, Dict[str, str], object) -> str
    """Return `text` with `settings` applied, preserving everything else.

    Keys already present are updated in place (so the file keeps its order and
    any hand-written comments); missing keys are inserted before the final
    closing brace.

    Keys in ``PROTECTED_VIDEO_KEYS`` are refused unless the caller explicitly
    opts in via `allow_protected`. Render scale is the one protected key a user
    can deliberately unlock with ``--render-scale``; a preset must never quietly
    resize someone's game.
    """
    pending = {}
    for key, value in settings.items():
        if key in PROTECTED_VIDEO_KEYS and key not in allow_protected:
            raise GameFileError(
                "%s is a display/hardware setting, not an optimisation; "
                "SpeedyLock will not overwrite it" % key
            )
        pending[key] = _sanitise(value)

    if not text.strip():
        lines = ['"video_config"\n', "{\n", "}\n"]
    else:
        lines = text.splitlines(True)

    out = []
    for raw in lines:
        match = _SETTING_LINE.match(raw)
        if match is not None and match.group(2) in pending:
            key = match.group(2)
            value = pending.pop(key)
            out.append(
                '%s"%s"%s"%s"%s'
                % (match.group(1), key, match.group(3), value, raw[match.end() :])
            )
        else:
            out.append(raw)

    if pending:
        insert_at = None
        for index in range(len(out) - 1, -1, -1):
            if out[index].strip() == "}":
                insert_at = index
                break
        new_lines = ['\t"%s"\t\t"%s"\n' % (key, pending[key]) for key in sorted(pending)]
        if insert_at is None:
            if out and not out[-1].endswith("\n"):
                out[-1] = out[-1] + "\n"
            out.extend(new_lines)
        else:
            out[insert_at:insert_at] = new_lines

    merged = "".join(out)
    if brace_delta(merged) != brace_delta(text):
        raise GameFileError("editing video.txt would unbalance its braces; aborted")
    return merged


def video_key_lines(text):
    # type: (str) -> List[Tuple[str, str]]
    """Every ``(key, value)`` pair in a video.txt."""
    pairs = []
    for raw in text.splitlines():
        match = _SETTING_LINE.match(raw)
        if match is not None:
            pairs.append((match.group(2), match.group(4)))
    return pairs


# ------------------------------------------------------------------- gameinfo


def find_convars_block(text):
    # type: (str) -> Optional[Tuple[int, int, int]]
    """Locate the ``ConVars`` block: (header line, open brace line, close line).

    Returns None when the file has no ConVars block. Raises GameFileError if a
    block is found but its braces never balance.
    """
    lines = text.splitlines(True)
    for index, raw in enumerate(lines):
        if not re.match(r"^\s*ConVars\s*$", raw.rstrip("\r\n")):
            continue
        cursor = index + 1
        while cursor < len(lines) and not _structural(lines[cursor]).strip():
            cursor += 1
        if cursor >= len(lines):
            continue
        if not _structural(lines[cursor]).strip().startswith("{"):
            continue
        depth = 0
        for scan in range(cursor, len(lines)):
            segment = _structural(lines[scan])
            depth += segment.count("{") - segment.count("}")
            if depth == 0:
                return index, cursor, scan
        raise GameFileError("the ConVars block in gameinfo.gi has unbalanced braces")
    return None


def _strip_managed_lines(lines):
    # type: (List[str]) -> List[str]
    out = []
    inside = False
    for raw in lines:
        if raw.strip().startswith(MARK_BEGIN):
            inside = True
            continue
        if inside:
            if raw.strip() == MARK_END:
                inside = False
            continue
        out.append(raw)
    return out


def strip_gameinfo(text):
    # type: (str) -> str
    """Remove SpeedyLock's managed ConVars from gameinfo.gi content."""
    return "".join(_strip_managed_lines(text.splitlines(True)))


def has_managed_convars(text):
    # type: (str) -> bool
    return any(line.strip().startswith(MARK_BEGIN) for line in text.splitlines())


def inject_gameinfo(text, convars, profile_key):
    # type: (str, object, str) -> str
    """Add `convars` to the existing ConVars block, non-destructively."""
    lines = _strip_managed_lines(text.splitlines(True))
    stripped_text = "".join(lines)

    span = find_convars_block(stripped_text)
    if span is None:
        raise GameFileError(
            "gameinfo.gi has no ConVars block that SpeedyLock can recognise, so "
            "there is nothing safe to merge into. Refusing to rewrite the file."
        )

    _, open_line, close_line = span
    indent = re.match(r"^\s*", lines[open_line]).group(0) + "\t"

    quoted = _names_are_quoted(lines, open_line, close_line)
    block = ["%s%s (profile: %s)\n" % (indent, MARK_BEGIN, profile_key)]
    for name, value in convars:
        if quoted:
            block.append('%s"%s"\t\t"%s"\n' % (indent, name, _sanitise(value)))
        else:
            block.append('%s%s\t\t"%s"\n' % (indent, name, _sanitise(value)))
    block.append("%s%s\n" % (indent, MARK_END))

    lines[close_line:close_line] = block
    updated = "".join(lines)

    before = brace_delta(stripped_text)
    after = brace_delta(updated)
    if before != after:
        raise GameFileError("editing gameinfo.gi would unbalance its braces; aborted")
    return updated


# ConVars entries appear in both styles in the wild: Valve's stock gameinfo.gi
# quotes the name ("sv_cheats" "0"), while community configs such as OptiLock's
# write it bare (sv_cheats	"0"). Both are accepted; the writer mirrors whichever
# style the file already uses.
_CONVAR_ROW = re.compile(
    r'^\s*(?:"([A-Za-z_][A-Za-z0-9_]*)"|([A-Za-z_][A-Za-z0-9_]*))\s+"([^"]*)"'
)


def _names_are_quoted(lines, open_line, close_line):
    # type: (List[str], int, int) -> bool
    """Whether this block quotes convar names, judged by its first real entry."""
    for raw in lines[open_line + 1 : close_line]:
        stripped = raw.strip()
        if not stripped or stripped.startswith("//"):
            continue
        match = _CONVAR_ROW.match(raw)
        if match is not None:
            return match.group(1) is not None
    return False


def _convars_of(text):
    # type: (str) -> List[Tuple[str, str]]
    span = find_convars_block(text)
    if span is None:
        return []
    _header, open_line, close_line = span
    lines = text.splitlines()
    pairs = []
    for raw in lines[open_line + 1 : close_line]:
        if raw.strip().startswith("//"):
            continue
        match = _CONVAR_ROW.match(raw)
        if match is not None:
            pairs.append((match.group(1) or match.group(2), match.group(3)))
    return pairs


def convars_in_block(text):
    # type: (str) -> List[Tuple[str, str]]
    """Convars the file defines itself, with SpeedyLock's own block excluded.

    This is the "what was already here" view: another config's rows count, ours
    do not, because we are about to re-inject them. Use
    :func:`all_convars_in_block` when you want the total.
    """
    return _convars_of(strip_gameinfo(text))


def all_convars_in_block(text):
    # type: (str) -> List[Tuple[str, str]]
    """Every convar in the block, SpeedyLock's managed rows included."""
    return _convars_of(text)
