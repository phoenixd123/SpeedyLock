"""Tests for the opt-in CPU relief overlay."""

import argparse
import contextlib
import io
import unittest

from speedylock import cli, config, convars, cpu, profiles, tune


class ReliefDataTests(unittest.TestCase):
    def test_every_row_is_a_writable_convar(self):
        for row in cpu.RELIEF:
            cvar = convars.get(row.name)
            self.assertIsNotNone(cvar, row.name)
            self.assertTrue(cvar.is_writable(), row.name)

    def test_names_are_unique(self):
        names = cpu.names()
        self.assertEqual(len(names), len(set(names)))

    def test_rows_carry_a_group_and_a_reason(self):
        labels = dict(cpu.GROUP_LABELS)
        for row in cpu.RELIEF:
            self.assertIn(row.group, labels, row.name)
            self.assertTrue(row.note, row.name)

    def test_grouping_covers_every_row_once(self):
        grouped = [row for _label, rows in cpu.by_group() for row in rows]
        self.assertEqual(len(grouped), len(cpu.RELIEF))

    def test_server_side_convars_are_not_written(self):
        written = set(cpu.names())
        for name in (
            "ai_lod_auto_enabled",
            "ai_think_interval_lod_med",
            "ai_think_interval_lod_very_low",
            "ai_use_async_ragdoll_fixup",
            "g_ragdoll_important_maxcount",
            "cl_disable_ragdolls",
        ):
            self.assertNotIn(name, written, name)

    def test_not_written_entries_are_not_duplicated_in_relief(self):
        written = set(cpu.names())
        for name, why in cpu.NOT_WRITTEN:
            self.assertNotIn(name, written, name)
            self.assertTrue(why, name)


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.base = profiles.get("balanced")

    def test_key_and_title_mark_the_overlay(self):
        layered = cpu.overlay(self.base)
        self.assertEqual(layered.key, "balanced-cpu")
        self.assertIn("CPU relief", layered.title)
        self.assertTrue(cpu.is_relief_profile(layered.key))
        self.assertEqual(cpu.base_key(layered.key), "balanced")

    def test_plain_key_is_not_a_relief_profile(self):
        self.assertFalse(cpu.is_relief_profile("balanced"))
        self.assertFalse(cpu.is_relief_profile(None))
        self.assertEqual(cpu.base_key("balanced"), "balanced")

    def test_base_profile_is_not_mutated(self):
        before_settings = tuple(self.base.settings)
        before_gameinfo = tuple(self.base.gameinfo)
        cpu.overlay(self.base)
        self.assertEqual(tuple(self.base.settings), before_settings)
        self.assertEqual(tuple(self.base.gameinfo), before_gameinfo)
        self.assertIs(profiles.get("balanced"), self.base)

    def test_overlay_is_idempotent(self):
        once = cpu.overlay(self.base)
        twice = cpu.overlay(once)
        self.assertEqual(once.settings, twice.settings)
        self.assertEqual(once.gameinfo, twice.gameinfo)

    def test_relief_rows_reach_both_files(self):
        layered = cpu.overlay(self.base)
        for target in (layered.settings, layered.gameinfo):
            values = dict(target)
            for name, value in cpu.values().items():
                self.assertEqual(values[name], value)

    def test_no_convar_is_defined_twice_after_overlay(self):
        layered = cpu.overlay(self.base)
        for target in (layered.settings, layered.gameinfo):
            names = [name for name, _value in target]
            self.assertEqual(len(names), len(set(names)))

    def test_relief_overrides_a_profile_that_sets_the_same_name(self):
        # potato already zeroes ragdolls; the overlay must own the name outright
        layered = cpu.overlay(profiles.get("potato"))
        names = [name for name, _value in layered.settings]
        self.assertEqual(names.count("cl_ragdoll_limit"), 1)
        self.assertEqual(dict(layered.settings)["cl_ragdoll_limit"], "0")

    def test_overlay_drops_optilock_values_it_replaces(self):
        layered = cpu.overlay(profiles.get("optilock"))
        values = dict(layered.gameinfo)
        # OptiLock sets this to -1; ours is last and wins, with no duplicate row
        self.assertEqual(values["cl_ragdoll_limit"], "0")

    def test_video_keys_are_untouched(self):
        layered = cpu.overlay(self.base)
        self.assertEqual(layered.video, self.base.video)

    def test_block_renders(self):
        layered = cpu.overlay(self.base)
        block = config.render_block(layered, fps_cap=141)
        self.assertIn('cl_simulate_dormant_entities "0"', block)
        self.assertIn('r_citadel_disable_particle_lights "1"', block)
        self.assertIn('fps_max "141"', block)

    def test_still_explains_that_the_server_is_untouched(self):
        text = " ".join(cpu.explain())
        self.assertIn("server", text)


