"""Client-side CPU relief for teamfights.

Your client does **not** simulate the other two lanes -- Valve's servers do. The
cost that lands on your CPU every tick is the work for entities the client
already knows about, and a teamfight is when all of it arrives at once: particle
systems and the dynamic light each effect asks for, ragdolls, breakable debris,
physics props, and decoding the snapshot that shows up sixty times a second.
That is the thing that looks like "calculating the whole map" and it is the only
part of it you can do something about.

So this module does two jobs:

* writes the convars that stop work the client would otherwise do, as an opt-in
  overlay on top of whichever profile you run (``--cpu-relief``). The values go
  into both ``autoexec.cfg`` and the ``gameinfo.gi`` ``ConVars`` block, so a mod
  manager rewriting ``video.txt`` cannot undo them.
* names the convars that look like they would help and cannot. OptiLock ships
  half a dozen ``ai_*`` ones; Valve's own Deadlock convar list flags every
  ``ai_*`` entry ``sv``, which means they are server-side and a client config
  cannot execute them at all. They are listed rather than silently dropped,
  because "I set ai_lod_auto_enabled" is exactly the kind of belief this project
  exists to correct.

The overlay is deliberately *not* the default: it is a real change to how the
game looks under load (cheaper effects, no ragdolls, no debris), and hiding that
behind a profile name would be the sort of surprise the rest of SpeedyLock avoids.
"""

from __future__ import annotations

from . import profiles

SIMULATION = "simulation"
EFFECTS = "effects"

GROUP_LABELS = (
    (SIMULATION, "Simulation, every tick"),
    (EFFECTS, "Effects, particles and debris"),
)

SUFFIX = "-cpu"


class Relief(object):
    """One convar the relief overlay writes."""

    __slots__ = ("name", "value", "group", "note")

    def __init__(self, name, value, group, note):
        self.name = name
        self.value = value
        self.group = group
        self.note = note

    def __repr__(self):
        return "Relief(%r, %r)" % (self.name, self.value)


RELIEF = (
    Relief(
        "cl_simulate_dormant_entities",
        "0",
        SIMULATION,
        "stop stepping entities the server has marked dormant",
    ),
    Relief(
        "cl_ragdoll_limit",
        "0",
        SIMULATION,
        "no ragdolls: each one is a simulated body",
    ),
    Relief(
        "func_break_max_pieces",
        "0",
        SIMULATION,
        "no debris from breakable props",
    ),
    Relief(
        "cl_phys_animated_hierarchy",
        "0",
        SIMULATION,
        "skip physics on animated prop hierarchies",
    ),
    Relief(
        "phys_multithreading_enabled",
        "1",
        SIMULATION,
        "keep VPhysics on job threads, off the main thread",
    ),
    Relief(
        "cl_parallel_readpacketentities",
        "1",
        SIMULATION,
        "decode snapshots on worker threads",
    ),
    Relief(
        "cl_aggregate_particles",
        "1",
        EFFECTS,
        "batch particle systems into shared work",
    ),
    Relief(
        "cl_particle_batch_mode",
        "1",
        EFFECTS,
        "batched particle draw/sim path",
    ),
    Relief(
        "cl_particle_fallback_base",
        "5",
        EFFECTS,
        "same fallback value the video profiles use",
    ),
    Relief(
        "cl_particle_fallback_multiplier",
        "5",
        EFFECTS,
        "same fallback multiplier the video profiles use",
    ),
    Relief(
        "cl_particle_sim_fallback_threshold_ms",
        "0",
        EFFECTS,
        "fall back to cheaper effects immediately",
    ),
    Relief(
        "r_citadel_disable_particle_lights",
        "1",
        EFFECTS,
        "no per-effect dynamic lights",
    ),
)

