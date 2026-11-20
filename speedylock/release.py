"""Build the shippable 1.0 release bundle.

The bundle is shaped by what the two managers actually accept, not by what looks
tidy:

* **Deadlock Mod Manager** reads ``mod-interchange.json`` ("Open export file…")
  and, separately, has an *Import config* path that takes a ``.zip``/archive,
  an ``autoexec`` file, or a pasted ``ConVars`` block. That config path is the
  right home for SpeedyLock, because SpeedyLock is config and not assets.
* **Grimoire** installs only ``.vpk`` files into ``citadel/addons`` and keeps a
  separate Autoexec manager for console commands, so the bundle's
  ``autoexec.cfg`` is what goes there. Grimoire ignores the rest of the files,
  which is fine -- they are for the installer and for the user.

Both interchange bundles in the wild carry VPKs in ``files/``; this one carries
none and leaves ``mods[]`` empty, because a VPK containing ``cfg/`` is not
documented to work and shipping an inert one would be a lie with a filename.

Everything the bundle contains is generated from the profile you build it with,
so ``autoexec.cfg``, ``convars-block.txt`` and the interchange profile cannot
disagree with each other.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path

from . import __version__, config, managers

BUNDLE_PREFIX = "speedylock-"

#: Fixed timestamp so building the same bundle twice produces the same bytes.
_ZIP_STAMP = (1980, 1, 1, 0, 0, 0)

_DOC_FILES = ("README.md", "LICENSE.md", "CREDITS.md")
_CODE_FILES = ("speedy.py", "speedy.bat")

INSTALL_PY = '''#!/usr/bin/env python3
"""One-file installer shipped inside the SpeedyLock release bundle.

Run it with no arguments to install, or pass any ``speedy`` command through:
``install.py plan``, ``install.py doctor``, ``install.py uninstall``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from speedylock.cli import main  # noqa: E402

