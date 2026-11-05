import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from speedylock import detect


class LocateTests(unittest.TestCase):
    def test_looks_like_deadlock_requires_the_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(detect.looks_like_deadlock(root))
            (root / "game" / "citadel").mkdir(parents=True)
            self.assertTrue(detect.looks_like_deadlock(root))

    def test_cfg_dir_layout(self):
        install = Path("/games/Deadlock")
        self.assertEqual(
            detect.cfg_dir(install),
            Path("/games/Deadlock/game/citadel/cfg"),
        )

    def test_env_override_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / "Deadlock"
            (install / "game" / "citadel").mkdir(parents=True)
            with mock.patch.dict(os.environ, {detect.ENV_GAME_DIR: str(install)}):
                self.assertEqual(detect.find_install(), install)

    def test_explicit_path_is_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                detect.find_install(tmp)

    def test_explicit_path_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / "Deadlock"
            (install / "game" / "citadel").mkdir(parents=True)
            self.assertEqual(detect.find_install(str(install)), install)


class ProfileGuessTests(unittest.TestCase):
    def test_integrated_gpu_gets_potato(self):
        self.assertEqual(detect.guess_profile("Intel(R) UHD Graphics 620"), "potato")
        self.assertEqual(detect.guess_profile("NVIDIA GeForce GT 730"), "potato")
        self.assertEqual(detect.guess_profile("AMD Radeon Vega 8 Graphics"), "potato")

    def test_discrete_gpu_gets_balanced(self):
        self.assertEqual(detect.guess_profile("NVIDIA GeForce RTX 4070"), "balanced")
        self.assertEqual(detect.guess_profile("AMD Radeon RX 7800 XT"), "balanced")

    def test_unknown_hardware_defaults_to_balanced(self):
        self.assertEqual(detect.guess_profile(None), "balanced")
        self.assertEqual(detect.guess_profile(""), "balanced")

    def test_probe_helpers_never_raise(self):
        # These shell out; they must degrade to None on any failure.
        self.assertTrue(detect.gpu_name() is None or isinstance(detect.gpu_name(), str))
        self.assertTrue(detect.cpu_name() is None or isinstance(detect.cpu_name(), str))


if __name__ == "__main__":
    unittest.main()
