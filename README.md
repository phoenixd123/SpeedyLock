# SpeedyLock

A Deadlock optimizer that refuses to lie to you.

SpeedyLock takes the two community approaches that usually ship as competing
downloads — the "strip everything for frames" potato config and the
"competitive clarity on mid-range hardware" config — and puts them in one tool
with three tiers, hardware auto-detection, and a framerate cap calibrated from
your own capture data instead of someone else's screenshot.

It is also deliberately *non-destructive*. The big configs work by replacing
your `gameinfo.gi` wholesale and pasting a whole `video.txt` over yours.
SpeedyLock merges the keys it owns into the files you already have, backs up
before every write, and puts everything back on `uninstall`.

---

## Where this sits next to Potato Lock and OptiLock

| | Potato Lock | OptiLock | SpeedyLock |
| --- | --- | --- | --- |
| Ships as | reduced-graphics VPK | full `gameinfo.gi` replacement + `video.txt` to paste | merges into `autoexec.cfg`, `video.txt`, `gameinfo.gi` |
| Reversible | restore game files by hand | manual, and patches break it | `speedy uninstall` restores backups |
| Resolution / monitor / gamma | — | replaced by the preset | **never touched** |
| Survives a game patch | no | usually no, file is stale | yes, it merges rather than replaces |
| Cap choice | — | manual | computed from your frametime capture |
| Dead convars | unknown | curated | validated against a status-checked knowledge base |

Both projects are worth a look and both are credited below. This is an
independent reimplementation of the same *mechanics* — no code or config file
from either project is included here, which matters because OptiLock is
GPL-3.0 and vendoring its files would relicense this project.

## What SpeedyLock actually writes

Three files, each optional via `--only`:

| File | What goes in |
| --- | --- |
| `game/citadel/cfg/autoexec.cfg` | a marked block of runtime convars: fps cap, input, latency, ragdolls, debris |
| `video.txt` (cfg **or** userdata) | ~45 `setting.*` quality keys: shadows, SSAO, fog, bloom, particles, AA, mip bias |
| `gameinfo.gi` | a few convars merged **into the existing `ConVars` block**, never replacing the file |

That split is the whole performance picture. `autoexec` cannot touch most of the
visual cost — that lives in `video.txt`, which the game reads at startup and
rewrites from the video menu.

### Safety

- No DLL injection, no process hooking, no memory editing, no packet tricks.
- Nothing here reads game state or gives you information you should not have.
- Your own binds, FOV, `PGIVersion`, resolution, monitor and gamma are preserved.
- Every write is backed up to `speedy_backups/` before it happens.
- If a file is not in a shape SpeedyLock understands, it **refuses** and touches
  nothing, rather than writing something that might not launch.
- `speedy uninstall` restores each file from the **first** backup it ever took,
  which is the state before SpeedyLock touched anything.

Deadlock has VAC and a game-specific anti-cheat layer, and Valve has published no
safe-list, so no tool can promise you anything. A text config of documented
console variables is in a different category from anything that alters game
files or game state. SpeedyLock will not write cheat-flagged convars even if you
ask it to — `cl_disable_ragdolls` is cheat-flagged and silently does nothing in a
live match, which is why so many configs containing it are quietly inert.

---

## Install

Python 3.8+. No dependencies, no build step, no `pip install`.

```bash
git clone https://github.com/phoenixd123/SpeedyLock
cd SpeedyLock
python speedy.py plan
```

On Windows, `speedy.bat` finds the interpreter for you: `speedy.bat plan`.

## Quick start

```bash
python speedy.py plan       # inspect hardware and preview every change
python speedy.py install    # write autoexec + video.txt + gameinfo ConVars
python speedy.py doctor     # audit all three files
python speedy.py uninstall  # restore everything from backups
```

| Command | Purpose |
| --- | --- |
| `plan` | Detects hardware, shows exactly what would be written (default command) |
| `install` | Merges the profile into all three files |
| `uninstall` | Removes the managed blocks and restores backups |
| `doctor` | Audits `autoexec.cfg`, `video.txt` and `gameinfo.gi` |
| `bench <capture>` | Analyses a frametime export and recommends an fps cap |
| `tune <capture>` | Diagnoses GPU- vs CPU-bound and applies the knobs that matter |
| `convar [name]` | Explains a convar and whether SpeedyLock will write it |
| `cpu` | What per-tick client CPU can be freed, and what cannot |

Flags: `--game-dir`, `--profile`, `--fps-cap N`, `--only autoexec|video|gameinfo`
(repeatable), `--dry-run`, `--experimental`, `--cvarlist PATH`, `--cpu-relief`.

