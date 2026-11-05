"""Tests for the OptiLock-derived preset data."""

import unittest

from speedylock import convars, gamefiles, optilock, profiles


class DataShapeTests(unittest.TestCase):
    def test_block_is_substantial(self):
        # If the import ever silently degrades to a handful of keys, this fails.
        self.assertGreater(len(optilock.CONVARS), 400)
        self.assertGreater(len(optilock.VIDEO), 40)

    def test_no_protected_video_key_is_carried(self):
        for key in optilock.VIDEO:
            self.assertNotIn(key, gamefiles.PROTECTED_VIDEO_KEYS, key)
        for tier in optilock.TIERS:
            for key in optilock.resolve_video(tier):
                self.assertNotIn(key, gamefiles.PROTECTED_VIDEO_KEYS, key)

    def test_several_tiers_resolve(self):
        for tier in optilock.TIERS:
            self.assertTrue(optilock.resolve(tier))
            self.assertTrue(optilock.resolve_video(tier))

    def test_unknown_tier_raises(self):
        with self.assertRaises(KeyError):
            optilock.resolve("not-a-tier")
        with self.assertRaises(KeyError):
            optilock.resolve_video("not-a-tier")

    def test_tiers_get_progressively_harsher(self):
        base = dict(optilock.resolve())
        potato = dict(optilock.resolve("optilock-potato"))
        ultra = dict(optilock.resolve("optilock-ultra"))
        self.assertGreater(int(base["r_farz"]), int(potato["r_farz"]))
        self.assertGreater(int(potato["r_farz"]), int(ultra["r_farz"]))


class KnowledgeBaseTests(unittest.TestCase):
    def test_every_imported_convar_is_known(self):
        for name in optilock.CONVARS:
            self.assertIsNotNone(convars.get(name), name)

    def test_only_deliberate_exceptions_are_unwritable(self):
        # If the import ever smuggles a cheat-flagged or unknown convar in, this
        # list grows and the test fails. cl_resend is the sole intentional case.
        blocked = sorted(
            name for name in optilock.CONVARS if not convars.get(name).is_writable()
        )
        self.assertEqual(blocked, ["cl_resend"])

    def test_curated_classification_wins_over_import(self):
        # The import must never downgrade something we already know is risky.
        self.assertIs(convars.get("cl_resend").status, convars.Status.RISKY)
        self.assertFalse(convars.get("cl_resend").is_writable())
        self.assertIs(
            convars.get("cl_interp_ratio").status, convars.Status.VERIFIED
        )

    def test_safe_values_override_optilock(self):
        paired = dict(optilock.resolve())
        self.assertEqual(paired["cl_interp_ratio"], "1")
        self.assertEqual(paired["cl_updaterate"], "60")
        # ...and the disagreement is documented for the user, not just coded.
        self.assertIn("cl_interp_ratio", optilock.DISAGREE)
        self.assertIn("cl_updaterate", optilock.DISAGREE)

    def test_player_preferences_are_not_carried(self):
        # FOV and aspect ratio belong to the player, not to a performance preset.
        for tier in (None,) + tuple(optilock.TIERS):
            names = dict(optilock.resolve(tier))
            self.assertNotIn("citadel_camera_hero_fov", names)
            self.assertNotIn("r_aspectratio", names)

    def test_register_documented_does_not_overwrite(self):
        before = convars.CONVARS["cl_resend"]
        convars.register_documented({"cl_resend": "99", "zz_fake_cvar": "1"})
        self.assertIs(convars.CONVARS["cl_resend"], before)
        self.assertEqual(convars.CONVARS["zz_fake_cvar"].status, convars.Status.DOCUMENTED)
        del convars.CONVARS["zz_fake_cvar"]


class ProfileWiringTests(unittest.TestCase):
    def test_profiles_registered(self):
        for key in ("optilock", "optilock-potato", "optilock-ultra", "optilock-community"):
            self.assertIn(key, profiles.names())

    def test_gameinfo_is_the_full_block_autoexec_is_not(self):
        profile = profiles.get("optilock")
        self.assertGreater(len(profile.gameinfo), 400)
        # 400 lines of exec at startup would be slower and noisier than the
        # ConVars block, so autoexec only carries the runtime-critical subset.
        self.assertLess(len(profile.settings), 20)

    def test_cap_placeholder_survives_import(self):
        profile = profiles.get("optilock")
        values = dict(profile.gameinfo)
        self.assertEqual(values["fps_max"], "{fps_cap}")
        self.assertEqual(profile.video["setting.fps_max"], "{fps_cap}")

    def test_every_gameinfo_convar_is_writable(self):
        for key in profiles.names():
            for name, _value in profiles.get(key).gameinfo:
                cvar = convars.get(name)
                self.assertIsNotNone(cvar, "%s: %s" % (key, name))
                self.assertTrue(cvar.is_writable(), "%s: %s" % (key, name))


if __name__ == "__main__":
    unittest.main()
