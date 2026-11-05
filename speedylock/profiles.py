"""SpeedyLock profiles.

Three tiers. The naming problem this solves: "potato configs" and
"competitive configs" are usually shipped as two separate downloads with
overlapping, contradictory instructions, and neither one lets you keep a
vanilla-looking game.

* ``potato``   -- the Potato Lock / OptiLock Ultra Potato idea: strip
                  everything. For integrated GPUs and anyone under 60fps.
* ``balanced`` -- the default, and the merge: OptiLock's competitive tier,
                  which keeps hero silhouettes and UI shadows for readability
                  while removing the expensive lighting. Best frames-per-clarity
                  on mid-range hardware.
* ``quality``  -- what neither community config offers: **zero visual
                  change**. Only input, latency and UI overhead move.

Each profile drives three files:

``settings``      written to ``autoexec.cfg``
``video``         ``setting.*`` keys merged into ``video.txt``
``gameinfo``      convars merged into the ``ConVars`` block of ``gameinfo.gi``

Every autoexec setting is resolved against ``speedylock.convars`` at generation
time and the write is refused if the convar is not writable. Display and
hardware keys (resolution, monitor, gamma, device id) are never written at all
-- see ``gamefiles.PROTECTED_VIDEO_KEYS``.

``{fps_cap}`` is substituted at install time from ``--fps-cap``.
"""

from __future__ import annotations

from . import convars, optilock

# The imported vocabulary has to be in the knowledge base before any profile
# below references it, or the writer would refuse every one of its convars.
optilock.apply_knowledge(convars)


class Profile(object):
    __slots__ = (
        "key",
        "title",
        "blurb",
        "settings",
        "launch_options",
        "manual_steps",
        "video",
        "gameinfo",
    )

    def __init__(
        self,
        key,
        title,
        blurb,
        settings,
        launch_options,
        manual_steps,
        video=None,
        gameinfo=None,
    ):
        self.key = key
        self.title = title
        self.blurb = blurb
        self.settings = tuple(settings)
        self.launch_options = tuple(launch_options)
        self.manual_steps = tuple(manual_steps)
        self.video = dict(video or {})
        self.gameinfo = tuple(gameinfo or ())

    def __repr__(self):
        return "Profile(%r)" % self.key


_COMMON_LAUNCH = ("-novid", "-console", "-exec", "autoexec")

# Latency only. Safe for every tier, including "do not touch my graphics".
_LATENCY_VIDEO = {
    "setting.mat_vsync": "0",
    "setting.r_low_latency": "1",
    "setting.fps_max": "{fps_cap}",
}

# The expensive lighting and post-processing. Derived from the documented
# setting.* surface; these are the keys OptiLock's competitive tier turns down,
# minus everything that is actually a display preference.
_COMPETITIVE_VIDEO = {
    # Shadows: the single largest GPU cost in Deadlock.
    "setting.r_shadows": "0",
    "setting.r_citadel_shadow_quality": "0",
    "setting.r_citadel_distancefield_shadows": "false",
    "setting.csm_max_shadow_dist_override": "0",
    "setting.csm_max_num_cascades_override": "0",
    "setting.csm_viewmodel_shadows": "0",
    "setting.lb_enable_shadow_casting": "false",
    "setting.lb_shadow_texture_width_override": "0",
    "setting.lb_shadow_texture_height_override": "0",
    "setting.r_screen_space_shadows": "false",
    # Ambient occlusion and fog.
    "setting.r_citadel_ssao": "0",
    "setting.r_citadel_ssao_quality": "0",
    "setting.r_citadel_distancefield_ao_quality": "0",
    "setting.r_citadel_fog_quality": "0",
    "setting.volume_fog_width": "0",
    "setting.volume_fog_height": "0",
    "setting.volume_fog_depth": "0",
    # Lighting extras.
    "setting.r_area_lights": "0",
    "setting.r_arealights": "false",
    "setting.r_citadel_distancefield_reflections": "false",
    "setting.r_distancefield_enable": "false",
    "setting.r_citadel_mboit": "false",
    "setting.shaderquality": "0",
    "setting.r_displacement_mapping": "0",
    # Post-processing.
    "setting.r_effects_bloom": "false",
    "setting.r_post_bloom": "false",
    "setting.r_depth_of_field": "false",
    "setting.r_citadel_motion_blur": "0",
    "setting.r_reduce_flash": "1",
    # Particles.
    "setting.r_particle_max_detail_level": "0",
    "setting.r_particle_shadows": "0",
    "setting.r_particle_cables_cast_shadows": "0",
    "setting.r_particle_depth_feathering": "false",
    "setting.r_citadel_half_res_noisy_effects": "true",
    "setting.cl_particle_fallback_base": "5",
    "setting.cl_particle_fallback_multiplier": "5",
    # Resolution and rendering detail.
    "setting.r_citadel_antialiasing": "0",
    "setting.r_citadel_upscaling": "0",
    "setting.r_dashboard_render_quality": "0",
    "setting.r_render_portals": "2",
    "setting.r_env_map_uses_height_map": "0",
    # Engine quality tiers.
    "setting.cpu_level": "1",
    "setting.mem_level": "1",
    "setting.gpu_level": "2",
}

