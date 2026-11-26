#!/usr/bin/env python3
"""Check that a pull request title is a Conventional Commit.

    PR_TITLE="feat: add filters" python3 check_title.py

The PR title becomes the squash commit message, and the release workflow
reads that message to decide the version, so a malformed title would silently
skip a release. Uses the same parser and type list as next_version.py, so
"valid title" and "what gets released" cannot disagree.

The title is read from the PR_TITLE environment variable, never from the
command line, because it is untrusted input.
"""

import os
import sys

from next_version import HEADER, TYPES, level

EFFECT = {
    0: "no release",
    1: "a patch release",
    2: "a minor release",
    3: "a major release (a minor release while the repo is on 0.x)",
}


def problem(title: str) -> str | None:
    """Why `title` is not acceptable, or None when it is fine."""
    match = HEADER.match(title)
    if not match:
        return "it is not in the form `type: subject` or `type(scope): subject`"
    if match["type"] not in TYPES:
        return f"`{match['type']}` is not an allowed type"
    if not title[match.end() :].strip():
        return "the subject after the colon is empty"
    return None


def main() -> int:
    title = os.environ.get("PR_TITLE", "")
    why = problem(title)
    if why:
        print(f"::error title=PR title is not a Conventional Commit::{why}.")
        print(f"Title:   {title!r}")
        print(f"Allowed: {', '.join(TYPES)}")
        print("Example: feat(email): add a footer")
        return 1
    print(f"OK: merging this PR cuts {EFFECT[level(title)]}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
