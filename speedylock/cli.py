"""Command line interface for SpeedyLock."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import (
    __version__,
    bench,
    config,
    convars,
    cpu,
    detect,
    gamefiles,
    managers,
    profiles,
    release,
    tune,
)

ONLY_CHOICES = ("autoexec", "video", "gameinfo")


def _out(message=""):
    sys.stdout.write(str(message) + "\n")


def _err(message):
    sys.stderr.write("speedy: %s\n" % message)


def _install_or_die(args, required):
    """Resolve the install directory, or None when it is not needed."""
    try:
        return detect.find_install(getattr(args, "game_dir", None))
    except FileNotFoundError as exc:
        if required:
            _err(exc)
            raise SystemExit(2)
        return None


def _wants(args, target):
    only = getattr(args, "only", None)
    return not only or target in only


def _with_relief(args, profile):
    """Apply the opt-in CPU relief overlay, if it was asked for."""
    if getattr(args, "cpu_relief", False):
        return cpu.overlay(profile)
    return profile


def _resolve_video(profile, fps_cap):
    """Substitute {fps_cap} into the profile's video settings."""
    resolved = {}
    for key, value in profile.video.items():
        resolved[key] = str(value).replace("{fps_cap}", str(int(fps_cap)))
    return resolved


def _render_scale(args):
    """Validate --render-scale. Only ever applied when explicitly requested.

    Render scale is the largest remaining lever after shadows, which is exactly
    why no profile sets it on its own: silently resizing someone's game is not
    an optimisation, it is a surprise.
    """
    value = getattr(args, "render_scale", None)
    if value is None:
        return None
    if not (0.5 <= value <= 1.0):
        _err("--render-scale must be between 0.5 and 1.0 (got %s)" % value)
        raise SystemExit(2)
    return round(float(value), 3)


def _video_for(args, profile):
    """Profile video keys, with the optional render-scale override applied."""
    video = _resolve_video(profile, args.fps_cap)
    scale = _render_scale(args)
    if scale is not None:
        video[tune.RENDER_SCALE_KEY] = "%.3f" % scale
    return video


def _allowed_protected(args):
    return (tune.RENDER_SCALE_KEY,) if _render_scale(args) is not None else ()


def _gameinfo_for(args, profile):
    """Profile ConVars with {fps_cap} resolved, minus anything unwritable.

    The filter is the important half. Imported tiers carry 400+ pairs from a
    third-party config, and a config does not get to widen SpeedyLock's own
    rules: if the knowledge base says a convar is risky (or cheat-flagged, or
    not a Deadlock convar at all) it is dropped here, exactly as it would be on
    the autoexec side. Without this, importing a large config would be a hole
    straight through the validation every other profile has to pass.
    """
    experimental = bool(getattr(args, "experimental", False))
    keep = []
    for name, value in profile.gameinfo:
        cvar = convars.get(name)
        if cvar is not None and not cvar.is_writable(experimental):
            continue
        keep.append((name, str(value).replace("{fps_cap}", str(int(args.fps_cap)))))
    return keep


def _mip_bias_warning(settings):
    value = settings.get("setting.r_texture_stream_mip_bias")
    if value is None:
        return None
    try:
        bias = int(float(value))
    except (TypeError, ValueError):
        return None
    if bias <= gamefiles.MIP_BIAS_FIX_THRESHOLD:
        return None
    return (
        "texture streaming mip bias is %d, past the documented limit of %d. "
        "Sinner's light needs the fix VPK (OptiLock 'Essential Fixes', GPL-3.0) "
        "or set it back to %d." % (bias, gamefiles.MIP_BIAS_FIX_THRESHOLD, gamefiles.MIP_BIAS_FIX_THRESHOLD)
    )


def _report_cvarlist(args, names):
    """Cross-check convar names against a user-supplied dump, if any.

    Advisory on purpose. Community dumps are frequently partial -- OptiLock's
    cvarlist.md does not even list fps_max -- so a mismatch is far more likely
    to mean "incomplete list" than "convars that do not exist". Blocking on it
    would make install impossible for anyone pointing at such a file.
    """
    path = getattr(args, "cvarlist", None)
    if not path:
        return
    try:
        known = convars.load_cvarlist(path)
    except OSError as exc:
        _err("could not read --cvarlist %s: %s" % (path, exc))
        return
    missing = sorted({name for name in names if name not in known})
    if not missing:
        _out("[ok] all %d convars are present in %s" % (len(set(names)), Path(path).name))
        return
    _out(
        "[!] %d convar(s) not listed in %s: %s"
        % (len(missing), Path(path).name, ", ".join(missing))
    )
    _out("    community dumps are often partial; confirm in game with the F7 console")


