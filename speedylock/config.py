"""Reading, writing and removing the SpeedyLock config block.

Design rules, in priority order:

1. Never lose the user's own config. Anything outside the managed block is
   preserved byte for byte.
2. Never leave the game with a half-written autoexec.cfg. Writes go to a
   temporary file in the same directory and are moved into place atomically.
3. Be idempotent. Installing five times leaves exactly one block, so users can
   flip profiles freely without the file growing.
4. Be reversible. Every write is preceded by a timestamped backup, and
   ``uninstall`` restores the file to what it was before SpeedyLock touched it.
"""

from __future__ import annotations

import datetime
import os
import re
import tempfile
from pathlib import Path

from . import convars

BEGIN_PREFIX = "// >>> SpeedyLock managed block"
END_LINE = "// <<< SpeedyLock end <<<"

_BEGIN_RE = re.compile(r"^// >>> SpeedyLock managed block\b")
_PROFILE_RE = re.compile(r"profile:\s*([A-Za-z0-9_-]+)")
_CONVAR_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+\"?([^\"\s]*)\"?\s*$")


class ConfigError(Exception):
    """Raised when the target file is in a state we refuse to touch."""


class Result(object):
    __slots__ = ("path", "changed", "backup", "previous_profile", "dry_run")

    def __init__(self, path, changed, backup=None, previous_profile=None, dry_run=False):
        self.path = path
        self.changed = changed
        self.backup = backup
        self.previous_profile = previous_profile
        self.dry_run = dry_run

    def __repr__(self):
        return "Result(path=%r, changed=%r, backup=%r)" % (
            self.path,
            self.changed,
            self.backup,
        )


def begin_line(profile_key):
    return "%s | profile: %s | regenerated on every install" % (BEGIN_PREFIX, profile_key)


# --------------------------------------------------------------------- rendering


def render_block(profile, fps_cap=0, experimental=False):
    """Build the managed block for `profile`.

    Every convar is checked against the knowledge base first. If a profile ever
    references something cheat-flagged, removed from the engine, or simply
    unknown, we refuse to write the whole block rather than shipping a command
    that silently does nothing (or does something bannable).
    """
    problems = []
    body = []
    for name, value in profile.settings:
        cvar = convars.get(name)
        if cvar is None:
            problems.append("%s -- not in the convar knowledge base" % name)
            continue
        if not cvar.is_writable(experimental):
            problems.append("%s -- status is '%s'" % (name, cvar.status.value))
            continue
        resolved = str(value).replace("{fps_cap}", str(int(fps_cap)))
        body.append('%s "%s"' % (name, resolved))

    if problems:
        raise ConfigError(
            "refusing to write a config containing unsupported convars:\n  "
            + "\n  ".join(problems)
        )

    lines = [begin_line(profile.key)]
    lines.append("// SpeedyLock | profile: %s | %s" % (profile.title, profile.blurb))
    lines.append("// Do not edit inside this block; run `speedy install` instead.")
    lines.extend(body)
    lines.append(END_LINE)
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ block surgery


def split_block(text):
    """Split file content into (before, block, after).

    `block` is None when no managed block is present. Raises ConfigError when
    the block is unterminated or duplicated, because guessing in either case
    risks destroying user content.
    """
    lines = text.splitlines(True)
    starts = [i for i, line in enumerate(lines) if _BEGIN_RE.match(line.rstrip("\r\n"))]

    if not starts:
        return text, None, ""
    if len(starts) > 1:
        raise ConfigError(
            "autoexec.cfg contains %d SpeedyLock blocks. Delete the extra blocks "
            "(or run uninstall, then install again) and retry." % len(starts)
        )

    start = starts[0]
    end = None
    for index in range(start + 1, len(lines)):
        if lines[index].strip() == END_LINE:
            end = index
            break
    if end is None:
        raise ConfigError(
            "autoexec.cfg has a SpeedyLock block with no end marker. Remove the "
            "lines after '%s' and retry." % BEGIN_PREFIX
        )
    return "".join(lines[:start]), "".join(lines[start : end + 1]), "".join(lines[end + 1 :])


def strip_block(text):
    """Return (content without the managed block, block or None)."""
    before, block, after = split_block(text)
    if block is None:
        return text, None
    head = before.rstrip("\n")
    tail = after.lstrip("\n")
    if head and tail:
        joined = head + "\n\n" + tail
    elif head:
        joined = head + "\n"
    else:
        joined = tail
    return joined, block


def block_profile(block):
    """Extract the profile key recorded inside a block, or None."""
    if not block:
        return None
    match = _PROFILE_RE.search(block)
    return match.group(1) if match else None