---

## Profiles

| Profile | For | Video tier |
| --- | --- | --- |
| `potato` | Integrated GPUs, old laptops, anything under 60fps | Everything off, mip bias 8 |
| `balanced` | **Default.** Mid-range, ranked play | Everything expensive off, outlines kept, mip bias 4 |
| `quality` | You want the game to look vanilla | **Nothing visual is written** — latency and UI only |

```bash
python speedy.py install --profile potato
python speedy.py install --profile balanced --fps-cap 141
python speedy.py install --only video --profile quality
```

`balanced` keeps hero outlines on: they are cheap and they are how you spot
people at range. `quality` is the tier neither community config offers — it
proves a config can lower latency and UI overhead without changing a single
pixel of the game.

---

## Frametime calibration

Average FPS is a bad target. Uncapped, the GPU runs at 100% utilisation against
its power and thermal limits, so every slow frame lands directly in your input
latency and in how much the camera judders. What you feel is the slow tail.

Cap slightly below the framerate your machine can *always* hold and the tail
flattens. `speedy bench` computes that from your own data:

```bash
python speedy.py bench capture.csv
```

```
Frametime report
  samples                 48210 frames
  average                  214.6 fps  (4.66 ms)
  median                   221.0 fps  (4.52 ms)
  1% low                   143.2 fps
  0.1% low                 118.9 fps
  99th pct frametime        6.94 ms
  99.9th pct frametime      8.41 ms
  tail / median            1.54x    noticeable stutter spikes - a cap will smooth this out

Recommended caps
  stable  --fps-cap 120   holds the 1% low; flattest frametimes
  fast    --fps-cap 180   holds the average; still steadier than uncapped
  0 (uncapped) if you would rather have the peak number than the feel.
```

Accepts PresentMon, CapFrameX, Afterburner or a plain one-number-per-line file.
Comma, semicolon, tab or pipe separated; finds the frametime column by header,
converts an `FPS` column, and falls back to the busiest numeric column.

The cap is written to both `fps_max` in `autoexec.cfg` and `setting.fps_max` in
`video.txt` so it survives the menus rewriting each other.

## Closed-loop tuning: more FPS without guessing

A cap is only half the decision. The other half is *which resource you are
waiting on*, and both community configs skip that step — they ship one fixed set
of values and hope it suits your machine.

```bash
python speedy.py tune capture.csv --refresh 165
```

PresentMon records `msGPUActive` per frame, so the split is measurable:

```
Bottleneck
  GPU busy  97.4% of each frame  ->  GPU-bound

Do this
  - GPU-bound: you are waiting on pixels. Physics and ragdoll convars will not help.
  - Lower render scale to 0.83 -- that is ~31% fewer pixels, sized from your own framerate.
  - Shadows and AA are already off in this profile; resolution is the only large lever left.
  - Cap to 120 (holds your 1% low).

Apply:
  python speedy.py install --profile balanced --fps-cap 120 --render-scale 0.83
```

If the same capture shows you **CPU-bound** — GPU idle for most of each frame —
the advice inverts. It tells you *not* to lower resolution, because that buys
zero frames and costs visual quality, and points at the potato profile's ragdoll
and debris convars instead. That inversion is the useful part: it is the
difference between tuning and cargo-culting someone else's config.

If the capture has no GPU timing column, the verdict is honestly reported as
*unknown* and you get the cap recommendation anyway.

### Render scale is opt-in, deliberately

`setting.mat_viewportscale` is the biggest remaining lever after shadows — it is
straight pixel cost — which is exactly why no profile sets it on its own.
Silently resizing someone's game is a surprise, not an optimisation, so the key
stays protected and `--render-scale 0.5-1.0` is the only way to unlock it.

The suggested value is `sqrt(current / target)` from your own capture, not a
number someone picked on their hardware. Fill rate scales with *pixel count*, so
the linear scale is the square root of the frame ratio: reaching 1.67x the
framerate needs a scale of `sqrt(1/1.67) ≈ 0.77`, which is about 40% fewer
pixels. A required downscale smaller than 0.95 is reported as not worth it rather
than suggested as a 1% saving.

Dropping the flag later does **not** undo it, because SpeedyLock will not write a
protected key it was not asked to write. It warns instead and tells you to pass
`--render-scale 1.0` (or `uninstall`) to go back.


---

## Freeing CPU in a teamfight (`--cpu-relief`)