def _print_machine(install, gpu, cpu):
    _out("  CPU        %s" % (cpu or "unknown"))
    _out("  GPU        %s" % (gpu or "unknown"))
    if install:
        _out("  Deadlock   %s" % install)
        _out("  config     %s" % detect.cfg_dir(install))
    else:
        _out("  Deadlock   not found")
        _out('             pass --game-dir, e.g. "C:/Program Files (x86)/Steam/steamapps/common/Deadlock"')


def _print_launch(profile):
    _out("Steam launch options:")
    _out("  %s" % " ".join(profile.launch_options))


# ------------------------------------------------------------------------- plan


def cmd_plan(args):
    install = _install_or_die(args, required=False)
    gpu = detect.gpu_name()
    cpu_name = detect.cpu_name()
    key = args.profile or detect.guess_profile(gpu)
    profile = _with_relief(args, profiles.get(key))
    video = _video_for(args, profile)
    gameinfo = _gameinfo_for(args, profile)

    _out("SpeedyLock %s -- plan (nothing written)" % __version__)
    _out()
    _print_machine(install, gpu, cpu_name)
    _out()
    _out("Profile: %s -- %s" % (profile.title, profile.blurb))
    if not args.profile:
        _out("  chosen automatically from your GPU; override with --profile")
    if cpu.is_relief_profile(profile.key):
        _out("  + CPU relief: %d extra convars for per-tick client CPU" % len(cpu.RELIEF))
    else:
        _out(
            "  [i] --cpu-relief adds %d convars that cut per-tick client CPU "
            "(`speedy cpu` explains them)" % len(cpu.RELIEF)
        )
    _out()

    _report_cvarlist(
        args, [name for name, _ in profile.settings] + [name for name, _ in profile.gameinfo]
    )

    if _wants(args, "autoexec"):
        try:
            block = config.render_block(
                profile, fps_cap=args.fps_cap, experimental=args.experimental
            )
        except config.ConfigError as exc:
            _err(exc)
            return 1
        _out("autoexec.cfg -- %d convars" % len(profile.settings))
        for line in block.rstrip("\n").splitlines():
            _out("  " + line)
        _out()

    if _wants(args, "video"):
        if install:
            targets = gamefiles.find_video_files(install) or [gamefiles.default_video_path(install)]
        else:
            targets = []
        _out("video.txt -- %d setting.* keys" % len(video))
        for path in targets:
            state = "exists" if path.exists() else "will be created"
            _out("  %s  (%s)" % (path, state))
        if not targets:
            _out("  <install not found; nothing to target>")
        _out("  protects deviceid, resolution, monitor, gamma -- those are yours")
        scale = _render_scale(args)
        if scale is not None:
            _out("  [opt-in] render scale %.3f (usually 0.5-1.0; lowers internal resolution)" % scale)
        warning = _mip_bias_warning(video)
        if warning:
            _out()
            _out("  [!] %s" % warning)
        _out()

    if _wants(args, "gameinfo"):
        _out("gameinfo.gi -- %d convar(s) merged into the existing ConVars block"
             % len(gameinfo))
        if install:
            gi = gamefiles.find_gameinfo(install)
            if gi.exists():
                span = gamefiles.find_convars_block(config.read_text(gi))
                state = "ConVars block found" if span else "NO ConVars block -- will skip"
                _out("  %s  (%s)" % (gi, state))
            else:
                _out("  %s  (not found -- will skip)" % gi)
        _out("  your file is merged, never replaced")
        _out()

    if args.fps_cap == 0:
        _out("fps_max is 0 (uncapped). `speedy bench <capture.csv>` gives you a cap")
        _out("that matches your hardware; then pass --fps-cap.")
        _out()

    _print_launch(profile)
    _out()
    _out("Also do this in game:")
    for step in profile.manual_steps:
        _out("  - %s" % step)
    _out()
    _out("Then: speedy install")
    return 0


# ---------------------------------------------------------------------- install


