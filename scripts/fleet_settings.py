#!/usr/bin/env python3
"""Fleet repo settings: diff or apply `repo-defaults/` across `repos.txt`.

    python3 scripts/fleet_settings.py diff    # exit 1 on drift anywhere
    python3 scripts/fleet_settings.py apply   # push the baseline (needs admin)

Hybrid model: a repo that carries its own `.github/repo/` folder is
self-managed by its in-repo copy of `repo_settings.py` and is skipped
here. For everything else, the desired state for each target file is
`overrides/<repo>/<file>` when present, else `repo-defaults/<file>`
(whole-file replacement, no merging). Rulesets are the union of the
default and override `rulesets/` folders, matched to live rulesets by
their `name` field.

The baseline deliberately omits `visibility` (an apply must never flip
a private repo public) and anything that needs a paid plan on private
repos; a failed apply on one target prints FAILED and moves on, so one
plan-limited repo can't abort the fleet. Apply also enables Dependabot
vulnerability alerts first — the documented prerequisite for
`dependabot_security_updates`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from repo_settings import ApiError, drift, gh, load, report  # noqa: E402

BASE = Path(__file__).resolve().parents[1]
DEFAULTS = BASE / "repo-defaults"
OVERRIDES = BASE / "overrides"
REPOS_FILE = BASE / "repos.txt"

# (file name, GET suffix, write method, write suffix) — suffixes on `repos/{slug}`.
TARGETS = [
    ("repository.json", "", "PATCH", ""),
    ("actions-permissions.json", "/actions/permissions", "PUT", "/actions/permissions"),
    ("actions-workflow.json", "/actions/permissions/workflow", "PUT", "/actions/permissions/workflow"),
]


def _desired_file(slug: str, name: str) -> Path | None:
    repo = slug.split("/", 1)[1]
    for candidate in (OVERRIDES / repo / name, DEFAULTS / name):
        if candidate.exists():
            return candidate
    return None


def _ruleset_files(slug: str) -> dict[str, Path]:
    repo = slug.split("/", 1)[1]
    files: dict[str, Path] = {}
    for folder in (DEFAULTS / "rulesets", OVERRIDES / repo / "rulesets"):
        if folder.exists():
            for f in sorted(folder.glob("*.json")):
                files[f.name] = f  # override folder comes last, so it wins
    return files


def _self_managed(slug: str) -> bool:
    try:
        gh("GET", f"repos/{slug}/contents/.github/repo")
        return True
    except ApiError:
        return False


def _write(apply: bool, method: str, path: str, desired: object, name: str, verb: str) -> None:
    if not apply:
        return
    try:
        gh(method, path, desired)
        print(f"  {verb:<8} {name}")
    except ApiError as e:
        print(f"  FAILED   {name} ({e})")


def check_repo(slug: str, apply: bool) -> int:
    if _self_managed(slug):
        print(f"{slug}: skipped (self-managed via its own .github/repo/)")
        return 0
    print(f"{slug}:")
    if apply:
        try:
            gh("PUT", f"repos/{slug}/vulnerability-alerts")
        except ApiError as e:
            print(f"  FAILED   vulnerability-alerts ({e})")
    drifted = 0
    for name, get_suffix, method, put_suffix in TARGETS:
        file = _desired_file(slug, name)
        if file is None:
            continue
        desired = load(file)
        try:
            live = gh("GET", f"repos/{slug}{get_suffix}")
        except ApiError as e:
            print(f"  skipped  {name} ({e})")
            continue
        changes, unverified = drift(desired, live)
        report(name, changes, unverified)
        if changes:
            drifted += 1
            _write(apply, method, f"repos/{slug}{put_suffix}", desired, name, "applied")
    files = _ruleset_files(slug)
    if files:
        try:
            live_list = {r["name"]: r["id"] for r in gh("GET", f"repos/{slug}/rulesets") or []}
        except ApiError as e:
            print(f"  skipped  rulesets ({e})")
            return drifted
        for fname, file in files.items():
            desired = load(file)
            name = f"rulesets/{fname}"
            ruleset_id = live_list.get(desired["name"])
            if ruleset_id is None:
                print(f"  DRIFT    {name} (not on GitHub)")
                drifted += 1
                _write(apply, "POST", f"repos/{slug}/rulesets", desired, name, "created")
                continue
            live = gh("GET", f"repos/{slug}/rulesets/{ruleset_id}")
            changes, unverified = drift(desired, live)
            report(name, changes, unverified)
            if changes:
                drifted += 1
                _write(apply, "PUT", f"repos/{slug}/rulesets/{ruleset_id}", desired, name, "applied")
    return drifted


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in {"diff", "apply"}:
        print(__doc__)
        return 2
    apply = argv[1] == "apply"
    slugs = [
        line.strip()
        for line in REPOS_FILE.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    print(f"{'Applying' if apply else 'Comparing'} repo-defaults against {len(slugs)} repo(s)")
    drifted = 0
    for slug in slugs:
        drifted += check_repo(slug, apply)
    if drifted and not apply:
        print(f"\n{drifted} target(s) drifted across the fleet.")
        return 1
    print("\nFleet matches." if not drifted else f"\n{drifted} target(s) applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