# Kept on in every tier because it is what makes enemies readable at distance.
_READABILITY_VIDEO = {
    "setting.r_citadel_outlines": "1",
}


def _video(*layers):
    merged = {}
    for layer in layers:
        merged.update(layer)
    return merged


PROFILES = {
    "potato": Profile(
        key="potato",
        title="Potato",
        blurb="Lowest possible cost. Maximum average FPS; visuals sacrificed.",
        settings=[
            ("fps_max", "{fps_cap}"),
            ("fps_max_ui", "30"),
            ("cl_ragdoll_limit", "0"),
            ("func_break_max_pieces", "0"),
            ("engine_no_focus_sleep", "100"),
        ],
        launch_options=_COMMON_LAUNCH + ("-high", "-dx11"),
        manual_steps=[
            "In Settings > Video, set the preset to the absolute lowest value "
            "so the menu and the file agree.",
            "If you need more, lower render resolution scale to 50% -- that is "
            "the only lever left that matters at this point.",
            "-dx11 is included because Vulkan is slower on some older GPUs. If "
            "your card handles Vulkan well, remove it.",
            "Textures stay at gpu_mem_level 1: dropping to 0 makes the game "
            "unreadable and barely helps.",
            "r_texture_stream_mip_bias is 8 here, which is past the documented "
            "threshold of 4 and needs the Sinner's Light fix VPK (OptiLock's "
            "Essential Fixes, GPL-3.0) or Sinner's light will render wrong. "
            "Drop the key to 4 if you would rather not install a VPK.",
        ],
        video=_video(
            _LATENCY_VIDEO,
            _COMPETITIVE_VIDEO,
            _READABILITY_VIDEO,
            {
                "setting.gpu_mem_level": "1",
                "setting.r_texture_stream_mip_bias": "8",
            },
        ),
        gameinfo=[("vis_enable", "1")],
    ),
    "balanced": Profile(
        key="balanced",
        title="Balanced",
        blurb="Default. Competitive clarity, steady frametimes, no gutted visuals.",
        settings=[
            ("fps_max", "{fps_cap}"),
            ("fps_max_ui", "60"),
            ("cl_input_enable_raw_keyboard", "1"),
            ("engine_low_latency_sleep_after_client_tick", "1"),
            ("cl_interp_ratio", "1"),
            ("cl_updaterate", "60"),
            ("snd_mixahead", "0.025"),
        ],
        launch_options=_COMMON_LAUNCH,
        manual_steps=[
            "Run `speedy bench <export.csv>` and use the reported stable cap "
            "with --fps-cap. That is the biggest single win available.",
            "Hero outlines stay enabled. They are cheap and they are how you "
            "spot people at range.",
            "Disable VSync in the menu as well as here, and use your GPU "
            "driver's low-latency mode.",
        ],
        video=_video(
            _LATENCY_VIDEO,
            _COMPETITIVE_VIDEO,
            _READABILITY_VIDEO,
            {
                "setting.gpu_mem_level": "1",
                "setting.r_texture_stream_mip_bias": "4",
            },
        ),
        gameinfo=[("vis_enable", "1")],
    ),
    "quality": Profile(
        key="quality",
        title="Quality",
        blurb="Looks identical to vanilla. Only latency and UI overhead change.",
        settings=[
            ("fps_max", "{fps_cap}"),
            ("fps_max_ui", "60"),
            ("cl_input_enable_raw_keyboard", "1"),
            ("engine_low_latency_sleep_after_client_tick", "1"),
        ],
        launch_options=_COMMON_LAUNCH,
        manual_steps=[
            "No visual key is written. Your video settings menu stays in charge.",
            "If frametime stability still bothers you, use --fps-cap with a "
            "value from `speedy bench`.",
        ],
        video=dict(_LATENCY_VIDEO),
        gameinfo=[("vis_enable", "1")],
    ),
}

DEFAULT_PROFILE = "balanced"


# ------------------------------------------------------- OptiLock-derived tiers