def cmd_install(args):
    install = _install_or_die(args, required=True)
    cfg_dir = detect.cfg_dir(install)
    key = args.profile or detect.guess_profile(detect.gpu_name())
    profile = _with_relief(args, profiles.get(key))
    video = _video_for(args, profile)
    gameinfo = _gameinfo_for(args, profile)

    _report_cvarlist(
        args, [n for n, _ in profile.settings] + [n for n, _ in gameinfo]
    )

    wrote_any = False

    # 1. autoexec.cfg
    if _wants(args, "autoexec"):
        try:
            result = config.install(
                cfg_dir,
                profile,
                fps_cap=args.fps_cap,
                experimental=args.experimental,
                dry_run=args.dry_run,
            )
        except config.ConfigError as exc:
            _err(exc)
            return 1
        if result.dry_run:
            _out("[dry] would write %s" % result.path)
        elif result.changed:
            wrote_any = True
            if result.previous_profile and result.previous_profile != profile.key:
                _out("[ok] %s  (%s -> %s)" % (result.path.name, result.previous_profile, profile.key))
            else:
                _out("[ok] %s  (profile %s)" % (result.path.name, profile.key))
            if result.backup:
                _out("     backup: %s" % result.backup)
        else:
            _out("[--] %s already up to date" % result.path.name)

    # 2. video.txt
    if _wants(args, "video"):
        targets = gamefiles.find_video_files(install) or [gamefiles.default_video_path(install)]
        for path in targets:
            original = config.read_text(path)
            if _render_scale(args) is None:
                # A downscale from an earlier run is never silently undone: we
                # do not write protected keys we were not asked to write. Say so
                # instead of leaving the user stuck at 0.5 with no explanation.
                leftover = dict(gamefiles.video_key_lines(original)).get(tune.RENDER_SCALE_KEY)
                if leftover is not None and leftover not in ("1", "1.0", "1.000", "1.000000"):
                    _out(
                        "[!] %s is still at render scale %s from an earlier run; "
                        "pass --render-scale 1.0 to reset it" % (path.name, leftover)
                    )
            try:
                merged = gamefiles.merge_video(
                    original, video, allow_protected=_allowed_protected(args)
                )
            except gamefiles.GameFileError as exc:
                _err("%s: %s" % (path, exc))
                return 1
            if merged == original:
                _out("[--] %s already up to date" % path)
                continue
            if args.dry_run:
                _out("[dry] would merge %d keys into %s" % (len(video), path))
                continue
            backup = None
            if original.strip():
                backup = config.backup_file(path.parent, original, label="video", suffix=".txt")
            config.atomic_write(path, merged)
            wrote_any = True
            _out("[ok] %s  (%d keys)" % (path, len(video)))
            if backup:
                _out("     backup: %s" % backup)
        warning = _mip_bias_warning(video)
        if warning and not args.dry_run:
            _out("[!] %s" % warning)

    # 3. gameinfo.gi
    if _wants(args, "gameinfo"):
        gi = gamefiles.find_gameinfo(install)
        if not gi.exists():
            _out("[--] gameinfo.gi not found; skipping ConVars merge")
        else:
            original = config.read_text(gi)
            try:
                updated = gamefiles.inject_gameinfo(original, gameinfo, profile.key)
            except gamefiles.GameFileError as exc:
                # Not fatal. autoexec.cfg already carries the same convars, so a
                # gameinfo.gi we cannot parse costs the startup-time head start,
                # not the optimisation -- and aborting here would leave a
                # half-finished install behind for no benefit.
                _out("[!] gameinfo.gi: %s" % exc)
                _out("    skipping it; autoexec.cfg sets the same convars")
            else:
                if updated == original:
                    _out("[--] gameinfo.gi already up to date")
                elif args.dry_run:
                    _out(
                        "[dry] would merge %d convars into %s"
                        % (len(gameinfo), gi)
                    )
                else:
                    backup = config.backup_file(
                        gi.parent, original, label="gameinfo", suffix=".gi"
                    )
                    config.atomic_write(gi, updated)
                    wrote_any = True
                    _out(
                        "[ok] gameinfo.gi  (%d convars merged, file preserved)"
                        % len(gameinfo)
                    )
                    _out("     backup: %s" % backup)

    if args.dry_run:
        _out()
        _out("Dry run: nothing was written.")
        return 0

    if not wrote_any:
        _out()
        _out("Everything was already in place.")

    _out()
    _print_launch(profile)
    _out()
    _out("Next:")
    _out("  1. Set those launch options in Steam > Deadlock > Properties.")
    _out("  2. Launch once. The game MAY rewrite video.txt from the menu on first")
    _out("     load; if settings revert, set the video menu to match and relaunch.")
    _out("  3. Revert everything with `speedy uninstall`.")
    return 0


# -------------------------------------------------------------------- uninstall