class CliWiringTests(unittest.TestCase):
    def test_flag_is_opt_in(self):
        parser = cli.build_parser()
        self.assertTrue(parser.parse_args(["install", "--cpu-relief"]).cpu_relief)
        self.assertFalse(parser.parse_args(["install"]).cpu_relief)

    def test_cpu_command_is_registered(self):
        parser = cli.build_parser()
        self.assertIs(parser.parse_args(["cpu"]).func, cli.cmd_cpu)

    def test_cpu_command_reports_both_halves(self):
        args = argparse.Namespace(profile=None)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            cli.cmd_cpu(args)
        text = buffer.getvalue()
        self.assertIn("cl_simulate_dormant_entities", text)
        self.assertIn("ai_lod_auto_enabled", text)
        self.assertIn("--cpu-relief", text)

    def test_cpu_bound_recommendation_suggests_the_relief_set(self):
        result = {
            "verdict": "cpu",
            "ratio": 0.4,
            "cap": 120,
            "render_scale": None,
            "caps": {"stable": 120, "fast": 180, "tick": 120, "vrr": None, "refresh": None},
        }
        self.assertIn("--cpu-relief", " ".join(tune.advice(result)))
        self.assertIn("--cpu-relief", tune.install_command(result, "potato"))

    def test_gpu_bound_recommendation_does_not(self):
        result = {
            "verdict": "gpu",
            "ratio": 0.99,
            "cap": 120,
            "render_scale": 0.83,
            "caps": {"stable": 120, "fast": 180, "tick": 120, "vrr": None, "refresh": None},
        }
        self.assertNotIn("--cpu-relief", tune.install_command(result, "balanced"))


class HudReliefTests(unittest.TestCase):
    def test_hud_rows_are_present(self):
        values = cpu.values()
        self.assertEqual(values["fps_max_ui"], "30")
        self.assertEqual(values["citadel_damage_text_lifetime"], "0.75")
        self.assertEqual(values["citadel_healthbars_enabled"], "0")

    def test_hud_rows_are_grouped_as_hud(self):
        labels = dict(cpu.GROUP_LABELS)
        hud = [row.name for row in cpu.RELIEF if row.group == cpu.HUD]
        self.assertEqual(
            sorted(hud),
            ["citadel_damage_text_lifetime", "citadel_healthbars_enabled", "fps_max_ui"],
        )
        self.assertIn(cpu.HUD, labels)

    def test_grouping_includes_hud(self):
        keys = [label for label, _rows in cpu.by_group()]
        self.assertIn(dict(cpu.GROUP_LABELS)[cpu.HUD], keys)

    def test_only_healthbars_is_lossy(self):
        self.assertEqual(
            [row.name for row in cpu.RELIEF if row.lossy], ["citadel_healthbars_enabled"]
        )

    def test_hud_values_replace_the_profile_value(self):
        layered = cpu.overlay(profiles.get("balanced"))
        names = [name for name, _value in layered.settings]
        self.assertEqual(names.count("fps_max_ui"), 1)
        self.assertEqual(dict(layered.settings)["fps_max_ui"], "30")
        self.assertEqual(dict(layered.gameinfo)["fps_max_ui"], "30")

    def test_lossy_row_is_explained_in_the_steps(self):
        layered = cpu.overlay(profiles.get("balanced"))
        self.assertIn("citadel_healthbars_enabled", " ".join(layered.manual_steps))

    def test_cpu_command_marks_the_lossy_row(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            cli.cmd_cpu(argparse.Namespace(profile=None))
        text = buffer.getvalue()
        self.assertIn("citadel_healthbars_enabled", text)
        self.assertIn("(costs information)", text)
        self.assertIn("fps_max_ui", text)


class ProfileKeyTests(unittest.TestCase):
    def test_relief_key_resolves_to_the_overlay(self):
        layered = profiles.get("balanced-cpu")
        self.assertEqual(layered.key, "balanced-cpu")
        self.assertEqual(
            dict(layered.settings)["cl_simulate_dormant_entities"], "0"
        )
        self.assertEqual(dict(layered.settings)["fps_max_ui"], "30")

    def test_every_profile_has_a_relief_key(self):
        for key in list(profiles.PROFILES):
            self.assertIn(key + cpu.SUFFIX, profiles.names())

    def test_plain_keys_still_resolve(self):
        for key in ("potato", "balanced", "quality", "optilock"):
            self.assertEqual(profiles.get(key).key, key)

    def test_double_suffix_is_rejected(self):
        with self.assertRaises(KeyError):
            profiles.get("balanced-cpu-cpu")

    def test_unknown_key_still_raises(self):
        with self.assertRaises(KeyError):
            profiles.get("balanced-gpu")

    def test_overlay_of_an_overlay_is_identity(self):
        layered = profiles.get("balanced-cpu")
        self.assertIs(cpu.overlay(layered), layered)

    def test_resolving_the_relief_key_does_not_mutate_the_base(self):
        before = tuple(profiles.get("potato").settings)
        profiles.get("potato-cpu")
        self.assertEqual(tuple(profiles.get("potato").settings), before)

    def test_doctor_key_round_trips_through_install(self):
        block = config.render_block(
            cpu.overlay(profiles.get("balanced")), fps_cap=141
        )
        printed = config.block_profile(block)
        self.assertEqual(printed, "balanced-cpu")
        pasted_back = profiles.get(printed)
        self.assertEqual(pasted_back.key, printed)
        self.assertEqual(dict(pasted_back.settings)["fps_max_ui"], "30")

    def test_cli_accepts_the_relief_key(self):
        parser = cli.build_parser()
        args = parser.parse_args(["install", "--profile", "balanced-cpu"])
        self.assertEqual(args.profile, "balanced-cpu")
        self.assertFalse(args.cpu_relief)

    def test_flag_and_key_together_agree(self):
        by_key = profiles.get("balanced-cpu")
        by_flag = cpu.overlay(profiles.get("balanced"))
        self.assertEqual(by_key.key, by_flag.key)
        self.assertEqual(by_key.settings, by_flag.settings)
        self.assertEqual(by_key.gameinfo, by_flag.gameinfo)


if __name__ == "__main__":
    unittest.main()
