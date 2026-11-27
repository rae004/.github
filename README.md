# .github

Default [community health files](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/creating-a-default-community-health-file)
and fleet-wide repository settings for all `rae004` repositories.

## Fleet settings as code

GitHub has no account-level defaults for repo settings, so this repo holds
them. It is the single source of truth for every repo in `repos.txt`.

| Where | What |
|---|---|
| `repo-defaults/` | The baseline for all repos, as GitHub REST API bodies |
| `repos.txt` | The repos it applies to |
| `scripts/fleet_settings.py` | Compares (`diff`) or pushes (`apply`) the baseline, repo by repo |
| `.github/repo-settings.json` in each repo | Only what differs for that repo |

```
python3 scripts/fleet_settings.py diff     # show drift; exit 1 if any
python3 scripts/fleet_settings.py apply    # push to GitHub (needs repo admin)
python3 -m unittest discover tests
```

`apply` is only ever run by hand. Nothing changes on GitHub when a PR merges.

Dropped connections, rate limits and GitHub server errors are retried up to
five times with exponential backoff and jitter, so one network blip does not
abort a run across every repo. Both commands are safe to run again at any
time.

### What the baseline enforces

- Changes reach the default branch only through a PR (0 approvals).
- Squash or rebase only; linear history; no force-push or deletion.
- A squash commit always takes its message from the PR title.
- Required checks must pass, and the branch must be up to date first.
- No bypass: the rules bind admins too.
- Actions must be pinned to a commit SHA.
- Secret scanning, push protection and Dependabot security updates on.
- Wiki off; branches deleted on merge; auto-merge and "Update branch" on.

`visibility` is deliberately not managed, so an apply can never make a
private repo public.

### Per-repo differences

A repo lists its own differences in `.github/repo-settings.json`. All keys
are optional; any other key is an error.

```json
{
  "required_status_checks": ["lint", "test"],
  "pull_request": { "require_extra_approval_for_unattributed_changes": false },
  "labels": [{ "name": "local-agent", "color": "0075ca", "description": "Hand to local agent" }]
}
```

| Key | Meaning |
|---|---|
| `required_status_checks` | CI job names that must pass. Use the job's `name:`, or its id if it has none |
| `pull_request` | Changes to individual parameters of the baseline's pull-request rule |
| `labels` | Issue labels to keep in place; other labels are left alone |

A repo with no file gets the baseline with no required checks.

Safety guard: a repo that has an old in-repo `.github/repo/` folder and no
`.github/repo-settings.json` is skipped, so the baseline cannot strip its
required checks.

### Common tasks

- **Change a setting for every repo:** edit `repo-defaults/`, merge, run `apply`.
- **Add a required CI job:** add the job and its name in
  `.github/repo-settings.json` in the same PR, merge, run `apply`.
- **Rename or remove a required CI job:** two steps, because a PR cannot
  pass a required check whose job no longer exists under that name.
  1. Remove the old name from `.github/repo-settings.json`, merge, run `apply`.
  2. Rename the job and add the new name to the file, merge, run `apply`.
- **Add a repo:** add it to `repos.txt`; give it a `.github/repo-settings.json`
  listing its CI jobs; make sure its workflows pin actions to a SHA and CI on
  the default branch is green; run `diff`, then `apply`.

### Rulesets

Each repo has exactly one ruleset, `Protect Main`. A lone ruleset under
another name is renamed in place. Any additional ruleset is reported as
drift with the command to delete it; the script never deletes one.

### Weekly drift audit

`.github/workflows/drift-audit.yml` runs `diff` every Monday and opens (or
comments on) a `fleet-drift` issue here when anything drifted. It can also
be started by hand from the Actions tab.

**Limit:** the audit's token is read-only, and GitHub hides eight
`repository.json` settings from read-only tokens: the three merge methods,
auto-merge, "Update branch", delete-branch-on-merge and the two squash
commit-message settings. The audit lists them as `unverified`. A local
`python3 scripts/fleet_settings.py diff`, run with your own login, checks
all of them.

### Tokens

One secret is needed: `FLEET_ADMIN_TOKEN`, set on this repo. It is a
fine-grained personal access token with **Administration: read** on every
repo in `repos.txt`, used by the weekly drift audit. It expires and must be
renewed by hand; once expired, the audit reports errors or `skipped` instead
of real results.

Releases and title checks need no token of their own; they run on each
repo's built-in `GITHUB_TOKEN`.

When adding a repo to `repos.txt`, also add it to `FLEET_ADMIN_TOKEN`'s
repository access.

## Checks on this repo

Everything here is shared, so a mistake merged to `main` reaches every repo
on its next push. Each PR to this repo must pass two required checks:

| Check | What it runs |
|---|---|
| `Lint and test` (`.github/workflows/ci.yml`) | The unit tests, `ruff check`, `ruff format --check` and `actionlint` on the workflows |
| `title / Conventional title` | The same title check every other repo uses |

To run the same checks locally (versions are pinned at the top of `ci.yml`):

```
python3 -m unittest discover tests
uvx ruff@0.17.6 check . && uvx ruff@0.17.6 format --check .
actionlint
```

`tests/test_baseline.py` loads the real files in `repo-defaults/` and
`repos.txt`, so a typo in the baseline fails on the PR instead of part-way
through an `apply`. It also holds the values chosen on purpose: `visibility`
is never managed, nobody bypasses the ruleset, and Actions must be pinned to
a commit. Changing one of those means changing that test too.