def cmd_uninstall(args):
    install = _install_or_die(args, required=True)
    cfg_dir = detect.cfg_dir(install)
    removed_any = False

    if _wants(args, "autoexec"):
        try:
            result = config.uninstall(cfg_dir, dry_run=args.dry_run)
        except config.ConfigError as exc:
            _err(exc)
            return 1
        if result.changed and not result.dry_run:
            removed_any = True
            _out("[ok] removed the SpeedyLock block from autoexec.cfg")
        elif not result.changed:
            _out("[--] no SpeedyLock block in autoexec.cfg")

    if _wants(args, "gameinfo"):
        gi = gamefiles.find_gameinfo(install)
        if not gi.exists():
            _out("[--] gameinfo.gi not found")
        else:
            original = config.read_text(gi)
            if not gamefiles.has_managed_convars(original):
                _out("[--] no SpeedyLock ConVars in gameinfo.gi")
            elif args.dry_run:
                _out("[dry] would remove the ConVars from gameinfo.gi")
            else:
                config.backup_file(gi.parent, original, label="gameinfo", suffix=".gi")
                config.atomic_write(gi, gamefiles.strip_gameinfo(original))
                removed_any = True
                _out("[ok] removed the SpeedyLock ConVars from gameinfo.gi")

    if _wants(args, "video"):
        targets = gamefiles.find_video_files(install)
        if not targets:
            _out("[--] no video.txt found")
        for path in targets:
            restored = config.restore_original(path.parent, "video", ".txt")
            if restored is None:
                _out("[--] no backup for %s; leaving it alone" % path)
                continue
            backup_path, text = restored
            if args.dry_run:
                _out("[dry] would restore %s from %s" % (path, backup_path.name))
                continue
            config.backup_file(path.parent, config.read_text(path), label="video", suffix=".txt")
            config.atomic_write(path, text)
            removed_any = True
            _out("[ok] restored %s from %s" % (path.name, backup_path.name))

    if args.dry_run:
        _out()
        _out("Dry run: nothing was written.")
        return 0

    _out()
    if removed_any:
        _out("Remember to remove the launch options too (keep -novid if you like it).")
    else:
        _out("Nothing to remove.")
    return 0


# ----------------------------------------------------------------------- doctor


def _audit_autoexec(cfg_dir):
    autoexec = Path(cfg_dir) / "autoexec.cfg"
    text = config.read_text(autoexec)
    if not autoexec.exists():
        _out("[--] autoexec.cfg: not present (run `speedy install`)")
        return 0, []

    try:
        _, block = config.strip_block(text)
    except config.ConfigError as exc:
        _out("[!!] autoexec.cfg: %s" % exc)
        return 1, []

    if block is None:
        _out("[--] autoexec.cfg: no SpeedyLock block")
    else:
        installed = config.block_profile(block)
        _out("[ok] autoexec.cfg: block present (profile: %s)" % installed)
        if cpu.is_relief_profile(installed):
            _out(
                "     [i] CPU relief is in this block; `install --profile %s` "
                "without --cpu-relief removes it" % cpu.base_key(installed)
            )

    issues = 0
    names = []
    for name, value in config.convar_lines(text):
        names.append(name)
        cvar = convars.get(name)
        if cvar is None:
            _out("     [??] %s \"%s\" -- unknown command, may be doing nothing" % (name, value))
            issues += 1
        elif cvar.status is convars.Status.CHEAT:
            _out("     [!!] %s \"%s\" -- cheat-flagged: %s"
                 % (name, value, cvar.description.split(".")[0]))
            issues += 1
        elif cvar.status is convars.Status.UNKNOWN:
            _out("     [??] %s \"%s\" -- not a Deadlock convar (Source 1 leftover)" % (name, value))
            issues += 1
        elif cvar.status is convars.Status.RISKY:
            _out("     [!!] %s \"%s\" -- real convar, real downside" % (name, value))
            issues += 1
    return issues, names


def _audit_video(install):
    targets = gamefiles.find_video_files(install)
    if not targets:
        _out("[--] video.txt: not found")
        return 0
    issues = 0
    for path in targets:
        pairs = dict(gamefiles.video_key_lines(config.read_text(path)))
        managed = [key for key in pairs if key.startswith("setting.")]
        _out("[ok] video.txt: %s (%d setting.* keys)" % (path, len(managed)))
        bias = pairs.get("setting.r_texture_stream_mip_bias")
        if bias is not None:
            try:
                if int(float(bias)) > gamefiles.MIP_BIAS_FIX_THRESHOLD:
                    _out("     [!] r_texture_stream_mip_bias %s needs the Sinner's Light "
                         "fix VPK, or set it back to %d"
                         % (bias, gamefiles.MIP_BIAS_FIX_THRESHOLD))
                    issues += 1
            except ValueError:
                pass
        if "deviceid" not in pairs:
            _out("     [!] no deviceid in this file -- the game may ignore it entirely")
            issues += 1
    return issues


