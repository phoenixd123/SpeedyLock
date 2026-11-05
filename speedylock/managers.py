"""Coexistence with Grimoire and Deadlock Mod Manager (DMM).

SpeedyLock is a *config* tool: it edits ``autoexec.cfg``, ``video.txt`` and the
``ConVars`` block of ``gameinfo.gi``. Grimoire and DMM are *asset* managers:
they own ``game/citadel/addons/*.vpk``, rename VPKs into ``pakNN`` slots and
track a load order per profile.

Those are disjoint sets of files, which is why the right integration is
coexistence rather than pretending SpeedyLock is a VPK mod. The facts that
drove that decision, all from the projects' own documentation:

* DMM installs into a shared ``citadel/addons`` folder and *adopts* VPKs that
  are already there, so it will not fight a file it did not put there.
* Both projects read and write ``mod-interchange.json`` with
  ``"format": "deadlock-mod-interchange"``, version 1 (DMM documents the full
  schema; Grimoire reads and writes the same format).
* That interchange format is VPK-only -- "skips mods with no VPK on disk" -- and
  both managers treat ``autoexec`` as a per-profile *setting*, not as a mod
  asset. Grimoire ships an explicit "Autoexec manager"; DMM stores the commands
  in ``profiles[].autoexec`` and deliberately does not export them.

So SpeedyLock cannot be a ``mods[]`` entry. What it *can* legitimately do is
fill ``profiles[].autoexec``, which is the documented home for "console
commands that run at game launch", and hand over a ready ``autoexec.cfg`` that
Grimoire's autoexec manager can hold.

One thing this module deliberately does not do: claim that a VPK containing
``cfg/autoexec.cfg`` works. Whether the engine resolves ``cfg/`` through the
addon search path is not documented anywhere we could find, so no packaging
path here depends on it.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ADDONS_SUBDIR = ("game", "citadel", "addons")

INTERCHANGE_FORMAT = "deadlock-mod-interchange"
INTERCHANGE_VERSION = 1

GRIMOIRE = "grimoire"
DMM = "deadlock-mod-manager"
UNKNOWN = "unknown"

# Directory-name fragments, matched case-insensitively against the per-user
# config root. Heuristic by nature: these are Electron/Tauri data directories,
# not documented paths, so a hit is reported as "looks like", never as fact.
_MANAGER_HINTS = (
    (GRIMOIRE, ("grimoire",)),
    (DMM, ("deadlock mod manager", "deadlock-mod-manager", "deadlockmods", "deadlock_mod_manager")),
)

# Grimoire and DMM both name enabled VPKs pakNN_dir.vpk, but mods arrive under
# arbitrary names, so we match on substrings rather than a fixed filename.
_SINNER_FIX_HINTS = ("essentialfix", "essential_fix", "sinners light", "sinnerslight")
_POTATO_HINTS = ("potato",)

_MAX_ADDON_SCAN = 400


class ManagerFinding(object):
    """One manager we believe is present, plus the evidence for it."""

    __slots__ = ("key", "label", "evidence")

    def __init__(self, key, label, evidence):
        self.key = key
        self.label = label
        self.evidence = tuple(evidence)

    def __repr__(self):
        return "ManagerFinding(%r)" % self.key


_LABELS = {GRIMOIRE: "Grimoire", DMM: "Deadlock Mod Manager", UNKNOWN: "an unidentified manager"}


def addons_dir(install):
    # type: (Path) -> Path
    return Path(install).joinpath(*ADDONS_SUBDIR)


def scan_addons(install):
    # type: (Path) -> list
    """Every ``.vpk`` in the addons folder, as ``(name, size)`` pairs.

    Names only: SpeedyLock never reads or validates VPK contents, so a manager
    that repacks or renumbers files cannot confuse it.
    """
    folder = addons_dir(install)
    if not folder.is_dir():
        return []
    found = []
    try:
        entries = sorted(folder.iterdir())
    except OSError:
        return []
    for entry in entries[:_MAX_ADDON_SCAN]:
        try:
            if entry.is_file() and entry.suffix.lower() == ".vpk":
                found.append((entry.name, entry.stat().st_size))
        except OSError:
            continue
    return found


def _config_root():
    """Per-user application data directory, or None."""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA")
        return Path(base) if base else None
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base)
    home = os.environ.get("HOME")
    return Path(home) / ".config" if home else None


def detect_managers(install, config_root=None):
    # type: (Path, object) -> list
    """Managers that look present, each with the evidence behind the guess.

    Two independent signals: a matching per-user config directory, and VPKs
    sitting in ``citadel/addons``. Either alone is weak, so the caller gets the
    evidence list rather than a boolean.
    """
    root = Path(config_root) if config_root is not None else _config_root()
    findings = []

    if root is not None and root.is_dir():
        try:
            names = [p.name for p in root.iterdir() if p.is_dir()]
        except OSError:
            names = []
        for key, hints in _MANAGER_HINTS:
            for name in names:
                lowered = name.lower()
                if any(hint in lowered for hint in hints):
                    findings.append(
                        ManagerFinding(key, _LABELS[key], ["config directory: %s" % name])
                    )
                    break

    addons = scan_addons(install)
    if addons:
        evidence = ["%d VPK%s in game/citadel/addons"
                    % (len(addons), "" if len(addons) == 1 else "s")]
        known = {finding.key for finding in findings}
        if not known:
            findings.append(ManagerFinding(UNKNOWN, _LABELS[UNKNOWN], evidence))
        else:
            for finding in findings:
                findings[-1] = ManagerFinding(finding.key, finding.label, list(finding.evidence) + evidence)
    return findings


def has_sinner_fix(addons):
    # type: (list) -> bool
    """Whether a Sinner's Light fix VPK is installed.

    ``r_texture_stream_mip_bias`` above 4 renders Sinner's light incorrectly
    without it, so this gates the high bias presets.
    """
    for name, _size in addons:
        lowered = name.lower()
        if any(hint in lowered for hint in _SINNER_FIX_HINTS):
            return True
    return False


def has_potato_lock(addons):
    # type: (list) -> bool
    """Whether something Potato-Lock-shaped is installed.

    Potato Lock swaps 4K PBR textures for 1x1 colour textures to cut VRAM use.
    It is CC BY-NC-ND 4.0, so SpeedyLock only ever points at it, never carries
    or derives from its assets.
    """
    return any(any(h in name.lower() for h in _POTATO_HINTS) for name, _ in addons)


def convar_duplicates(managed, existing):
    # type: (list, list) -> list
    """Convars SpeedyLock writes that the file already defines elsewhere.

    Ours are injected just before the closing brace of the ``ConVars`` block, so
    they are defined last and win. That is the intended behaviour when layering
    on top of another config, but the user should be told it happened.
    """
    existing_names = {name for name, _value in existing}
    return sorted({name for name, _value in managed if name in existing_names})


# ------------------------------------------------------------------- interchange


def interchange(profile_key, commands, display_name=None, warnings=()):
    # type: (str, list, object, object) -> dict
    """A ``mod-interchange.json`` document carrying our autoexec commands.

    ``mods`` stays empty on purpose: the format skips entries with no VPK on
    disk, and SpeedyLock has none. The commands live in ``profiles[].autoexec``,
    which is where DMM keeps "console commands that run at game launch".
    """
    return {
        "format": INTERCHANGE_FORMAT,
        "version": INTERCHANGE_VERSION,
        "mods": [],
        "profiles": [
            {
                "key": "speedylock-%s" % profile_key,
                "name": display_name or ("SpeedyLock %s" % profile_key),
                "enabled": True,
                "order": 0,
                "autoexec": list(commands),
            }
        ],
        "crosshairs": [],
        "warnings": list(warnings),
    }


_BUNDLE_README = """# SpeedyLock -- {title}

