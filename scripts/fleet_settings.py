#!/usr/bin/env python3
"""Fleet repo settings: diff or apply `repo-defaults/` across `repos.txt`.

    python3 scripts/fleet_settings.py diff    # exit 1 on drift anywhere
    python3 scripts/fleet_settings.py apply   # push the baseline (needs admin)

`repo-defaults/` is the single source of truth for every repo in `repos.txt`.
A repo may carry one small file, `.github/repo-settings.json`, holding only
what legitimately differs for it:

    {
      "required_status_checks": ["lint", "test"],   # CI job names
      "pull_request": {"some_parameter": false},     # patch on the PR rule
      "labels": [{"name": "x", "color": "0075ca", "description": "..."}]
    }

All keys are optional and any other key is an error. The file is read from
the repo's default branch through the API; no script or baseline copy lives
in the repos.

Each repo gets exactly one ruleset, `repo-defaults/ruleset.json`, plus a
strict `required_status_checks` rule when the repo lists checks. If the repo
has a single live ruleset under another name it is updated in place
(renamed); any other live ruleset is reported as drift and never deleted.

Transition guard: a repo that still has the old in-repo `.github/repo/`
folder and no `.github/repo-settings.json` is skipped, so the baseline can't
strip its required checks before it is migrated.

The baseline deliberately omits `visibility` (an apply must never flip a
private repo public). A failed apply on one target prints FAILED and moves
on. Apply also enables Dependabot vulnerability alerts first, the documented
prerequisite for `dependabot_security_updates`.
"""

import base64
import copy
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from repo_settings import ApiError, drift, gh, load, report  # noqa: E402

BASE = Path(__file__).resolve().parents[1]
DEFAULTS = BASE / "repo-defaults"
REPOS_FILE = BASE / "repos.txt"
SETTINGS_PATH = ".github/repo-settings.json"
LEGACY_PATH = ".github/repo"
ALLOWED_KEYS = {"required_status_checks", "pull_request", "labels"}

# (file name, GET suffix, write method, write suffix), suffixes on `repos/{slug}`.
TARGETS = [
    ("repository.json", "", "PATCH", ""),
    ("actions-permissions.json", "/actions/permissions", "PUT", "/actions/permissions"),
    ("actions-workflow.json", "/actions/permissions/workflow", "PUT", "/actions/permissions/workflow"),
]


class SettingsError(Exception):
    pass


def validate(settings: Any) -> dict[str, Any]:
    """Reject anything but the three allowed, correctly shaped keys."""
    if not isinstance(settings, dict):
        raise SettingsError("must be a JSON object")
    unknown = sorted(set(settings) - ALLOWED_KEYS)
    if unknown:
        raise SettingsError(f"unknown key(s): {', '.join(unknown)}")
    checks = settings.get("required_status_checks", [])
    if not isinstance(checks, list) or not all(isinstance(c, str) and c for c in checks):
        raise SettingsError("required_status_checks must be a list of job names")
    if not isinstance(settings.get("pull_request", {}), dict):
        raise SettingsError("pull_request must be an object")
    labels = settings.get("labels", [])
    if not isinstance(labels, list) or not all(isinstance(x, dict) and x.get("name") for x in labels):
        raise SettingsError("labels must be a list of objects with a name")
    return settings


def build_ruleset(baseline: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """The baseline ruleset with one repo's differences layered on."""
    ruleset = copy.deepcopy(baseline)
    patch = settings.get("pull_request", {})
    if patch:
        rule = next(r for r in ruleset["rules"] if r["type"] == "pull_request")
        unknown = sorted(set(patch) - set(rule["parameters"]))
        if unknown:
            raise SettingsError(f"pull_request: unknown parameter(s): {', '.join(unknown)}")
        rule["parameters"].update(patch)
    checks = settings.get("required_status_checks", [])
    if checks:
        ruleset["rules"].append(
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "do_not_enforce_on_create": False,
                    "required_status_checks": [{"context": c} for c in checks],
                },
            }
        )
    return ruleset


def _exists(slug: str, path: str) -> bool:
    try:
        gh("GET", f"repos/{slug}/contents/{path}")
        return True
    except ApiError as e:
        if e.status == 404:
            return False
        raise