def _audit_gameinfo(install):
    gi = gamefiles.find_gameinfo(install)
    if not gi.exists():
        _out("[--] gameinfo.gi: not found")
        return 0, []
    text = config.read_text(gi)
    if not gamefiles.has_managed_convars(text):
        _out("[--] gameinfo.gi: no SpeedyLock ConVars")
        return 0, []
    span = gamefiles.find_convars_block(text)
    if span is None:
        _out("[!!] gameinfo.gi: no ConVars block found at all")
        return 1, []
    every = gamefiles.all_convars_in_block(text)
    outside = gamefiles.convars_in_block(text)
    ours = every[len(outside) :]
    _out(
        "[ok] gameinfo.gi: %d convar(s) in the block (%d from SpeedyLock)"
        % (len(every), len(ours))
    )

    # Ours are injected just before the closing brace, so they win a redefinition
    # fight. Say so when another config also sets the same names.
    duplicates = managers.convar_duplicates(ours, outside)
    if duplicates:
        preview = ", ".join(duplicates[:4])
        if len(duplicates) > 4:
            preview += ", ..."
        _out(
            "     [i] %d convar(s) also set elsewhere in the block (%s); ours are "
            "defined last and win" % (len(duplicates), preview)
        )
    return 0, [name for name, _ in every]


def _audit_managers(install):
    """Report mod-manager coexistence: addons, the fix VPK, VRAM hints."""
    issues = 0
    findings = managers.detect_managers(install)
    addons = managers.scan_addons(install)

    for finding in findings:
        _out("[ok] mod manager: %s (%s)" % (finding.label, "; ".join(finding.evidence)))
    if not findings:
        _out("[--] no mod manager detected; a manual install behaves identically")

    if not addons:
        return issues

    fixes = managers.has_sinner_fix(addons)
    _out(
        "[ok] addons/: %d VPK(s); Sinner's Light fix %s"
        % (len(addons), "present" if fixes else "not detected")
    )
    if not fixes:
        for path in gamefiles.find_video_files(install):
            bias = dict(gamefiles.video_key_lines(config.read_text(path))).get(
                "setting.r_texture_stream_mip_bias"
            )
            if bias is None:
                continue
            try:
                too_high = int(float(bias)) > gamefiles.MIP_BIAS_FIX_THRESHOLD
            except (TypeError, ValueError):
                continue
            if too_high:
                _out(
                    "     [!] mip bias %s is above %d with no fix VPK: Sinner's "
                    "light renders wrong" % (bias, gamefiles.MIP_BIAS_FIX_THRESHOLD)
                )
                issues += 1

    if managers.has_potato_lock(addons):
        _out("[ok] a Potato Lock style texture VPK is installed (cuts VRAM use)")
    else:
        _out(
            "     hint: if your 1% lows collapse late-game, you may be VRAM-bound; "
            "Potato Lock (texture VPK) is the fix for that, not a lower resolution"
        )
    return issues


def cmd_doctor(args):
    _out("SpeedyLock %s -- doctor" % __version__)
    _out()
    install = _install_or_die(args, required=False)
    if not install:
        _out("[!!] Deadlock install not found. Pass --game-dir.")
        return 2

    cfg_dir = detect.cfg_dir(install)
    _out("[ok] Deadlock at %s" % install)
    if not cfg_dir.is_dir():
        _out("[!!] %s does not exist. Launch the game once so it creates it." % cfg_dir)
        return 2

    _out()
    issues, autoexec_names = _audit_autoexec(cfg_dir)
    issues += _audit_video(install)
    gi_issues, gi_names = _audit_gameinfo(install)
    issues += gi_issues
    issues += _audit_managers(install)

    if args.cvarlist:
        _report_cvarlist(args, autoexec_names + gi_names)

    _out()
    if issues:
        _out("%d thing(s) above are not doing what you think." % issues)
    else:
        _out("No problems found.")
    return 0


# ----------------------------------------------------------------------- tune


