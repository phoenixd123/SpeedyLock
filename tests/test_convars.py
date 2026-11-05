import unittest

from speedylock import convars, profiles


class KnowledgeBaseTests(unittest.TestCase):
    def test_cheat_convars_are_never_writable(self):
        for cvar in convars.by_status(convars.Status.CHEAT):
            self.assertFalse(cvar.is_writable(), cvar.name)
            self.assertFalse(cvar.is_writable(experimental=True), cvar.name)

    def test_unknown_convars_are_never_writable(self):
        for cvar in convars.by_status(convars.Status.UNKNOWN):
            self.assertFalse(cvar.is_writable(), cvar.name)
            self.assertFalse(cvar.is_writable(experimental=True), cvar.name)

    def test_risky_convars_need_experimental(self):
        risky = convars.by_status(convars.Status.RISKY)
        self.assertTrue(risky, "expected at least one RISKY convar")
        for cvar in risky:
            self.assertFalse(cvar.is_writable())
            self.assertTrue(cvar.is_writable(experimental=True))

    def test_ragdoll_limit_and_cheat_ragdolls_are_distinct(self):
        # It is easy to reach for cl_disable_ragdolls here; it is cheat-flagged
        # and does nothing in a live match.
        self.assertTrue(convars.is_writable("cl_ragdoll_limit"))
        self.assertFalse(convars.is_writable("cl_disable_ragdolls"))

    def test_unknown_name_is_not_writable(self):
        self.assertFalse(convars.is_writable("totally_made_up_convar"))
        self.assertIsNone(convars.get("totally_made_up_convar"))


class ProfileTests(unittest.TestCase):
    def test_every_setting_is_known_and_writable(self):
        for key in profiles.names():
            profile = profiles.get(key)
            self.assertTrue(profile.settings, key)
            for name, value in profile.settings:
                cvar = convars.get(name)
                self.assertIsNotNone(cvar, "%s uses unknown convar %s" % (key, name))
                self.assertTrue(
                    cvar.is_writable(), "%s uses non-writable convar %s" % (key, name)
                )
                self.assertTrue(str(value), "%s has empty value for %s" % (key, name))

    def test_settings_are_unique_within_a_profile(self):
        for key in profiles.names():
            names = [name for name, _ in profiles.get(key).settings]
            self.assertEqual(len(names), len(set(names)), key)

    def test_every_profile_caps_ui_framerate_or_fps(self):
        for key in profiles.names():
            names = {name for name, _ in profiles.get(key).settings}
            self.assertIn("fps_max", names, key)

    def test_unknown_profile_raises_helpful_error(self):
        with self.assertRaises(KeyError) as ctx:
            profiles.get("ultra")
        self.assertIn("potato", str(ctx.exception))

    def test_launch_options_include_autoexec(self):
        for key in profiles.names():
            self.assertIn("autoexec", profiles.get(key).launch_options, key)


if __name__ == "__main__":
    unittest.main()
