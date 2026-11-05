"""Tests for the video.txt and gameinfo.gi management layer."""

import tempfile
import unittest
from pathlib import Path

from speedylock import gamefiles


GAMEINFO = """\
"GameInfo"
{
\tgame\t\t"citadel"

\tConVars
\t{
\t\t// vanilla convar
\t\tvis_enable\t\t"0"
\t\tr_aspectratio\t\t"2.0"
\t}

\tOther
\t{
\t\tKey\t\t"Value"
\t}
}
"""

VIDEO = """\
"video_config"
{
\t"deviceid"		"ABC123"
\t"setting.fullscreen"		"1"
\t"setting.r_shadows"		"3"
\t"setting.monitor_index"		"1"
}
"""


class VideoMergeTests(unittest.TestCase):
    def test_updates_existing_key_in_place(self):
        out = gamefiles.merge_video(VIDEO, {"setting.r_shadows": "0"})
        self.assertIn('"setting.r_shadows"\t\t"0"', out)
        self.assertNotIn('"setting.r_shadows"\t\t"3"', out)

    def test_preserves_device_id_and_display_preferences(self):
        out = gamefiles.merge_video(VIDEO, {"setting.r_shadows": "0"})
        self.assertIn('"deviceid"', out)
        self.assertIn('"ABC123"', out)
        self.assertIn('"setting.fullscreen"\t\t"1"', out)
        self.assertIn('"setting.monitor_index"\t\t"1"', out)

    def test_inserts_new_keys_before_the_closing_brace(self):
        out = gamefiles.merge_video(VIDEO, {"setting.r_area_lights": "0"})
        self.assertIn('"setting.r_area_lights"', out)
        self.assertLess(out.index("setting.r_area_lights"), out.rindex("}"))

    def test_is_idempotent(self):
        once = gamefiles.merge_video(VIDEO, {"setting.r_shadows": "0"})
        twice = gamefiles.merge_video(once, {"setting.r_shadows": "0"})
        self.assertEqual(once, twice)
        self.assertEqual(twice.count('"setting.r_shadows"'), 1)

    def test_brace_balance_is_unchanged(self):
        out = gamefiles.merge_video(VIDEO, {"setting.r_area_lights": "0"})
        self.assertEqual(gamefiles.brace_delta(out), gamefiles.brace_delta(VIDEO))

    def test_bare_key_list_without_wrapper_is_appended(self):
        bare = '"setting.r_shadows"\t\t"3"\n'
        out = gamefiles.merge_video(bare, {"setting.r_shadows": "0"})
        self.assertIn('"setting.r_shadows"\t\t"0"', out)

    def test_empty_file_gets_a_wrapper(self):
        out = gamefiles.merge_video("", {"setting.r_shadows": "0"})
        self.assertIn('"video_config"', out)
        self.assertIn("{", out)
        self.assertIn("}", out)
        self.assertEqual(gamefiles.brace_delta(out), 0)

    def test_refuses_to_overwrite_a_display_setting(self):
        with self.assertRaises(gamefiles.GameFileError):
            gamefiles.merge_video(VIDEO, {"setting.monitor_index": "0"})
        with self.assertRaises(gamefiles.GameFileError):
            gamefiles.merge_video(VIDEO, {"deviceid": "nope"})
        with self.assertRaises(gamefiles.GameFileError):
            gamefiles.merge_video(VIDEO, {"setting.r_fullscreen_gamma": "9"})

    def test_render_scale_needs_an_explicit_opt_in(self):
        with self.assertRaises(gamefiles.GameFileError):
            gamefiles.merge_video(VIDEO, {"setting.mat_viewportscale": "0.85"})
        out = gamefiles.merge_video(
            VIDEO,
            {"setting.mat_viewportscale": "0.85"},
            allow_protected=("setting.mat_viewportscale",),
        )
        self.assertIn('"setting.mat_viewportscale"\t\t"0.85"', out)

    def test_refuses_values_with_quotes(self):
        with self.assertRaises(gamefiles.GameFileError):
            gamefiles.merge_video(VIDEO, {"setting.r_shadows": '0"\n"evil'})

    def test_reads_back_key_value_pairs(self):
        pairs = dict(gamefiles.video_key_lines(VIDEO))
        self.assertEqual(pairs["deviceid"], "ABC123")
        self.assertEqual(pairs["setting.r_shadows"], "3")


