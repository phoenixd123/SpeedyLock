"""Tests for the 1.0 release bundle."""

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from speedylock import cli, cpu, profiles, release


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.built = release.build(self.out, profiles.get("balanced"), fps_cap=141)

    def tearDown(self):
        self.tmp.cleanup()

    def test_directory_is_named_for_the_version(self):
        self.assertEqual(self.built.directory.name, "speedylock-1.0.0")

    def test_core_files_present(self):
        for name in (
            "README.md",
            "DOCUMENTATION.md",
            "LICENSE.md",
            "CREDITS.md",
            "autoexec.cfg",
            "convars-block.txt",
            "mod-interchange.json",
            "install.py",
            "install.bat",
            "install.sh",
            "uninstall.bat",
            "speedy.py",
            "release-manifest.json",
            "speedylock/cli.py",
            "speedylock/cpu.py",
        ):
            self.assertTrue((self.built.directory / name).is_file(), name)

    def test_manifest_verifies(self):
        self.assertEqual(release.verify(self.built.directory), [])

    def test_manifest_covers_every_file(self):
        manifest = json.loads(
            (self.built.directory / "release-manifest.json").read_text(encoding="utf-8")
        )
        listed = {entry["path"] for entry in manifest["files"]}
        actual = {
            path.relative_to(self.built.directory).as_posix()
            for path in self.built.directory.rglob("*")
            if path.is_file()
        }
        self.assertEqual(listed | {"release-manifest.json"}, actual)

    def test_manifest_records_the_profile(self):
        manifest = json.loads(
            (self.built.directory / "release-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["profile"], "balanced")
        self.assertEqual(manifest["fps_cap"], 141)
        self.assertEqual(manifest["interchange"]["format"], "deadlock-mod-interchange")

    def test_verify_detects_tampering(self):
        target = self.built.directory / "autoexec.cfg"
        target.write_text(target.read_text(encoding="utf-8") + 'sv_cheats "1"\n', encoding="utf-8")
        problems = release.verify(self.built.directory)
        self.assertTrue(any("autoexec.cfg" in problem for problem in problems), problems)

    def test_interchange_is_valid_and_vpkless(self):
        document = json.loads(
            (self.built.directory / "mod-interchange.json").read_text(encoding="utf-8")
        )
        self.assertEqual(document["format"], "deadlock-mod-interchange")
        self.assertEqual(document["version"], 1)
        self.assertEqual(document["mods"], [])
        self.assertTrue(document["warnings"])
        profile = document["profiles"][0]
        self.assertEqual(profile["key"], "speedylock-balanced")
        self.assertTrue(profile["enabled"])
        self.assertEqual(
            profile["autoexec"], release.commands_for(profiles.get("balanced"), fps_cap=141)
        )

    def test_autoexec_matches_the_interchange_commands(self):
        lines = (self.built.directory / "autoexec.cfg").read_text(encoding="utf-8").splitlines()
        document = json.loads(
            (self.built.directory / "mod-interchange.json").read_text(encoding="utf-8")
        )
        self.assertEqual(lines, document["profiles"][0]["autoexec"])
        self.assertIn('fps_max "141"', lines)

    def test_convars_block_carries_every_applied_convar(self):
        text = (self.built.directory / "convars-block.txt").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("ConVars\n{"))
        self.assertTrue(text.rstrip().endswith("}"))
        self.assertIn('"fps_max"\t"141"', text)
        self.assertIn('"vis_enable"\t"1"', text)
        self.assertIn('"cl_interp_ratio"\t"1"', text)

    def test_no_display_or_hardware_key_is_shipped(self):
        for name in ("autoexec.cfg", "convars-block.txt"):
            text = (self.built.directory / name).read_text(encoding="utf-8")
            for forbidden in (
                "setting.defaultres",
                "deviceid",
                "mat_viewportscale",
                "fullscreen_gamma",
                "monitor_index",
                "r_aspectratio",
                "citadel_camera_hero_fov",
            ):
                self.assertNotIn(forbidden, text, "%s in %s" % (forbidden, name))

    def test_installer_runs_the_bundle(self):
        source = (self.built.directory / "install.py").read_text(encoding="utf-8")
        compile(source, "install.py", "exec")
        self.assertIn("speedylock.cli", source)
        self.assertIn("'balanced'", source)
        self.assertIn("141", source)

    def test_installer_defaults_to_install(self):
        source = (self.built.directory / "install.py").read_text(encoding="utf-8")
        self.assertIn('"install"', source)

    def test_shell_installer_uses_lf(self):
        raw = (self.built.directory / "install.sh").read_bytes()
        self.assertTrue(raw.startswith(b"#!/bin/sh"))
        self.assertNotIn(b"\r", raw)

    def test_batch_installers_use_crlf_only(self):
        for name in ("install.bat", "uninstall.bat"):
            raw = (self.built.directory / name).read_bytes()
            self.assertIn(b"\r\n", raw, name)
            self.assertNotIn(b"\r\r", raw, name)

    def test_archive_contains_the_whole_bundle(self):
        self.assertIsNotNone(self.built.archive)
        names = release.zip_names(self.built.archive)
        root = self.built.directory.name
        self.assertIn("%s/mod-interchange.json" % root, names)
        self.assertIn("%s/autoexec.cfg" % root, names)
        self.assertIn("%s/install.sh" % root, names)
        self.assertIn("%s/speedylock/cli.py" % root, names)
        extras = [name for name in names if not name.startswith(root + "/")]
        self.assertEqual(extras, [])
        self.assertEqual([name for name in names if ".." in name], [])

    def test_rebuild_is_byte_identical(self):
        first = self.built.archive.read_bytes()
        again = release.build(self.out, profiles.get("balanced"), fps_cap=141)
        self.assertEqual(first, again.archive.read_bytes())
        self.assertEqual(release.verify(again.directory), [])

    def test_no_zip_option_also_drops_a_stale_archive(self):
        stale = self.out / (self.built.directory.name + ".zip")
        self.assertTrue(stale.exists())
        built = release.build(self.out, profiles.get("quality"), zip_it=False)
        self.assertIsNone(built.archive)
        # the folder was just rebuilt as `quality`; the old zip no longer matches it
        self.assertFalse(stale.exists())


class ReliefBundleTests(unittest.TestCase):
    def test_relief_overlay_reaches_every_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            built = release.build(
                Path(tmp), cpu.overlay(profiles.get("balanced")), fps_cap=141
            )
            autoexec = (built.directory / "autoexec.cfg").read_text(encoding="utf-8")
            self.assertIn('cl_simulate_dormant_entities "0"', autoexec)
            self.assertIn('citadel_healthbars_enabled "0"', autoexec)
            convars = (built.directory / "convars-block.txt").read_text(encoding="utf-8")
            self.assertIn('"cl_simulate_dormant_entities"\t"0"', convars)
            document = json.loads(
                (built.directory / "mod-interchange.json").read_text(encoding="utf-8")
            )
            self.assertEqual(document["profiles"][0]["key"], "speedylock-balanced-cpu")
            self.assertIn("relief **on**", (built.directory / "README.md").read_text(encoding="utf-8"))


class ReleaseCommandTests(unittest.TestCase):
    def _args(self, tmp, *extra):
        return cli.build_parser().parse_args(
            ["release", "--out", str(tmp), "--no-zip"] + list(extra)
        )

    def test_command_is_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self._args(tmp).func, cli.cmd_release)

    def test_command_builds_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self._args(tmp, "--profile", "balanced-cpu", "--fps-cap", "141")
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = cli.cmd_release(args)
            text = buffer.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("speedylock-1.0.0", text)
            self.assertIn("balanced-cpu", text)
            self.assertIn("checksums verified", text)
            built = Path(tmp) / "speedylock-1.0.0"
            self.assertTrue((built / "autoexec.cfg").is_file())
            self.assertEqual(release.verify(built), [])


if __name__ == "__main__":
    unittest.main()
