import os
import tempfile
import unittest
from pathlib import Path

from speedylock import config, profiles


def make_profile(settings):
    return profiles.Profile(
        key="probe",
        title="Probe",
        blurb="synthetic profile for tests",
        settings=settings,
        launch_options=(),
        manual_steps=(),
    )


class RenderTests(unittest.TestCase):
    def test_renders_profile_and_substitutes_cap(self):
        block = config.render_block(profiles.get("balanced"), fps_cap=144)
        self.assertTrue(block.startswith(config.BEGIN_PREFIX))
        self.assertIn('fps_max "144"', block)
        self.assertTrue(block.rstrip().endswith(config.END_LINE))

    def test_refuses_cheat_convar(self):
        profile = make_profile([("r_drawothermodels", "2")])
        with self.assertRaises(config.ConfigError):
            config.render_block(profile, experimental=True)

    def test_refuses_unknown_convar(self):
        profile = make_profile([("mat_queue_mode", "2")])
        with self.assertRaises(config.ConfigError):
            config.render_block(profile, experimental=True)

    def test_refuses_convar_missing_from_knowledge_base(self):
        profile = make_profile([("not_a_real_convar", "1")])
        with self.assertRaises(config.ConfigError):
            config.render_block(profile)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self._tmp.name) / "cfg"
        self.cfg.mkdir(parents=True)
        self.autoexec = self.cfg / "autoexec.cfg"

    def tearDown(self):
        self._tmp.cleanup()

    def write_user_config(self, text):
        with open(str(self.autoexec), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

    def read(self):
        with open(str(self.autoexec), "r", encoding="utf-8") as fh:
            return fh.read()

    def test_install_creates_file(self):
        result = config.install(self.cfg, profiles.get("balanced"))
        self.assertTrue(result.changed)
        self.assertTrue(self.autoexec.exists())
        self.assertIn(config.END_LINE, self.read())

    def test_install_preserves_user_content_above_block(self):
        self.write_user_config('// my binds\nbind f1 "citadel_hud_visible 0"\n')
        config.install(self.cfg, profiles.get("balanced"))
        text = self.read()
        self.assertIn("// my binds", text)
        self.assertIn('bind f1 "citadel_hud_visible 0"', text)
        self.assertLess(text.index("// my binds"), text.index(config.BEGIN_PREFIX))

    def test_install_is_idempotent(self):
        config.install(self.cfg, profiles.get("balanced"))
        first = self.read()
        result = config.install(self.cfg, profiles.get("balanced"))
        self.assertFalse(result.changed)
        self.assertEqual(first, self.read())
        self.assertEqual(self.read().count(config.BEGIN_PREFIX), 1)

    def test_switching_profile_replaces_block(self):
        config.install(self.cfg, profiles.get("potato"))
        config.install(self.cfg, profiles.get("quality"))
        text = self.read()
        self.assertEqual(text.count(config.BEGIN_PREFIX), 1)
        self.assertIn("profile: quality", text)
        self.assertNotIn("cl_ragdoll_limit", text)

    def test_fps_cap_is_written(self):
        config.install(self.cfg, profiles.get("balanced"), fps_cap=141)
        self.assertIn('fps_max "141"', self.read())

    def test_backup_is_taken_before_overwriting(self):
        self.write_user_config("// precious\n")
        result = config.install(self.cfg, profiles.get("balanced"))
        self.assertIsNotNone(result.backup)
        with open(str(result.backup), "r", encoding="utf-8") as fh:
            self.assertIn("// precious", fh.read())

    def test_backup_does_not_clobber_existing_backups(self):
        self.write_user_config("// one\n")
        first = config.install(self.cfg, profiles.get("balanced"), stamp="20260101-000000")
        self.write_user_config("// two\n")
        second = config.install(self.cfg, profiles.get("potato"), stamp="20260101-000000")
        self.assertNotEqual(first.backup, second.backup)
        self.assertTrue(first.backup.exists())
        self.assertTrue(second.backup.exists())

    def test_restore_original_returns_the_first_backup(self):
        # Two installs leave two backups: the original, then SpeedyLock's own
        # output. Uninstall must restore the original, not the newest file.
        self.write_user_config("// v1\n")
        config.install(self.cfg, profiles.get("balanced"))
        config.install(self.cfg, profiles.get("potato"))
        restored = config.restore_original(self.cfg, "autoexec", ".cfg")
        self.assertIsNotNone(restored)
        _, text = restored
        self.assertEqual(text, "// v1\n")

    def test_restore_original_without_backups_returns_none(self):
        self.assertIsNone(config.restore_original(self.cfg, "video", ".txt"))

    def test_dry_run_writes_nothing(self):
        result = config.install(self.cfg, profiles.get("balanced"), dry_run=True)
        self.assertFalse(result.changed)
        self.assertFalse(self.autoexec.exists())

    def test_uninstall_restores_user_content(self):
        self.write_user_config('// mine\nbind f1 "citadel_hud_visible 0"\n')
        config.install(self.cfg, profiles.get("balanced"))
        result = config.uninstall(self.cfg)
        self.assertTrue(result.changed)
        text = self.read()
        self.assertNotIn(config.BEGIN_PREFIX, text)
        self.assertIn('bind f1 "citadel_hud_visible 0"', text)

    def test_uninstall_removes_file_when_only_the_block_was_there(self):
        config.install(self.cfg, profiles.get("balanced"))
        config.uninstall(self.cfg)
        self.assertFalse(self.autoexec.exists())

    def test_uninstall_without_block_is_a_noop(self):
        self.write_user_config("// untouched\n")
        result = config.uninstall(self.cfg)
        self.assertFalse(result.changed)
        self.assertEqual(self.read(), "// untouched\n")

    def test_installed_profile_reports_current_key(self):
        config.install(self.cfg, profiles.get("potato"))
        self.assertEqual(config.installed_profile(self.cfg), "potato")

    def test_unterminated_block_is_refused(self):
        self.write_user_config(config.BEGIN_PREFIX + " | profile: balanced\nfps_max \"0\"\n")
        with self.assertRaises(config.ConfigError):
            config.install(self.cfg, profiles.get("balanced"))
        # The file must be left exactly as it was.
        self.assertIn('fps_max "0"', self.read())

    def test_duplicate_blocks_are_refused(self):
        self.write_user_config(
            config.BEGIN_PREFIX
            + " | profile: balanced\n"
            + config.END_LINE
            + "\n"
            + config.BEGIN_PREFIX
            + " | profile: potato\n"
            + config.END_LINE
            + "\n"
        )
        with self.assertRaises(config.ConfigError):
            config.install(self.cfg, profiles.get("balanced"))

    def test_created_file_has_no_carriage_returns(self):
        config.install(self.cfg, profiles.get("balanced"))
        with open(str(self.autoexec), "rb") as fh:
            self.assertNotIn(b"\r\n", fh.read())

    def test_convar_lines_skips_comments(self):
        self.write_user_config('// fps_max "999"\nfps_max "120"\n')
        lines = dict(config.convar_lines(self.read()))
        self.assertEqual(lines.get("fps_max"), "120")


if __name__ == "__main__":
    unittest.main()