class GameinfoTests(unittest.TestCase):
    def test_finds_the_convars_block(self):
        span = gamefiles.find_convars_block(GAMEINFO)
        self.assertIsNotNone(span)
        header, open_line, close_line = span
        self.assertLess(header, open_line)
        self.assertLess(open_line, close_line)

    def test_returns_none_without_a_convars_block(self):
        self.assertIsNone(gamefiles.find_convars_block('"GameInfo"\n{\n}\n'))

    def test_injects_into_the_existing_block(self):
        out = gamefiles.inject_gameinfo(GAMEINFO, [("vis_enable", "1")], "balanced")
        self.assertTrue(gamefiles.has_managed_convars(out))

    def test_injection_keeps_vanilla_convars_and_other_blocks(self):
        out = gamefiles.inject_gameinfo(GAMEINFO, [("vis_enable", "1")], "balanced")
        self.assertIn('r_aspectratio\t\t"2.0"', out)
        self.assertIn('Other', out)
        self.assertIn('Key\t\t"Value"', out)

    def test_injection_does_not_break_braces(self):
        out = gamefiles.inject_gameinfo(GAMEINFO, [("vis_enable", "1")], "balanced")
        self.assertEqual(gamefiles.brace_delta(out), gamefiles.brace_delta(GAMEINFO))

    def test_injection_is_idempotent(self):
        once = gamefiles.inject_gameinfo(GAMEINFO, [("vis_enable", "1")], "balanced")
        twice = gamefiles.inject_gameinfo(once, [("vis_enable", "1")], "balanced")
        self.assertEqual(once, twice)
        self.assertEqual(twice.count(gamefiles.MARK_BEGIN), 1)

    def test_switching_profile_replaces_the_block(self):
        once = gamefiles.inject_gameinfo(GAMEINFO, [("vis_enable", "1")], "potato")
        twice = gamefiles.inject_gameinfo(once, [("vis_enable", "1")], "quality")
        self.assertIn("profile: quality", twice)
        self.assertNotIn("profile: potato", twice)

    def test_strip_removes_the_managed_block(self):
        injected = gamefiles.inject_gameinfo(GAMEINFO, [("vis_enable", "1")], "balanced")
        self.assertEqual(gamefiles.strip_gameinfo(injected), GAMEINFO)

    def test_injection_lands_inside_the_convars_block(self):
        out = gamefiles.inject_gameinfo(GAMEINFO, [("vis_enable", "1")], "balanced")
        self.assertGreater(out.index(gamefiles.MARK_BEGIN), out.index("ConVars"))
        self.assertLess(out.index(gamefiles.MARK_END), out.index("Other"))

    def test_refuses_when_there_is_no_convars_block(self):
        with self.assertRaises(gamefiles.GameFileError):
            gamefiles.inject_gameinfo('"GameInfo"\n{\n}\n', [("vis_enable", "1")], "p")

    def test_comments_and_strings_do_not_confuse_brace_counting(self):
        tricky = 'a "{" b\n// }}}}\nc\n'
        self.assertEqual(gamefiles.brace_delta(tricky), 0)

    def test_reads_convars_inside_the_block_only(self):
        pairs = dict(gamefiles.convars_in_block(GAMEINFO))
        self.assertEqual(pairs.get("r_aspectratio"), "2.0")
        self.assertEqual(pairs.get("vis_enable"), "0")


class LocateTests(unittest.TestCase):
    def test_finds_game_and_userdata_video_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            steam = Path(tmp) / "Steam"
            install = steam / "steamapps" / "common" / "Deadlock"
            (install / "game" / "citadel" / "cfg").mkdir(parents=True)
            userdata = steam / "userdata" / "12345" / "1422450" / "local" / "cfg"
            userdata.mkdir(parents=True)

            (install / "game" / "citadel" / "cfg" / "video.txt").write_text(VIDEO)
            (userdata / "video.txt").write_text(VIDEO)

            found = gamefiles.find_video_files(install)
            self.assertEqual(len(found), 2)
            self.assertTrue(all(path.name == "video.txt" for path in found))

    def test_returns_empty_when_nothing_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / "Deadlock"
            (install / "game" / "citadel").mkdir(parents=True)
            self.assertEqual(gamefiles.find_video_files(install), [])

    def test_gameinfo_path(self):
        install = Path("/games/Deadlock")
        self.assertEqual(
            gamefiles.find_gameinfo(install),
            Path("/games/Deadlock/game/citadel/gameinfo.gi"),
        )


if __name__ == "__main__":
    unittest.main()