Generated for profile **{profile}**. These files are for use with Grimoire or
Deadlock Mod Manager (DMM). SpeedyLock itself does the real work:

```
python speedy.py install --profile {profile}{extra}
```

## Why this is not a .vpk

SpeedyLock changes `autoexec.cfg`, `video.txt` and the `ConVars` block inside
`gameinfo.gi`. Mod managers install `.vpk` files into `game/citadel/addons/`
and renumber them into `pakNN` slots. Those are different files, so the two
tools do not collide and neither needs to wrap the other.

The cross-manager `mod-interchange.json` format both projects use is also
VPK-only -- it skips mods with no VPK on disk -- and both treat autoexec as a
per-profile setting rather than a mod. That is why `mods[]` here is empty and
the commands sit in `profiles[].autoexec`.

## Grimoire

Grimoire has an autoexec manager for console commands that run at launch.
Paste the contents of `autoexec.cfg` there. Do not let it *replace* the file if
you have other commands in it; SpeedyLock writes its own marked block and can
merge with yours at any time by re-running `install`.

## Deadlock Mod Manager

Import `mod-interchange.json` from DMM's mod-interchange screen. Note that DMM
documents export of `profiles[].autoexec` as unsupported; import behaviour for
that field is not documented either, so if the commands do not appear, use the
Grimoire route or just run `speedy install`.
{notes}
## Both

Neither manager knows about the other's edits. If a manager restores a stock
`gameinfo.gi` or rewrites `autoexec.cfg`, SpeedyLock's changes go with it.
`speedy doctor` re-checks all three files and tells you what is missing.
"""


def write_bundle(dest, profile, commands, extra_install_args="", notes=()):
    # type: (Path, object, list, str, object) -> list
    """Write the manager-facing bundle, returning the paths created."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    written = []

    autoexec = dest / "autoexec.cfg"
    autoexec.write_text("".join(line + "\n" for line in commands), encoding="utf-8")
    written.append(autoexec)

    document = interchange(
        profile.key,
        commands,
        display_name="SpeedyLock %s" % profile.title,
        warnings=[
            "SpeedyLock is a config tool, not a VPK mod; commands are carried in "
            "profiles[].autoexec, not mods[].",
        ],
    )
    interchange_path = dest / "mod-interchange.json"
    interchange_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    written.append(interchange_path)

    note_block = ""
    if notes:
        note_block = "\n" + "".join("%s\n" % note for note in notes) + "\n"
    readme = dest / "README.md"
    readme.write_text(
        _BUNDLE_README.format(
            title=profile.title,
            profile=profile.key,
            extra=extra_install_args,
            notes=note_block,
        ),
        encoding="utf-8",
    )
    written.append(readme)
    return written
