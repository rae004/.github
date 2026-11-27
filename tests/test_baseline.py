"""The real files in repo-defaults/ and repos.txt, checked offline.

`fleet_settings.py` reads these at run time, so without these tests a typo in
one of them is first seen part-way through an `apply` across the fleet.
"""

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fleet_settings import DEFAULTS, TARGETS, build_ruleset, fleet_slugs  # noqa: E402

EXPECTED_FILES = {name for name, *_ in TARGETS} | {"ruleset.json"}


def baseline(name):
    return json.loads((DEFAULTS / name).read_text())


class BaselineFiles(unittest.TestCase):
    def test_folder_holds_exactly_the_files_the_script_reads(self):
        # A misnamed or stray file would be silently ignored by the script.
        self.assertEqual({p.name for p in DEFAULTS.iterdir()}, EXPECTED_FILES)

    def test_every_file_is_a_json_object(self):
        for name in sorted(EXPECTED_FILES):
            with self.subTest(file=name):
                self.assertIsInstance(baseline(name), dict)

    def test_ruleset_builds_with_and_without_required_checks(self):
        ruleset = baseline("ruleset.json")
        for settings in ({}, {"required_status_checks": ["lint"]}):
            with self.subTest(settings=settings):
                build_ruleset(ruleset, settings)


class Guardrails(unittest.TestCase):
    """Values chosen on purpose; changing one should be a deliberate edit here too."""

    def test_visibility_is_never_managed(self):
        # An apply must never be able to flip a private repo public.
        self.assertNotIn("visibility", baseline("repository.json"))
        self.assertNotIn("private", baseline("repository.json"))

    def test_nobody_bypasses_the_ruleset(self):
        ruleset = baseline("ruleset.json")
        self.assertEqual(ruleset["bypass_actors"], [])
        self.assertEqual(ruleset["enforcement"], "active")

    def test_actions_must_be_pinned_to_a_commit(self):
        self.assertIs(baseline("actions-permissions.json")["sha_pinning_required"], True)


class ReposFile(unittest.TestCase):
    def test_every_line_is_an_owner_and_a_repo_name(self):
        slugs = fleet_slugs()
        self.assertTrue(slugs)
        for slug in slugs:
            with self.subTest(slug=slug):
                self.assertRegex(slug, re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$"))

    def test_no_repo_is_listed_twice(self):
        slugs = [s.lower() for s in fleet_slugs()]
        self.assertEqual(len(slugs), len(set(slugs)))


if __name__ == "__main__":
    unittest.main()