#: Convars that are commonly sold as CPU tweaks and cannot help here, with the
#: reason. Printed by ``speedy cpu`` so nobody has to take this on faith.
NOT_WRITTEN = (
    (
        "ai_lod_auto_enabled",
        "sv-flagged: AI runs on the server, so the client cannot execute this",
    ),
    (
        "ai_think_interval_lod_med",
        "sv-flagged (same reason); OptiLock ships it anyway",
    ),
    (
        "ai_think_interval_lod_very_low",
        "sv-flagged (same reason); OptiLock ships it anyway",
    ),
    (
        "ai_use_async_ragdoll_fixup",
        "sv-flagged (same reason)",
    ),
    (
        "g_ragdoll_important_maxcount",
        "game/server ragdoll cap; the client-side knob is cl_ragdoll_limit",
    ),
    (
        "cl_disable_ragdolls",
        "cheat-flagged, so it does nothing in a live match",
    ),
    (
        "cl_particle_simulate",
        "cheat-flagged, and it removes effects you need to read a fight",
    ),
    (
        "particle_cluster_nodraw",
        "saves work, but hides world effect clusters that telegraph abilities",
    ),
    (
        "cl_impacteffects",
        "removes bullet-impact feedback: that is information, not decoration",
    ),
    (
        "panorama_min_comp_layer_cache_cost",
        "exists in Deadlock but is undocumented; no guessed HUD value",
    ),
)

RELIEF_STEP = (
    "CPU relief does not make the server simulate less -- the other lanes are "
    "ticked on Valve's machines. It stops your client doing work for effects, "
    "bodies and props you are not looking at, and it is written to both "
    "autoexec.cfg and the gameinfo ConVars block so a manager cannot undo it."
)

_VALUES = {row.name: row.value for row in RELIEF}
_PAIRS = tuple((row.name, row.value) for row in RELIEF)


def names():
    return [row.name for row in RELIEF]


def values():
    return dict(_VALUES)


def by_group():
    """Rows in display order, grouped."""
    return [
        (label, [row for row in RELIEF if row.group == key])
        for key, label in GROUP_LABELS
    ]


def _without_relief(pairs):
    """Drop any relief convar the underlying profile already sets.

    The overlay owns these names outright. Appending a second definition would
    work -- ours is written last and wins -- but a managed block that defines the
    same convar twice is exactly the mess this tool cleans up for other configs.
    """
    return [(name, value) for name, value in pairs if name not in _VALUES]


def overlay(profile):
    """Layer the relief rows onto a copy of `profile`.

    Nothing is mutated: ``profiles.PROFILES`` is shared module state, so a
    caller asking for relief must not leave the plain profile changed for the
    next command in the same process.
    """
    return profiles.Profile(
        key=profile.key + SUFFIX,
        title=profile.title + " + CPU relief",
        blurb=profile.blurb,
        settings=_without_relief(profile.settings) + list(_PAIRS),
        launch_options=profile.launch_options,
        manual_steps=tuple(profile.manual_steps) + (RELIEF_STEP,),
        video=profile.video,
        gameinfo=_without_relief(profile.gameinfo) + list(_PAIRS),
    )


def is_relief_profile(key):
    """Whether a profile key recorded in a managed block carries the overlay."""
    return bool(key) and key.endswith(SUFFIX)


def base_key(key):
    """The plain profile key behind a ``-cpu`` overlay key."""
    if is_relief_profile(key):
        return key[: -len(SUFFIX)]
    return key


def explain():
    """The honest framing, as lines for the CLI."""
    return (
        "Your client renders and steps the entities it knows about. The rest of "
        "the map is simulated on Valve's servers, and no client convar changes "
        "that. What you can remove is the per-tick work for things you are not "
        "looking at: dormant entities, ragdolls, debris, particle systems and "
        "their lights, and snapshot decoding.",
        "The win shows up in teamfights, which is where that work spikes. If "
        "`speedy tune` says you are GPU-bound instead, this set will not help "
        "you -- cut pixels there, not simulation.",
        "This is opt-in because it is visible under load: cheaper effects, no "
        "ragdolls, no debris. `speedy uninstall` puts it back.",
    )
