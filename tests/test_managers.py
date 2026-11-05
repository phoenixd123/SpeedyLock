"""Tests for Grimoire / Deadlock Mod Manager coexistence."""

import json
import tempfile
import unittest
from pathlib import Path

from speedylock import managers, profiles


class AddonScanTests(unittest.TestCase):
    def test_missing_dir_is_empty(self):
        self.assertEqual(managers.scan_addons(Path("/nonexistent-speedylock")), [])

    def test_scan_finds_vpk_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp)
            addons = install / "game" / "citadel" / "addons"
            addons.mkdir(parents=True)
            (addons / "pak01_dir.vpk").write_bytes(b"x")
            (addons / "PotatoLock.vpk").write_bytes(b"x")
            (addons / "EssentialFixes.vpk").write_bytes(b"x")
            (addons / "readme.txt").write_text("not a vpk")
            found = managers.scan_addons(install)
            self.assertEqual(len(found), 3)
            self.assertTrue(managers.has_potato_lock(found))
            self.assertTrue(managers.has_sinner_fix(found))

    def test_hints_on_empty_list(self):
        self.assertFalse(managers.has_potato_lock([]))
        self.assertFalse(managers.has_sinner_fix([]))


class DetectionTests(unittest.TestCase):
    def test_config_directory_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cfgroot"
            root.mkdir()
            (root / "grimoire").mkdir()
            findings = managers.detect_managers(Path(tmp) / "nope", config_root=root)
            self.assertEqual([f.key for f in findings], [managers.GRIMOIRE])
            self.assertTrue(findings[0].evidence)

    def test_unidentified_manager_from_addons(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp)
            (install / "game" / "citadel" / "addons").mkdir(parents=True)
            (install / "game" / "citadel" / "addons" / "pak01_dir.vpk").write_bytes(b"x")
            root = Path(tmp) / "cfgroot"
            root.mkdir()
            findings = managers.detect_managers(install, config_root=root)
            self.assertEqual([f.key for f in findings], [managers.UNKNOWN])

    def test_nothing_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cfgroot"
            root.mkdir()
            self.assertEqual(
                managers.detect_managers(Path(tmp) / "nope", config_root=root), []
            )


class InterchangeTests(unittest.TestCase):
    def test_documented_shape(self):
        document = managers.interchange("balanced", ["fps_max 120"])
        self.assertEqual(document["format"], "deadlock-mod-interchange")
        self.assertEqual(document["version"], 1)
        # The format is VPK-only, so mods[] must stay empty for a config tool.
        self.assertEqual(document["mods"], [])
        self.assertEqual(document["profiles"][0]["autoexec"], ["fps_max 120"])
        self.assertIn("warnings", document)
        json.dumps(document)

    def test_bundle_writes_the_three_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "bundle"
            paths = managers.write_bundle(
                dest, profiles.get("quality"), ["fps_max 120"]
            )
            self.assertEqual(
                sorted(p.name for p in paths),
                ["README.md", "autoexec.cfg", "mod-interchange.json"],
            )
            document = json.loads((dest / "mod-interchange.json").read_text())
            self.assertEqual(document["format"], "deadlock-mod-interchange")
            self.assertEqual(document["profiles"][0]["key"], "speedylock-quality")
            self.assertIn("fps_max 120", (dest / "autoexec.cfg").read_text())
            self.assertIn("Grimoire", (dest / "README.md").read_text())

    def test_bundle_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "one"
            second = Path(tmp) / "two"
            managers.write_bundle(first, profiles.get("quality"), ["a 1"])
            managers.write_bundle(second, profiles.get("quality"), ["a 1"])
            self.assertEqual(
                (first / "mod-interchange.json").read_text(),
                (second / "mod-interchange.json").read_text(),
            )


class DuplicateTests(unittest.TestCase):
    def test_reports_overlap(self):
        ours = [("fps_max", "120"), ("only_ours", "1")]
        existing = [("fps_max", "0"), ("theirs", "2")]
        self.assertEqual(managers.convar_duplicates(ours, existing), ["fps_max"])

    def test_no_overlap(self):
        self.assertEqual(managers.convar_duplicates([("a", "1")], []), [])
        self.assertEqual(managers.convar_duplicates([], [("a", "1")]), [])


if __name__ == "__main__":
    unittest.main()
