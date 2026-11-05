# Credits and licensing

SpeedyLock would not exist without two community projects. Both are credited
here and, where their material is actually used, complied with.

## OptiLock -- https://github.com/dacooderr/OptiLock

**Used: yes, substantially.** SpeedyLock imports OptiLock's real `ConVars`
block (417 pairs) and its `video.txt` keys, extracted from the four tiers it
ships: *FPS Config (Recommended)*, *Potato*, *Ultra Potato* and *Community*.
Those power the `optilock`, `optilock-potato`, `optilock-ultra` and
`optilock-community` profiles.

Extracted at commit `77489664c3e2367c486a81ffd62b0f3f28d3454d`, read
2026-11-05. The extracted data lives in `speedylock/optilock.py`, which is
generated rather than hand-written so the provenance stays checkable.

OptiLock is licensed **GPL-3.0**, so SpeedyLock is licensed GPL-3.0 as well --
see [LICENSE.md](LICENSE.md). If you want a non-GPL take on the same idea, use
SpeedyLock's own `potato` / `balanced` / `quality` profiles, which are
independent of OptiLock's data.

What SpeedyLock does differently with that data, and why it is not just a copy:

* it **merges** the values into your existing `gameinfo.gi` and `video.txt`
  instead of asking you to replace both files
* it **does not carry display or hardware keys** -- resolution, monitor, gamma,
  render scale and `deviceid` are stripped on import, so OptiLock's
  `setting.r_fullscreen_gamma "2.200000"` will not land in your config
* it records the handful of values it does not copy verbatim, with reasons
  (`optilock.DISAGREE`) -- `cl_interp_ratio 0` and `cl_updaterate 128`, for
  instance, are clamped or ignored at Deadlock's 60-tick rate

Credit also to the people OptiLock credits: boot (potato config), simcasting
(benchmarking), pidjan (gameinfo contribution), Piggy (original video.txt),
Artemon121 (cvar unhider).

## Potato Lock -- https://gamebanana.com/mods/692484

**Used: no, and deliberately.** Potato Lock is not a config mod. It is a
texture-replacement VPK that swaps Deadlock's 4K PBR textures for 1x1 colour
textures, tinting materials instead, which cuts **VRAM** use -- and running out
of VRAM is a genuine cause of the frame drops low-end cards see.

SpeedyLock therefore points at it rather than containing it:

* it is licensed **CC BY-NC-ND 4.0** -- no derivatives, no commercial use -- so
  repackaging its assets, or shipping a modified VPK, would violate the licence
* a texture VPK is also orthogonal to a config tool: it belongs in
  `game/citadel/addons/`, which is the mod manager's territory, not SpeedyLock's

What SpeedyLock does with the insight is detect the condition: `speedy doctor`
reports whether a Potato-Lock-shaped VPK is installed and whether your texture
budget settings put you at risk of exceeding VRAM.

Author: abuzitin2000. 131k downloads, so it is clearly doing something right.

## Grimoire -- https://github.com/Slush97/grimoire

MIT. Not bundled; SpeedyLock only reads its documented behaviour to avoid
fighting it (see `speedylock/managers.py`).

## Deadlock Mod Manager -- https://docs.deadlockmods.app/

GPL-3.0. Not bundled. SpeedyLock writes the `mod-interchange.json` format that
DMM documents, and follows its `citadel/addons` + `pakNN` model so the two
tools never touch the same files.