`.github/workflows/self-codeql.yml` scans this repo's scripts and workflows
with the shared CodeQL workflow, and `.github/dependabot.yml` keeps the
actions pinned in the shared workflows current.

This repo also releases through its own release workflow
(`.github/workflows/self-release.yml`). Each merge here is therefore a run of
the shared workflow before another repo uses it, and each release is a tag to
go back to if a change breaks releases elsewhere.

## Releases

`.github/workflows/release.yml` is the one release workflow for every repo.
Each PR is squash-merged, so a push to the default branch is one commit; the
workflow tags that commit and publishes a GitHub Release for it. There is no
release PR and no release commit:

```
feat: awesome feature 1   (tag: v0.1.0)
fix: oops                 (tag: v0.1.1)
chore(deps): bump x       (no tag)
```

| Commit type | Release |
|---|---|
| `type!:` or a `BREAKING CHANGE:` footer | major (minor while the repo is on 0.x) |
| `feat` | minor |
| `fix`, `perf` | patch |
| anything else (`chore`, `docs`, `ci`, ...) | none |

- The PR title becomes the squash commit message, so it decides the version.
- Following the SemVer spec, 0.x is initial development: a breaking change
  there bumps the minor. 1.0.0 is only ever cut by hand, with
  `gh release create v1.0.0 --generate-notes`; the workflow carries on from it.
- The biggest change since the last tag wins, so a skipped or failed run is
  picked up by the next one.
- The version lives in git tags only. No file in the repo is bumped, and
  release notes are on the repo's Releases page.
- The rules are `scripts/next_version.py`, tested by
  `tests/test_next_version.py`; the workflow runs those tests before every
  release.
- No file in a repo carries the version. `package.json` and `pyproject.toml`
  are set to `0.0.0`.

A repo opts in with a small caller and chains its own deploy on the `tag`
output:

```yaml
on:
  push:
    branches: [main]

jobs:
  release:
    permissions:
      contents: write
    uses: rae004/.github/.github/workflows/release.yml@<commit> # vX.Y.Z

  deploy:
    needs: release
    if: needs.release.outputs.tag != ''
    # the repo's own deploy, given needs.release.outputs.tag
```

### How repos reference the shared workflows

Every call to a shared workflow is pinned to the commit of a release of this
repo, with the version in a comment:

```yaml
uses: rae004/.github/.github/workflows/release.yml@5bc9b7d39611874852d144fc0bb668eb989bb4e8 # v0.1.0
```

- A change here reaches a repo only when that repo's pin is moved to a
  release that contains it. A bad merge here cannot break every repo at once.
- A change to a shared workflow, or to an action pinned inside one, must
  therefore be titled `feat` or `fix`. A `chore`, `ci` or `docs` title cuts
  no release, so no repo would ever pick the change up.
- To move a repo to a newer release, change the commit and the comment in
  its callers. Each repo's Dependabot config covers `github-actions`, which
  is meant to raise that PR.
- This repo calls its own shared workflows by local path
  (`./.github/workflows/...`), so it always runs what was just merged.

### PR title check

Because the title decides the version, `.github/workflows/pr-title.yml`
checks that every PR title is a Conventional Commit: `type: subject` or
`type(scope): subject`, with one of `feat`, `fix`, `perf`, `refactor`,
`docs`, `chore`, `test`, `ci`, `build`, `style`, `revert`. It uses the same
rules file as the release workflow and prints what merging would release.

A repo opts in with a caller, and lists the check as required in its
`.github/repo-settings.json`:

```yaml
on:
  pull_request:
    types: [opened, edited, synchronize, reopened]

jobs:
  title:
    uses: rae004/.github/.github/workflows/pr-title.yml@<commit> # vX.Y.Z
```

```json
{ "required_status_checks": ["title / Conventional title"] }
```

### Dependabot titles

Dependabot PRs follow the same rule through each repo's own
`.github/dependabot.yml` (GitHub has no shared one): runtime dependency bumps
are titled `fix(deps)` and cut a patch release, dev-only bumps are
`chore(deps-dev)`, and GitHub Actions bumps are `chore(deps)`.

## Code scanning

`.github/workflows/codeql.yml` is the one CodeQL workflow for every repo. It
sets what is the same everywhere:

- Workflow files are always scanned, on top of the repo's own languages.
- The query set is `security-and-quality`, CodeQL's widest built-in set.
- The CodeQL version, through the actions pinned in the workflow.

A repo passes only the languages its code is written in:

```yaml
on:
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: "0 9 * * 1"

permissions:
  contents: read

jobs:
  analyze:
    permissions:
      security-events: write
      contents: read
      actions: read
    uses: rae004/.github/.github/workflows/codeql.yml@<commit> # vX.Y.Z
    with:
      languages: '["python", "javascript-typescript"]'
```

Do not list `actions`; it is always added. A repo that must exclude paths
from the scan can pass `config-file` with the path to a CodeQL config file.
Results are under each repo's Security tab.

## Issue templates

- **Local agent task** (`.github/ISSUE_TEMPLATE/local-agent-task.md`) — pre-fills the
  YAML-frontmatter body that [rae-local-agent](https://github.com/rae004/rae-local-agent)'s
  issue poller parses, and applies the `local-agent` trigger label. It appears
  on every repo that has no issue templates of its own. Filing it only does
  something on repos the poller watches (listed in the machine-local
  `repos.yaml`) — those also carry the four `agent-*` labels, synced by
  `rae-local-agent`'s `scripts/polled_repo_labels.py`. On any other repo the
  label doesn't exist and the issue just sits there, unadopted.