def cmd_tune(args):
    if args.file == "-":
        text = sys.stdin.read()
        label = "<stdin>"
    else:
        path = Path(args.file).expanduser()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            _err("could not read %s: %s" % (path, exc))
            return 2
        label = str(path)

    try:
        capture = bench.parse_capture(text)
    except bench.BenchError as exc:
        _err(exc)
        return 2

    stats = bench.analyze(capture.frametimes)
    result = tune.recommendation(stats, capture, refresh=args.refresh)

    _out("Capture: %s" % label)
    _out(bench.format_report(stats))
    _out()
    if capture.frame_column or capture.gpu_column:
        _out(
            "Columns read: frame=%s  gpu=%s"
            % (capture.frame_column or "?", capture.gpu_column or "none")
        )
        _out()
    if capture.gpu_fallback:
        _out(
            "[!] this capture has total GPU time, not GPU busy time. The ratio "
            "below overstates how busy the GPU was; re-capture with GPU "
            "tracking for a real split."
        )
        _out()
    _out("Bottleneck")
    if result["ratio"] is None:
        _out("  no usable GPU busy column in this capture -- verdict unknown")
    else:
        _out(
            "  GPU busy %5.1f%% of each frame  ->  %s"
            % (result["ratio"] * 100, tune.VERDICT_LABEL[result["verdict"]])
        )
    _out()
    _out("Do this")
    for line in tune.advice(result):
        _out("  - %s" % line)
    _out()

    profile = args.profile
    if profile is None:
        profile = "potato" if result["verdict"] == "cpu" else "balanced"
    _out("Apply:")
    _out("  %s" % tune.install_command(result, profile, getattr(args, "game_dir", None)))
    return 0


# ---------------------------------------------------------------------- integrate


def cmd_integrate(args):
    """Export the profile in the shape Grimoire and DMM understand."""
    install = _install_or_die(args, required=False)
    key = args.profile or detect.guess_profile(detect.gpu_name() if install else None)
    profile = _with_relief(args, profiles.get(key))

    try:
        block = config.render_block(
            profile, fps_cap=args.fps_cap, experimental=args.experimental
        )
    except config.ConfigError as exc:
        _err(exc)
        return 1
    commands = [
        line
        for line in block.rstrip("\n").splitlines()
        if line.strip() and not line.strip().startswith("//")
    ]

    _out("SpeedyLock %s -- integrate" % __version__)
    _out()
    if install:
        findings = managers.detect_managers(install)
        addons = managers.scan_addons(install)
        for finding in findings:
            _out("[ok] %s (%s)" % (finding.label, "; ".join(finding.evidence)))
        if not findings:
            _out("[--] no mod manager detected; the bundle still works by hand")
        if addons:
            _out(
                "[ok] %d VPK(s) in citadel/addons -- SpeedyLock never touches them"
                % len(addons)
            )
    else:
        _out("[--] Deadlock not found; writing the bundle anyway")

    dest = (
        Path(args.out)
        if args.out
        else Path.cwd() / "dist" / ("speedylock-" + profile.key)
    )
    notes = []
    warning = _mip_bias_warning(_resolve_video(profile, args.fps_cap))
    if warning:
        notes.append("* " + warning)

    written = managers.write_bundle(
        dest,
        profile,
        commands,
        extra_install_args=" --profile %s" % profile.key,
        notes=notes,
    )

    _out()
    _out("[ok] %s  (%d commands, profile %s)" % (dest, len(commands), profile.key))
    for path in written:
        _out("     %s" % path.name)
    _out()
    _out("Grimoire: paste autoexec.cfg into its autoexec manager.")
    _out("DMM:      import mod-interchange.json.")
    _out("Both:     run `speedy install` -- the bundle does not do the writing.")
    return 0


# ------------------------------------------------------------------ bench/convar


def cmd_bench(args):
    if args.file == "-":
        text = sys.stdin.read()
        label = "<stdin>"
    else:
        path = Path(args.file).expanduser()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            _err("could not read %s: %s" % (path, exc))
            return 2
        label = str(path)

    try:
        times = bench.parse_frametimes(text)
    except bench.BenchError as exc:
        _err(exc)
        return 2

    stats = bench.analyze(times)
    _out("Capture: %s" % label)
    _out(bench.format_report(stats))
    _out()
    _out("Apply with:  speedy install --fps-cap %d" % stats["stable_cap"])
    return 0