Deadlock's client does not simulate the other two lanes — Valve's servers do. What
your CPU is charged every tick is the work for entities the client already knows
about, and a teamfight is when all of it arrives at once: particle systems and the
dynamic light each effect asks for, ragdolls, breakable debris, props with physics,
and decoding the snapshot that lands sixty times a second.

`--cpu-relief` layers that set onto any profile, and writes it to **both**
`autoexec.cfg` and the `gameinfo.gi` `ConVars` block, so a manager rewriting
`video.txt` cannot undo it:

| convar | value | what it stops |
| --- | --- | --- |
| `cl_simulate_dormant_entities` | `0` | stepping entities the server marked dormant |
| `cl_ragdoll_limit` | `0` | ragdolls — each one is a simulated body |
| `func_break_max_pieces` | `0` | debris physics from breakable props |
| `cl_phys_animated_hierarchy` | `0` | physics on animated prop hierarchies |
| `phys_multithreading_enabled` | `1` | keeps VPhysics on job threads |
| `cl_parallel_readpacketentities` | `1` | decodes snapshots off the main thread |
| `cl_aggregate_particles` | `1` | batches particle systems into shared work |
| `cl_particle_batch_mode` | `1` | the batched particle path |
| `cl_particle_fallback_base` / `_multiplier` | `5` / `5` | matches the video profiles instead of disagreeing with them |
| `cl_particle_sim_fallback_threshold_ms` | `0` | falls back to cheaper effects immediately |
| `r_citadel_disable_particle_lights` | `1` | one dynamic light per effect |

```bash
python speedy.py cpu                        # what it writes, and what it refuses to
python speedy.py plan --cpu-relief          # see the diff first
python speedy.py install --cpu-relief       # layer it on your profile
```

It is opt-in because it is visible under load: cheaper effects, no ragdolls, no
debris. Re-running `install` without the flag removes it again, and `doctor` says
which block you are running.

### What it cannot do, and what other configs get wrong

The other lanes are ticked on Valve's hardware. Nothing in a client config changes
that, and a config that claims otherwise is describing the server's job.