# These profiles carry OptiLock's real ConVars block (417 entries, extracted from
# its shipped gameinfo.gi) instead of a hand-written shortlist. That is the whole
# point of importing it: breadth we could not justify inventing ourselves.
#
# What stays SpeedyLock's:
#   * the merge, so a patch or another config cannot be silently destroyed
#   * display keys, which are never written whatever the source says
#   * {fps_cap}, so `speedy bench` still drives the cap
#
# The full block goes into gameinfo.gi (as OptiLock does) rather than autoexec,
# because 417 lines of `exec` at startup is both slower and noisier. Only the
# handful of convars that must apply at runtime go to autoexec.

_RUNTIME_CONVARS = frozenset(
    [
        "fps_max",
        "fps_max_ui",
        "cl_interp_ratio",
        "cl_updaterate",
        "cl_input_enable_raw_keyboard",
        "engine_low_latency_sleep_after_client_tick",
        "cl_ragdoll_limit",
        "func_break_max_pieces",
        "engine_no_focus_sleep",
        "snd_mixahead",
    ]
)

_OPTILOCK_STEPS = (
    "Do NOT hand-replace gameinfo.gi or video.txt as OptiLock's instructions "
    "say. SpeedyLock merges the same values in place and leaves your FOV, "
    "PGIVersion, resolution and device id alone.",
    "These values come from OptiLock (GPL-3.0). `speedy convar <name>` shows "
    "where each one came from.",
    "If a patch replaces gameinfo.gi, just run `speedy install` again; nothing "
    "needs re-downloading.",
)


def _optilock_profile(key, tier, title, blurb, steps):
    pairs = optilock.resolve(tier)

    # A third-party config does not get to widen SpeedyLock's own rules. Anything
    # the knowledge base refuses to write is dropped here, so the profile data is
    # clean at the source instead of relying on a later filter. OptiLock's
    # cl_resend 15 is the one casualty, and it deserves to be: a 15 second
    # retransmit window is not something to inherit silently.
    writable = [(name, value) for name, value in pairs if convars.is_writable(name)]

    runtime = [
        (name, value) for name, value in writable if name in _RUNTIME_CONVARS
    ]
    if not any(name == "fps_max" for name, _ in runtime):
        runtime.insert(0, ("fps_max", "{fps_cap}"))

    gameinfo = [
        (name, "{fps_cap}" if name == "fps_max" else value)
        for name, value in writable
    ]
    if not any(name == "fps_max" for name, _ in gameinfo):
        # OptiLock does not set fps_max in its ConVars block at all; the cap lives
        # only in video.txt there. Add it so --fps-cap takes effect either way.
        gameinfo.insert(0, ("fps_max", "{fps_cap}"))
    video = optilock.resolve_video(tier)
    video["setting.mat_vsync"] = "0"
    video["setting.r_low_latency"] = "1"
    video["setting.fps_max"] = "{fps_cap}"
    return Profile(
        key=key,
        title=title,
        blurb=blurb,
        settings=runtime,
        launch_options=_COMMON_LAUNCH,
        manual_steps=tuple(steps) + _OPTILOCK_STEPS,
        video=video,
        gameinfo=gameinfo,
    )


PROFILES.update(
    {
        "optilock": _optilock_profile(
            "optilock",
            None,
            "OptiLock (imported)",
            "OptiLock's Recommended config, merged instead of replacing your files.",
            ("OptiLock's own competitive tier. Best starting point for mid-range hardware.",),
        ),
        "optilock-potato": _optilock_profile(
            "optilock-potato",
            "optilock-potato",
            "OptiLock Potato (imported)",
            "OptiLock's Potato config: shorter farz, no decals, no post-processing.",
            ("Shorter draw distance is the main difference from the tier above.",),
        ),
        "optilock-ultra": _optilock_profile(
            "optilock-ultra",
            "optilock-ultra",
            "OptiLock Ultra Potato (imported)",
            "OptiLock's Ultra Potato: 7000 farz and 100 map extents.",
            (
                "Map extents drop to 100, which visibly shrinks the world. Try the "
                "Potato tier first.",
                "Texture mip bias is 8; that needs the Sinner's Light fix VPK.",
            ),
        ),
        "optilock-community": _optilock_profile(
            "optilock-community",
            "optilock-community",
            "OptiLock Community (imported)",
            "OptiLock's Community config: gentler values, fewer convars.",
            ("This tier omits ~100 convars the other three set. It is the least aggressive.",),
        ),
    }
)


def get(key):
    """Look up a profile by key, raising a helpful error for typos."""
    try:
        return PROFILES[key]
    except KeyError:
        raise KeyError(
            "unknown profile %r (choose from: %s)" % (key, ", ".join(sorted(PROFILES)))
        )


def names():
    return sorted(PROFILES)


def chooser_order():
    """Order used when explaining the profiles to a human."""
    return [
        "potato",
        "balanced",
        "quality",
        "optilock-community",
        "optilock-potato",
        "optilock",
        "optilock-ultra",
    ]