def cmd_convar(args):
    if not args.name:
        _out("SpeedyLock convar knowledge base (%d entries)" % len(convars.CONVARS))
        for status in (
            convars.Status.VERIFIED,
            convars.Status.GENERIC,
            convars.Status.RISKY,
            convars.Status.CHEAT,
            convars.Status.UNKNOWN,
        ):
            rows = convars.by_status(status)
            if not rows:
                continue
            _out()
            _out("  %s" % status.value)
            for cvar in rows:
                _out("    %-46s default %s" % (cvar.name, cvar.default or "-"))
        _out()
        _out("Details: speedy convar <name>")
        return 0

    cvar = convars.get(args.name)
    if cvar is None:
        _err("%r is not in the knowledge base. SpeedyLock will not write it." % args.name)
        return 2
    _out("%s" % cvar.name)
    _out("  status      %s%s" % (
        cvar.status.value,
        "" if cvar.is_writable() else "  (SpeedyLock will not write this)",
    ))
    _out("  default     %s" % (cvar.default or "unknown"))
    _out("  %s" % cvar.description)
    return 0


# --------------------------------------------------------------------- release


def cmd_release(args):
    """Build the bundle that a mod manager (or a person) can install from."""
    out = Path(args.out).expanduser() if args.out else Path.cwd() / "dist"
    key = args.profile or profiles.DEFAULT_PROFILE
    profile = _with_relief(args, profiles.get(key))

    _out("SpeedyLock %s -- release" % __version__)
    _out()
    try:
        built = release.build(
            out,
            profile,
            fps_cap=args.fps_cap,
            experimental=args.experimental,
            zip_it=not args.no_zip,
        )
    except OSError as exc:
        _err("could not build the bundle: %s" % exc)
        return 1

    _out("  bundle    %s" % built.directory)
    _out("  profile   %s  (%d commands)" % (built.profile.key, len(built.commands)))
    if built.archive is not None:
        size = built.archive.stat().st_size
        _out("  archive   %s  (%d KB)" % (built.archive, max(1, round(size / 1024.0))))
    problems = release.verify(built.directory)
    if problems:
        for problem in problems:
            _err(problem)
        return 1
    _out("  manifest  %d files, checksums verified" % len(built.files))
    _out()
    _out("Grimoire:  Autoexec manager -> paste autoexec.cfg")
    _out("DMM:       Mods Library -> Import config -> drop the archive or convars-block.txt")
    _out("DMM alt:   Mods Library -> Open export file... -> mod-interchange.json")
    _out("Installer: install.bat (Windows) or ./install.sh")
    return 0


# ------------------------------------------------------------------------- cpu


def cmd_cpu(args):
    _out("SpeedyLock %s -- CPU relief" % __version__)
    _out()
    _out("Per-tick client work this set removes:")
    _out()
    for label, rows in cpu.by_group():
        _out("  %s" % label)
        for row in rows:
            marker = "  (costs information)" if row.lossy else ""
            _out("    %-38s %-2s  %s%s" % (row.name, row.value, row.note, marker))
        _out()

    _out("Sold as CPU tweaks, not written here:")
    for name, why in cpu.NOT_WRITTEN:
        _out("    %-38s %s" % (name, why))
    _out()

    for line in cpu.explain():
        _out("  %s" % line)
        _out()

    _out("Apply:")
    _out(
        "  python speedy.py install --profile %s --cpu-relief"
        % (args.profile or profiles.DEFAULT_PROFILE)
    )
    return 0


# ----------------------------------------------------------------------- parser


