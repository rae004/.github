"""python3 -m unittest discover tests"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_title import problem  # noqa: E402


class Problem(unittest.TestCase):
    def test_accepts_conventional_titles(self):
        for title in (
            "feat: add digest filters",
            "fix(email): handle empty feed (#12)",
            "chore(deps-dev): bump eslint from 10.14.0 to 10.15.0",
            "feat!: drop the v1 config",
            "ci: pin actions",
            "revert: undo the footer",
        ):
            self.assertIsNone(problem(title), title)

    def test_rejects_everything_else(self):
        for title in (
            "Update README",
            "M10: generate the dataset",
            "feature: not an allowed type",
            "Feat: types are lowercase",
            "feat:missing space",
            "feat: ",
            "",
        ):
            self.assertIsNotNone(problem(title), title)


if __name__ == "__main__":
    unittest.main()
