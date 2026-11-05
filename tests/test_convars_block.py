"""Tests for parsing and writing the ConVars block in both naming styles."""

import unittest

from speedylock import gamefiles, managers

QUOTED = '"GameInfo"\n{\n\tConVars\n\t{\n\t\t"r_aspectratio"\t\t"2.15"\n\t\t"r_farz"\t\t"9000"\n\t}\n}\n'
BARE = '"GameInfo"\n{\n\tConVars\n\t{\n\t\tr_aspectratio\t\t"2.15"\n\t\tr_farz\t\t"9000"\n\t}\n}\n'


class ParseTests(unittest.TestCase):
    def test_quoted_names(self):
        pairs = dict(gamefiles._convars_of(QUOTED))
        self.assertEqual(pairs["r_aspectratio"], "2.15")
        self.assertEqual(pairs["r_farz"], "9000")

    def test_bare_names(self):
        pairs = dict(gamefiles._convars_of(BARE))
        self.assertEqual(pairs["r_aspectratio"], "2.15")

    def test_roundtrip_preserves_quote_style(self):
        for source, marker in ((QUOTED, '"r_farz"'), (BARE, "\t\tr_farz\t")):
            merged = gamefiles.inject_gameinfo(source, [("vis_enable", "1")], "test")
            self.assertIn(marker, merged)
            self.assertIn("vis_enable", merged)

    def test_missing_block_is_refused(self):
        with self.assertRaises(gamefiles.GameFileError):
            gamefiles.inject_gameinfo('"GameInfo"\n{\n}\n', [("a", "1")], "test")


class ManagedVsExistingTests(unittest.TestCase):
    def test_plain_view_excludes_managed_rows(self):
        merged = gamefiles.inject_gameinfo(QUOTED, [("vis_enable", "1")], "test")
        self.assertEqual(len(gamefiles.convars_in_block(merged)), 2)
        self.assertEqual(len(gamefiles.all_convars_in_block(merged)), 3)

    def test_duplicates_are_detectable(self):
        merged = gamefiles.inject_gameinfo(QUOTED, [("r_farz", "7000")], "test")
        every = gamefiles.all_convars_in_block(merged)
        outside = gamefiles.convars_in_block(merged)
        ours = every[len(outside) :]
        self.assertEqual(ours, [("r_farz", "7000")])
        self.assertEqual(managers.convar_duplicates(ours, outside), ["r_farz"])

    def test_strip_restores_the_original_exactly(self):
        merged = gamefiles.inject_gameinfo(QUOTED, [("a", "1"), ("b", "2")], "test")
        self.assertEqual(gamefiles.strip_gameinfo(merged), QUOTED)


if __name__ == "__main__":
    unittest.main()