The `ai_*` convars are where this gets concrete. OptiLock ships
`ai_lod_auto_enabled`, `ai_think_interval_lod_med`,
`ai_think_interval_lod_very_low` and `ai_use_async_ragdoll_fixup`; Valve's own
[Deadlock convar list](https://developer.valvesoftware.com/wiki/List_of_Deadlock_console_commands_and_variables)
flags every one of them `sv`, i.e. server-side. A client `autoexec` cannot run
them, so they free nothing on your machine. `speedy cpu` lists them rather than
copying them, because running them and believing they worked is the failure mode
this tool is built against.

Four more that save real work and are still not written:

| convar | why not |
| --- | --- |
| `cl_disable_ragdolls` | cheat-flagged: inert in a live match |
| `cl_particle_simulate 0` | cheat-flagged, and it removes effects you need to read a fight |
| `particle_cluster_nodraw`, `cl_impacteffects` | hide world effect clusters and bullet-impact feedback — that is information |
| `panorama_min_comp_layer_cache_cost` | exists in Deadlock, undocumented; no guessed HUD values |

If `speedy tune` says you are GPU-bound, skip this: cutting simulation does nothing
when you are waiting on pixels. It is the CPU-bound branch of `tune` that suggests
it, from your own capture rather than from a hunch.

---

## video.txt: what is and is not touched

SpeedyLock only writes quality and latency keys. These are **never** written,
whatever a preset says:

`deviceid`, `setting.defaultres`, `setting.defaultresheight`,
`setting.fullscreen`, `setting.nowindowborder`, `setting.monitor_index`,
`setting.refreshrate_*`, `setting.aspectratiomode`, `setting.high_dpi`,
`setting.r_fullscreen_gamma`, `setting.mat_viewportscale`

If you ask for one of those, you get an error — not a quietly overwritten
resolution. Values are matched in place so your file keeps its order and
comments; new keys are inserted before the closing brace; brace balance is
verified before writing.

**Mip bias caveat.** `potato` sets `r_texture_stream_mip_bias` to 8, past the
documented limit of 4. Sinner's light will render incorrectly without the fix
VPK (OptiLock's `Essential Fixes`, GPL-3.0). `doctor` warns about this. Drop the
key to `4` if you would rather not install a VPK.

## gameinfo.gi: merge, not replace

OptiLock's approach is to overwrite `gameinfo.gi` (a 46KB file) with its own copy.
SpeedyLock locates the existing `ConVars { }` block, inserts a marked handful of
convars before its closing brace, and leaves the other ~2000 lines — including
your `PGIVersion`, FOV and everything else — alone.

If there is no recognisable `ConVars` block, it refuses and changes nothing.

## Validating convars against your own build

The knowledge base is curated, so it can lag a patch. Point SpeedyLock at a
convar dump from **your** install and it will cross-check every name it is about
to write:

```bash
python speedy.py doctor  --cvarlist path/to/cvarlist.md
python speedy.py install --cvarlist path/to/cvarlist.md
```

Both the pipe-table format (`name | default | flags | description`) and a plain
console `cvarlist` dump are parsed.

The check is **advisory**, and that is deliberate: community dumps are often
partial. OptiLock's own `cvarlist.md` does not list `fps_max`, `cl_updaterate`
or `cl_interp_ratio`, all of which obviously exist. So a mismatch is reported as
`[!]` rather than blocking the install, and the real guardrail remains the
status-checked knowledge base. The only authoritative check is your own F7
console.

## The convar knowledge base

| Status | Meaning | Written? |
| --- | --- | --- |
| `verified` | Documented as working in Deadlock | Yes |
| `generic` | Standard Source 2 convar, harmless, possibly a no-op | Yes |
| `risky` | Real convar with a real downside | Only with `--experimental` |
| `cheat` | Cheat-flagged or information-gathering | **Never** |
| `unknown` | Believed to exist but unconfirmed (usually Source 1 leftover) | **Never** |

```bash
python speedy.py convar                   # list
python speedy.py convar cl_ragdoll_limit  # explain one
```

Highlights: `fps_max`, `fps_max_ui`, `cl_input_enable_raw_keyboard`,
`engine_low_latency_sleep_after_client_tick`, `cl_interp_ratio`,
`cl_ragdoll_limit`, `func_break_max_pieces` — and the traps:
`cl_disable_ragdolls` (cheat-flagged, inert), `mat_queue_mode` / `r_shadows` /
`cl_forcepreload` (Source 1, gone), `r_drawothermodels 2` (a wallhack).

---

## Troubleshooting

**Settings do not stick.** Add `-console -exec autoexec` to launch options, or
type `exec autoexec` in the console (F7) once per session.

**video.txt changes revert after a launch.** The game rewrites `video.txt` from
the video menu. Set the menu to match the profile, then relaunch. `doctor` will
tell you which file it is reading if you have both a cfg and a userdata copy.

**`speedy: Could not find Deadlock.`** Pass
`--game-dir "C:/Program Files (x86)/Steam/steamapps/common/Deadlock"`.

**"gameinfo.gi has no ConVars block that SpeedyLock can recognise."** Your file
has been replaced by a third-party preset with a different shape. Restore the
vanilla file through Steam, or run `uninstall` if SpeedyLock was the one that
changed it.

**It complains about a missing end marker.** Deliberate. It will not guess where
your binds end. Delete the lines between the two markers and reinstall.

**Audio crackles.** Raise `snd_mixahead` back to `0.05`.

---

## Development

```bash
python -m unittest discover -s tests -t . -v
```

`convars.py` is the knowledge base, `profiles.py` the three tiers,
`config.py` the autoexec surgery, `gamefiles.py` the video/gameinfo merge
layer, `tune.py` the bottleneck diagnosis, and `bench.py` the statistics.
Standard library only, no dependencies.

## Credits

- **dacooderr / OptiLock** (GPL-3.0) — established `video.txt` and the
  `gameinfo.gi` `ConVars` block as the real levers, and documented the Sinner's
  Light mip-bias threshold. No files from that project are included here; get its
  VPK fixes from its own repo.
- **abuzitin2000 / Potato Lock** on GameBanana — the reduced-graphics approach.
- The Deadlock community for the convar research this knowledge base is built on.

## Honest limitations

- SpeedyLock cannot make a GPU faster than it is. CPU-bound in a teamfight? The
  physics toggles help. GPU-bound at 4K? Only video settings help, and `plan`
  says so.
- Convar validation is against a curated list, not the live executable. Use
  `--cvarlist` to check against your own build.
- Windows is the primary target; Linux paths are detected for Proton users and
  the GPU probe there is best-effort.
- The merge logic assumes Valve's `gameinfo.gi` and `video.txt` shapes. If a
  patch restructures them, SpeedyLock refuses rather than writing blind — that is
  the intended failure mode, but it does mean a patch can require updating this
  tool.
- Not tested against a running Deadlock client. The file mechanics are covered by
  tests; the in-game effect of each convar is documented, not measured here.

## OptiLock, imported rather than paraphrased

The `optilock`, `optilock-potato`, `optilock-ultra` and `optilock-community`
profiles do not describe OptiLock. They carry its actual `ConVars` block --
**417 pairs**, extracted from the `gameinfo.gi` each tier ships -- plus its
`video.txt` keys. The extraction is generated into `speedylock/optilock.py` so
the provenance stays auditable; `CREDITS.md` records the commit it came from.

Two things the extraction turned up that the project's own docs do not say:

* **The tiers are nearly the same config.** Recommended, Potato and Ultra have
  an identical `ConVars` block except for **9 rows**, and their `video.txt`
  differs in **4 keys**. The real difference between "Potato" and "Ultra
  Potato" is `r_farz` (8500 -> 7000), `r_mapextents` (200 -> 100) and a few
  decal/colour-correction toggles. If your framerate barely moves between
  tiers, that is why.
* **OptiLock never sets `fps_max` in `ConVars` at all.** The cap only exists in
  its `video.txt`, so a user who replaces `gameinfo.gi` but keeps their own
  `video.txt` gets no cap. SpeedyLock writes it to both, from `--fps-cap`.

Where SpeedyLock deliberately does **not** copy OptiLock (`optilock.DISAGREE`,
enforced by `optilock.SAFE_VALUES`):

| convar | OptiLock | SpeedyLock | why |
| --- | --- | --- | --- |
| `cl_interp_ratio` | `0` | `1` | Source clamps 0 to 1 anyway; write what the engine does |
| `cl_updaterate` | `128` | `60` | Deadlock ticks at 60; the rest is ignored at best |
| `cl_resend` | `15` | *not written* | 15s retransmit window; the KB flags it risky |
| `citadel_camera_hero_fov` | `100` | *not written* | your FOV is a preference, not an optimisation |
| `r_aspectratio` | `2.15` | *not written* | same -- OptiLock's own FAQ says to set these yourself |

Display and hardware keys are stripped on import, not just at write time --
OptiLock's `setting.r_fullscreen_gamma "2.200000"` and
`setting.mat_viewportscale "1.000000"` never reach your file.

## Works with Grimoire and Deadlock Mod Manager

SpeedyLock and a mod manager do not compete, because they own different files:

| | owns | writes |
| --- | --- | --- |
| Grimoire / DMM | `game/citadel/addons/*.vpk`, `pakNN` slots, load order | VPKs |
| SpeedyLock | `autoexec.cfg`, `video.txt`, `ConVars` in `gameinfo.gi` | config |

`speedy integrate --profile optilock` exports a bundle in the shape each
manager understands:

```
dist/speedylock-optilock/
  autoexec.cfg          plain commands, for Grimoire's autoexec manager
  mod-interchange.json  format "deadlock-mod-interchange" v1, for DMM
  README.md             what to do in each, and what not to
```

The `mods[]` array in that document is **empty on purpose**. The interchange
format is VPK-only -- DMM's docs say it "skips mods with no VPK on disk" -- and
both managers treat `autoexec` as a per-profile *setting* rather than a mod
asset. So the commands go in `profiles[].autoexec`, which is the documented
home for console commands that run at launch.

This is also why SpeedyLock is not shipped as a `.vpk`: whether the engine
resolves `cfg/` through the addon search path is not documented anywhere, so no
part of this tool depends on it.

`speedy doctor` reports which manager it thinks is installed and on what
evidence, counts the addons, checks whether the Sinner's Light fix VPK is
present when your mip bias needs it, and warns when another config in the same
`ConVars` block defines a convar SpeedyLock also writes (ours are injected last,
so ours win).

## Potato Lock: recommended, not bundled

[Potato Lock](https://gamebanana.com/mods/692484) is not a config mod. It
replaces Deadlock's 4K PBR textures with 1x1 colour textures and tints
materials instead, which cuts **VRAM** use -- and running out of VRAM is a real
cause of the late-game frame drops low-end cards get.

It is **CC BY-NC-ND 4.0** (no derivatives, no commercial use), so repackaging
it would break its licence, and a texture VPK belongs in `addons/` where the
mod manager lives. SpeedyLock only points at it: `doctor` tells you when a
Potato-Lock-shaped VPK is already installed, and suggests it when your 1% lows
look memory-bound rather than resolution-bound.

## Licensing

SpeedyLock carries data extracted from OptiLock, which is **GPL-3.0**, so
SpeedyLock is GPL-3.0 too -- see [LICENSE.md](LICENSE.md). The `potato`,
`balanced` and `quality` profiles are SpeedyLock's own and do not depend on
OptiLock's data. Full attribution: [CREDITS.md](CREDITS.md).