def convar_lines(text):
    """Yield (name, value) for every `name "value"` line in the file."""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        match = _CONVAR_LINE_RE.match(line)
        if match:
            yield match.group(1), match.group(2)


# ------------------------------------------------------------------------- IO


def read_text(path):
    path = Path(path)
    if not path.exists():
        return ""
    with open(str(path), "r", encoding="utf-8", errors="replace", newline="") as fh:
        return fh.read()


def atomic_write(path, text):
    """Write `text` to `path` via a same-directory temp file and os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=".speedylock-", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_name, str(path))
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def backup_file(cfg_dir, text, label="autoexec", stamp=None, suffix=".cfg"):
    """Copy a file's current content into cfg_dir/speedy_backups.

    `label` names the original file (autoexec, video, gameinfo) so several
    files can share one backup directory.
    """
    cfg_dir = Path(cfg_dir)
    stamp = stamp or datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = cfg_dir / "speedy_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / ("%s-%s%s" % (label, stamp, suffix))
    counter = 1
    while target.exists():
        target = backup_dir / ("%s-%s-%d%s" % (label, stamp, counter, suffix))
        counter += 1
    atomic_write(target, text)
    return target


# Backups are named <label>-<YYYYmmdd-HHMMSS>[-<n>].<suffix>. Only a hyphen-digits
# group *after a full stamp* is a collision counter; without the stamp anchor
# the timestamp's own digits parse as the counter and ordering silently inverts.
_COUNTER_RE = re.compile(r"-\d{8}-\d{6}-(\d+)\.[^.]+$")


def _backup_sort_key(path):
    """Order backups by write time, then by collision counter."""
    match = _COUNTER_RE.search(path.name)
    counter = int(match.group(1)) if match else 0
    return (path.stat().st_mtime_ns, counter)


def restore_original(cfg_dir, label, suffix=".cfg"):
    """**Oldest** backup for `label`, as (path, text), or None.

    The first backup ever taken is the state before SpeedyLock touched the
    file, which is what `uninstall` has to put back. Picking the newest backup
    would restore an intermediate config that SpeedyLock itself wrote -- the
    first version of this function did exactly that and quietly broke restore.
    """
    backup_dir = Path(cfg_dir) / "speedy_backups"
    if not backup_dir.is_dir():
        return None
    matches = list(backup_dir.glob("%s-*%s" % (label, suffix)))
    if not matches:
        return None
    oldest = min(matches, key=_backup_sort_key)
    return oldest, read_text(oldest)


# ---------------------------------------------------------------- public actions


def install(cfg_dir, profile, fps_cap=0, experimental=False, dry_run=False, stamp=None):
    """Write the managed block for `profile` into `<cfg_dir>/autoexec.cfg`."""
    cfg_dir = Path(cfg_dir)
    autoexec = cfg_dir / "autoexec.cfg"
    original = read_text(autoexec)
    rest, existing_block = strip_block(original)
    previous = block_profile(existing_block)

    block = render_block(profile, fps_cap=fps_cap, experimental=experimental)
    head = rest.rstrip("\n")
    text = (head + "\n\n" if head else "") + block

    changed = text != original
    if dry_run or not changed:
        return Result(autoexec, False, None, previous, dry_run=dry_run)

    backup = backup_file(cfg_dir, original, stamp=stamp) if original.strip() else None
    atomic_write(autoexec, text)
    return Result(autoexec, True, backup, previous)


def uninstall(cfg_dir, dry_run=False, stamp=None):
    """Remove the managed block, restoring the user's own content."""
    cfg_dir = Path(cfg_dir)
    autoexec = cfg_dir / "autoexec.cfg"
    original = read_text(autoexec)
    if not original:
        return Result(autoexec, False, None, None, dry_run=dry_run)

    rest, existing_block = strip_block(original)
    if existing_block is None:
        return Result(autoexec, False, None, None, dry_run=dry_run)

    previous = block_profile(existing_block)
    if dry_run:
        return Result(autoexec, False, None, previous, dry_run=True)

    backup = backup_file(cfg_dir, original, stamp=stamp)
    if rest.strip():
        atomic_write(autoexec, rest if rest.endswith("\n") else rest + "\n")
    else:
        try:
            autoexec.unlink()
        except OSError:
            atomic_write(autoexec, "")
    return Result(autoexec, True, backup, previous)


def installed_profile(cfg_dir):
    """Profile key currently installed, or None."""
    text = read_text(Path(cfg_dir) / "autoexec.cfg")
    _, block = strip_block(text)
    return block_profile(block)
