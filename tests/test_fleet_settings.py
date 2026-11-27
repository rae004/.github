"""python3 -m unittest discover tests"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fleet_settings import SettingsError, build_ruleset, validate  # noqa: E402

BASELINE = json.loads((ROOT / "repo-defaults" / "ruleset.json").read_text())


def rule(ruleset, kind):
    return next((r for r in ruleset["rules"] if r["type"] == kind), None)


class BuildRuleset(unittest.TestCase):
    def test_no_settings_is_the_baseline(self):
        self.assertEqual(build_ruleset(BASELINE, {}), BASELINE)

    def test_checks_add_a_strict_rule(self):
        params = rule(
            build_ruleset(BASELINE, {"required_status_checks": ["a", "b"]}),
            "required_status_checks",
        )["parameters"]
        self.assertTrue(params["strict_required_status_checks_policy"])
        self.assertEqual(params["required_status_checks"], [{"context": "a"}, {"context": "b"}])

    def test_pull_request_patch_changes_only_that_parameter(self):
        key = "require_extra_approval_for_unattributed_changes"
        built = rule(build_ruleset(BASELINE, {"pull_request": {key: False}}), "pull_request")[
            "parameters"
        ]
        base = rule(BASELINE, "pull_request")["parameters"]
        self.assertFalse(built[key])
        self.assertEqual({**built, key: base[key]}, base)

    def test_baseline_is_not_mutated(self):
        before = json.dumps(BASELINE)
        build_ruleset(
            BASELINE,
            {
                "required_status_checks": ["a"],
                "pull_request": {"required_approving_review_count": 1},
            },
        )
        self.assertEqual(json.dumps(BASELINE), before)

    def test_unknown_pull_request_parameter_is_rejected(self):
        with self.assertRaises(SettingsError):
            build_ruleset(BASELINE, {"pull_request": {"nope": True}})


class Validate(unittest.TestCase):
    def test_unknown_key_is_rejected(self):
        with self.assertRaises(SettingsError):
            validate({"allow_merge_commit": True})

    def test_bad_shapes_are_rejected(self):
        for bad in (
            [],
            {"required_status_checks": "lint"},
            {"required_status_checks": [""]},
            {"pull_request": []},
            {"labels": [{"color": "fff"}]},
        ):
            with self.assertRaises(SettingsError):
                validate(bad)


if __name__ == "__main__":
    unittest.main()