DEFAULT = ["install", "--profile", {profile!r}, "--fps-cap", {fps_cap!r}]

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or DEFAULT))
'''

INSTALL_BAT = """@echo off
rem SpeedyLock installer. Writes the config, then opens doctor's report.
setlocal
set "HERE=%~dp0"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 "%HERE%install.py" %*
  set "RC=%ERRORLEVEL%"
  goto done
)
where python >nul 2>nul
if %ERRORLEVEL%==0 (
  python "%HERE%install.py" %*
  set "RC=%ERRORLEVEL%"
  goto done
)
echo SpeedyLock needs Python 3.8 or newer.
echo Install it from https://www.python.org/downloads/ and tick
echo "Add python.exe to PATH" during setup, then run this file again.
set "RC=1"

:done
echo.
pause
exit /b %RC%
"""

UNINSTALL_BAT = """@echo off
rem Removes the SpeedyLock block and restores the backups.
setlocal
call "%~dp0install.bat" uninstall
"""

INSTALL_SH = """#!/bin/sh
# SpeedyLock installer. Pass any speedy command: ./install.sh plan, ./install.sh uninstall
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
if command -v python3 >/dev/null 2>&1; then
  exec python3 "$HERE/install.py" "$@"
fi
exec python "$HERE/install.py" "$@"
"""

RELEASE_README = """# SpeedyLock {version} — install guide

SpeedyLock writes three things: a marked block of convars in
`game/citadel/cfg/autoexec.cfg`, quality keys merged into `video.txt`, and a few
convars merged into the existing `ConVars` block of `gameinfo.gi`. It never
replaces a file, never touches resolution, monitor, gamma or `deviceid`, and
backs everything up first.

This folder is the **1.0 release bundle**. It carries the config files a mod
manager can read plus the installer that does the actual writing.

| File | For |
| --- | --- |
| `install.bat` / `install.sh` | one-step install; backs up, merges, prints the report |
| `uninstall.bat` | removes the block and restores the backups |
| `autoexec.cfg` | the commands, plain — for Grimoire's Autoexec manager |
| `convars-block.txt` | every convar the install applies, as a `ConVars` block |
| `mod-interchange.json` | DMM "Open export file…" / Grimoire "Import from file…" |
| `speedy.py`, `speedylock/` | the tool itself, so the installer works offline |
| `release-manifest.json` | SHA-256 of every file here |

Profile **{profile}**, fps cap **{fps_cap}**, relief **{relief}**.

## 30 seconds: the installer

Windows: double-click `install.bat`. macOS/Linux/Proton: `./install.sh`.

```bash
./install.sh plan      # what would be written, nothing touched
./install.sh           # write it
./install.sh doctor    # audit all three files
./install.sh uninstall # put everything back
```

Drop `--game-dir "…/steamapps/common/Deadlock"` on the end if detection fails.

## Grimoire

Grimoire installs only `.vpk` files and has a separate **Autoexec manager** for
console commands that run at launch. Open `autoexec.cfg` from this folder, copy
it, paste it into the Autoexec manager. Do not let it replace a file you already
use — SpeedyLock writes a marked block and merges, but a manual paste does not.

If you want the visual keys in `video.txt` as well, that part is not something a
manager does; run `install.sh` once and let SpeedyLock handle all three files.

## Deadlock Mod Manager

Two routes, both under **Mods Library**:

1. **Import config** — drop `speedylock-{version}.zip`, `autoexec.cfg` or
   `convars-block.txt` into it. DMM shows what will apply and what will not
   before writing, and does not copy a mod's `gameinfo.gi` over yours. This is
   the route that matches what SpeedyLock is: config, not assets.
2. **Open export file…** — pick `mod-interchange.json`. The commands ride in
   `profiles[].autoexec`, which is where DMM keeps console commands that run at
   launch. `mods[]` is empty on purpose; see below.

## Why there is no .vpk

A `.vpk` is the only thing both managers will *install* as a mod, and it is the
one thing this project will not fake. Whether the engine resolves `cfg/` through
the addon search path is not documented anywhere, so a VPK containing
`autoexec.cfg` would install cleanly, appear in your library, and very possibly
change nothing at all — or fight the `gameinfo.gi` that the manager rewrites on
every launch. An inert download with a green tick is worse than an honest
config tool.

## What gets written, and how to undo it

```
autoexec.cfg   a marked block; your own commands outside it are untouched
video.txt      quality keys merged in place; display keys are refused
gameinfo.gi    convars merged before the existing ConVars closing brace
```

`uninstall` restores each file from the first backup SpeedyLock ever took, which
is the state before it touched anything. `doctor` re-checks all three files and
says which profile is installed — that key pastes straight back into `install`.

Full documentation, the convar knowledge base and the honest limitations are in
`DOCUMENTATION.md`. Licensing and attribution: `LICENSE.md`, `CREDITS.md`.
"""


class Release(object):
    """What ``build`` produced."""

    __slots__ = ("directory", "files", "archive", "profile", "commands")

    def __init__(self, directory, files, archive, profile, commands):
        self.directory = Path(directory)
        self.files = list(files)
        self.archive = Path(archive) if archive else None
        self.profile = profile
        self.commands = list(commands)

    def __repr__(self):
        return "Release(%r, %d files)" % (str(self.directory), len(self.files))


def bundle_name(version=None):
    return "%s%s" % (BUNDLE_PREFIX, version or __version__)


def commands_for(profile, fps_cap=0, experimental=False):
    """The plain console commands, in the same shape the managers expect."""
    block = config.render_block(profile, fps_cap=fps_cap, experimental=experimental)
    return [
        line
        for line in block.rstrip("\n").splitlines()
        if line.strip() and not line.strip().startswith("//")
    ]


def convars_block(profile, fps_cap=0):
    """Every convar SpeedyLock applies, as a paste-able block.

    ``profile.gameinfo`` alone is what gets merged into ``gameinfo.gi``, and for
    the hand-written tiers that is a single readable toggle -- so a block built
    from it would hand a DMM *Import config* user no cap and no latency keys.
    The runtime settings are folded in here as well, which is why this file is
    "the convar set", not "the gameinfo merge".
    """
    pairs = list(profile.gameinfo)
    seen = {name for name, _value in pairs}
    pairs.extend((name, value) for name, value in profile.settings if name not in seen)

    lines = ["ConVars", "{"]
    for name, value in pairs:
        resolved = str(value).replace("{fps_cap}", str(int(fps_cap)))
        lines.append('\t"%s"\t"%s"' % (name, resolved))
    lines.append("}")
    return "\n".join(lines) + "\n"


def _sha256(path):
    digest = hashlib.sha256()
    with open(str(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(source), str(target))
    return target


def _write(path, text, newline="\n"):
    """Write text without platform newline translation.

    ``Path.write_text`` translates ``\\n`` to ``os.linesep``, which would turn
    the ``.sh`` installer into CRLF script the moment someone builds the bundle
    on Windows -- and make the zip bytes depend on the build machine.
    """
    with open(str(path), "w", encoding="utf-8", newline=newline) as handle:
        handle.write(text)
    return path


def _source_root():
    return Path(__file__).resolve().parent.parent


def build(out, profile, fps_cap=0, experimental=False, source_root=None, zip_it=True):
    """Write the bundle into `out` and, unless told not to, zip it.

    A bundle of the same name that is already there is replaced wholesale, so
    rebuilding can never leave a stale file behind (the manifest would catch it,
    but the point is that it cannot happen).
    """
    root = _source_root() if source_root is None else Path(source_root)
    directory = Path(out) / bundle_name()
    if directory.exists():
        shutil.rmtree(str(directory))
    directory.mkdir(parents=True)

    commands = commands_for(profile, fps_cap=fps_cap, experimental=experimental)
    written = []

    autoexec = _write(directory / "autoexec.cfg", "".join(line + "\n" for line in commands))
    written.append(autoexec)

    convars = _write(directory / "convars-block.txt", convars_block(profile, fps_cap=fps_cap))
    written.append(convars)

    document = managers.interchange(
        profile.key,
        commands,
        display_name="SpeedyLock %s" % profile.title,
        warnings=[
            "SpeedyLock is a config tool, not a VPK mod: commands are carried in "
            "profiles[].autoexec and mods[] is empty on purpose.",
        ],
    )
    interchange_path = _write(
        directory / "mod-interchange.json", json.dumps(document, indent=2) + "\n"
    )
    written.append(interchange_path)

    install_py = _write(
        directory / "install.py",
        INSTALL_PY.format(profile=profile.key, fps_cap=int(fps_cap)),
    )
    written.append(install_py)

    for name, text in (("install.bat", INSTALL_BAT), ("uninstall.bat", UNINSTALL_BAT)):
        written.append(_write(directory / name, text.replace("\n", "\r\n"), newline=""))

    install_sh = _write(directory / "install.sh", INSTALL_SH)
    try:
        os.chmod(str(install_sh), 0o755)
    except OSError:
        pass
    written.append(install_sh)

    readme = _write(
        directory / "README.md",
        RELEASE_README.format(
            version=__version__,
            profile=profile.key,
            fps_cap="uncapped (0)" if not fps_cap else int(fps_cap),
            relief="on" if profile.key.endswith("-cpu") else "off",
        ),
    )
    written.append(readme)

    # The project's own README is long-form documentation; the bundle's README is
    # the install guide, so the former ships under a name that cannot be confused
    # with it.
    project_readme = root / "README.md"
    if project_readme.is_file():
        written.append(_copy(project_readme, directory / "DOCUMENTATION.md"))
    for name in _DOC_FILES:
        source = root / name
        if source.is_file() and name != "README.md":
            written.append(_copy(source, directory / name))
    for name in _CODE_FILES:
        source = root / name
        if source.is_file():
            written.append(_copy(source, directory / name))

    package = root / "speedylock"
    if package.is_dir():
        target = directory / "speedylock"
        target.mkdir(exist_ok=True)
        for path in sorted(package.glob("*.py")):
            written.append(_copy(path, target / path.name))

    files = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        files.append(
            {
                "path": path.relative_to(directory).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )

    manifest = {
        "name": BUNDLE_PREFIX.rstrip("-"),
        "version": __version__,
        "profile": profile.key,
        "fps_cap": int(fps_cap),
        "interchange": {
            "format": managers.INTERCHANGE_FORMAT,
            "version": managers.INTERCHANGE_VERSION,
        },
        "entrypoints": ["install.bat", "install.sh", "install.py"],
        "commands": len(commands),
        "files": files,
    }
    manifest_path = directory / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    written.append(manifest_path)

    archive = _archive(directory) if zip_it else None
    if archive is None:
        # A zip left over from an earlier build would claim to be this bundle and
        # not be one. Same reasoning as replacing the folder wholesale.
        stale = directory.parent / (directory.name + ".zip")
        if stale.exists():
            stale.unlink()
    return Release(directory, manifest["files"], archive, profile, commands)


def _archive(directory):
    """Zip the bundle with fixed timestamps so rebuilds are byte-identical."""
    directory = Path(directory)
    target = directory.parent / (directory.name + ".zip")
    with zipfile.ZipFile(str(target), "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            arcname = "%s/%s" % (
                directory.name,
                path.relative_to(directory).as_posix(),
            )
            info = zipfile.ZipInfo(arcname, date_time=_ZIP_STAMP)
            mode = 0o755 if path.suffix in (".sh",) else 0o644
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return target


def verify(directory):
    """Problems with a built bundle, as strings. Empty list means it checks out."""
    directory = Path(directory)
    manifest_path = directory / "release-manifest.json"
    if not manifest_path.is_file():
        return ["release-manifest.json is missing"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    problems = []
    listed = set()
    for entry in manifest.get("files", []):
        listed.add(entry["path"])
        path = directory / entry["path"]
        if not path.is_file():
            problems.append("missing: %s" % entry["path"])
            continue
        actual = _sha256(path)
        if actual != entry["sha256"]:
            problems.append("changed: %s" % entry["path"])

    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(directory).as_posix()
        if relative == "release-manifest.json" or relative in listed:
            continue
        problems.append("not in manifest: %s" % relative)
    return problems


def zip_names(archive):
    """Member names of a built archive, in order."""
    with zipfile.ZipFile(str(archive)) as handle:
        return handle.namelist()