def fetch_settings(slug: str) -> dict[str, Any] | None:
    """The repo's own settings file; {} when it has none; None when not migrated."""
    try:
        res = gh("GET", f"repos/{slug}/contents/{SETTINGS_PATH}")
    except ApiError as e:
        if e.status != 404:
            raise
        return None if _exists(slug, LEGACY_PATH) else {}
    try:
        return validate(json.loads(base64.b64decode(res["content"])))
    except ValueError as e:
        raise SettingsError(f"not valid JSON: {e}") from None


def _write(apply: bool, method: str, path: str, desired: object, name: str, verb: str) -> None:
    if not apply:
        return
    try:
        gh(method, path, desired)
        print(f"  {verb:<8} {name}")
    except ApiError as e:
        print(f"  FAILED   {name} ({e})")


def check_targets(slug: str, apply: bool) -> int:
    drifted = 0
    for name, get_suffix, method, put_suffix in TARGETS:
        desired = load(DEFAULTS / name)
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
    return drifted


def check_ruleset(slug: str, settings: dict[str, Any], apply: bool) -> int:
    desired = build_ruleset(load(DEFAULTS / "ruleset.json"), settings)
    try:
        live_list = {r["name"]: r["id"] for r in gh("GET", f"repos/{slug}/rulesets") or []}
    except ApiError as e:
        print(f"  skipped  ruleset ({e})")
        return 0
    drifted = 0
    current = desired["name"]
    if current not in live_list and len(live_list) == 1:
        current = next(iter(live_list))  # a lone ruleset under another name: rename it in place
    ruleset_id = live_list.pop(current, None)
    if ruleset_id is None:
        print("  DRIFT    ruleset (not on GitHub)")
        drifted += 1
        _write(apply, "POST", f"repos/{slug}/rulesets", desired, "ruleset", "created")
    else:
        live = gh("GET", f"repos/{slug}/rulesets/{ruleset_id}")
        changes, unverified = drift(desired, live)
        report("ruleset", changes, unverified)
        if changes:
            drifted += 1
            _write(apply, "PUT", f"repos/{slug}/rulesets/{ruleset_id}", desired, "ruleset", "applied")
    for name, extra_id in sorted(live_list.items()):
        print(f"  DRIFT    unexpected ruleset {name!r}; remove it by hand:")
        print(f"           gh api -X DELETE repos/{slug}/rulesets/{extra_id}")
        drifted += 1
    return drifted


def check_labels(slug: str, settings: dict[str, Any], apply: bool) -> int:
    wanted = settings.get("labels", [])
    if not wanted:
        return 0
    drifted = 0
    live = {label["name"]: label for label in gh("GET", f"repos/{slug}/labels?per_page=100") or []}
    for want in wanted:
        name = f"labels/{want['name']}"
        have = live.get(want["name"])
        if have is None:
            print(f"  DRIFT    {name} (not on GitHub)")
            drifted += 1
            _write(apply, "POST", f"repos/{slug}/labels", want, name, "created")
            continue
        changes, _ = drift(want, have)
        report(name, changes, [])
        if changes:
            drifted += 1
            _write(apply, "PATCH", f"repos/{slug}/labels/{want['name']}", want, name, "applied")
    return drifted


def check_repo(slug: str, apply: bool) -> int:
    try:
        settings = fetch_settings(slug)
        if settings is None:
            print(f"{slug}: skipped (not migrated: has {LEGACY_PATH}/ but no {SETTINGS_PATH})")
            return 0
        print(f"{slug}:")
        build_ruleset(load(DEFAULTS / "ruleset.json"), settings)  # fail before any write
    except SettingsError as e:
        print(f"{slug}:\n  DRIFT    {SETTINGS_PATH} is invalid: {e}")
        return 1
    if apply:
        try:
            gh("PUT", f"repos/{slug}/vulnerability-alerts")
        except ApiError as e:
            print(f"  FAILED   vulnerability-alerts ({e})")
    return (
        check_targets(slug, apply)
        + check_ruleset(slug, settings, apply)
        + check_labels(slug, settings, apply)
    )


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
    try:
        for slug in slugs:
            drifted += check_repo(slug, apply)
    except ApiError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if drifted and not apply:
        print(f"\n{drifted} target(s) drifted across the fleet.")
        return 1
    print("\nFleet matches." if not drifted else f"\n{drifted} target(s) applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