def build_parser():
    parser = argparse.ArgumentParser(
        prog="speedy",
        description="SpeedyLock -- a Deadlock optimizer that refuses to lie to you.",
    )
    parser.add_argument("-v", "--version", action="version", version="SpeedyLock " + __version__)
    subparsers = parser.add_subparsers(dest="command")

    def add_target(sub, allow_dry_run=False):
        sub.add_argument("--game-dir", help="Deadlock install directory")
        sub.add_argument("--profile", choices=profiles.names(), help="override profile choice")
        sub.add_argument(
            "--fps-cap", type=int, default=0, metavar="N", help="value for fps_max (0 = uncapped)"
        )
        sub.add_argument(
            "--experimental",
            action="store_true",
            help="allow RISKY convars (never cheat-flagged ones)",
        )
        sub.add_argument(
            "--only",
            action="append",
            choices=ONLY_CHOICES,
            help="limit to one file (repeatable): autoexec, video, gameinfo",
        )
        sub.add_argument(
            "--cvarlist",
            metavar="PATH",
            help="convar dump to validate against, e.g. OptiLock's cvarlist.md",
        )
        sub.add_argument(
            "--render-scale",
            type=float,
            metavar="0.5-1.0",
            help="opt-in: scale internal render resolution (for GPU-bound hardware)",
        )
        sub.add_argument(
            "--cpu-relief",
            action="store_true",
            help="opt-in: also write the per-tick client CPU relief set (`speedy cpu`)",
        )
        if allow_dry_run:
            sub.add_argument("--dry-run", action="store_true", help="show, do not write")

    plan = subparsers.add_parser("plan", help="show what would be written (default)")
    add_target(plan)
    plan.set_defaults(func=cmd_plan)

    install = subparsers.add_parser("install", help="write the config")
    add_target(install, allow_dry_run=True)
    install.set_defaults(func=cmd_install)

    uninstall = subparsers.add_parser("uninstall", help="remove everything and restore backups")
    uninstall.add_argument("--game-dir", help="Deadlock install directory")
    uninstall.add_argument(
        "--only", action="append", choices=ONLY_CHOICES, help="limit to one file (repeatable)"
    )
    uninstall.add_argument("--dry-run", action="store_true", help="show, do not write")
    uninstall.set_defaults(func=cmd_uninstall)

    doctor = subparsers.add_parser("doctor", help="audit an existing install")
    doctor.add_argument("--game-dir", help="Deadlock install directory")
    doctor.add_argument("--cvarlist", metavar="PATH", help="convar dump to validate against")
    doctor.set_defaults(func=cmd_doctor)

    tune_parser = subparsers.add_parser(
        "tune", help="diagnose the bottleneck from a capture and apply the right knobs"
    )
    tune_parser.add_argument("file", help="PresentMon/CapFrameX export, or - for stdin")
    tune_parser.add_argument("--refresh", type=int, default=0, help="monitor refresh rate in Hz")
    tune_parser.add_argument("--profile", choices=profiles.names(), help="profile to suggest")
    tune_parser.add_argument("--game-dir", help="Deadlock install directory")
    tune_parser.set_defaults(func=cmd_tune)

    bench_parser = subparsers.add_parser(
        "bench", help="analyse a frametime capture and recommend an fps cap"
    )
    bench_parser.add_argument("file", help="CSV/txt frametime export, or - for stdin")
    bench_parser.set_defaults(func=cmd_bench)

    integrate = subparsers.add_parser(
        "integrate", help="export a bundle for Grimoire / Deadlock Mod Manager"
    )
    integrate.add_argument("--game-dir", help="Deadlock install directory")
    integrate.add_argument("--profile", choices=profiles.names(), help="profile to export")
    integrate.add_argument(
        "--fps-cap", type=int, default=0, metavar="N", help="value for fps_max (0 = uncapped)"
    )
    integrate.add_argument("--experimental", action="store_true")
    integrate.add_argument(
        "--out", help="output directory (default: dist/speedylock-<profile>)"
    )
    integrate.set_defaults(func=cmd_integrate)

    release_parser = subparsers.add_parser(
        "release", help="build the 1.0 bundle for Grimoire / Deadlock Mod Manager"
    )
    release_parser.add_argument(
        "--out", help="output directory (default: ./dist)"
    )
    release_parser.add_argument(
        "--profile", choices=profiles.names(), help="profile to build the bundle for"
    )
    release_parser.add_argument(
        "--fps-cap", type=int, default=0, metavar="N", help="value for fps_max (0 = uncapped)"
    )
    release_parser.add_argument("--experimental", action="store_true")
    release_parser.add_argument(
        "--cpu-relief", action="store_true", help="build it with the CPU relief set"
    )
    release_parser.add_argument(
        "--no-zip", action="store_true", help="leave the bundle as a folder only"
    )
    release_parser.set_defaults(func=cmd_release)

    cpu_parser = subparsers.add_parser(
        "cpu", help="what per-tick CPU can be freed, and what cannot"
    )
    cpu_parser.add_argument(
        "--profile", choices=profiles.names(), help="profile to describe the overlay for"
    )
    cpu_parser.set_defaults(func=cmd_cpu)

    convar_parser = subparsers.add_parser("convar", help="inspect the convar knowledge base")
    convar_parser.add_argument("name", nargs="?", help="convar to explain")
    convar_parser.set_defaults(func=cmd_convar)

    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["plan"]
    elif argv[0].startswith("-") and argv[0] not in ("-h", "--help", "-v", "--version"):
        argv.insert(0, "plan")

    args = build_parser().parse_args(argv)
    if not getattr(args, "func", None):
        build_parser().print_help()
        return 0
    try:
        return args.func(args)
    except KeyboardInterrupt:
        _err("interrupted")
        return 130
