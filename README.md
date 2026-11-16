# .github

Default [community health files](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/creating-a-default-community-health-file)
and fleet-wide repository settings for all `rae004` repositories.

## Fleet settings as code

GitHub has no native user-level defaults for repo *settings*, so this repo
carries them as code (same pattern as `rae-local-chat`'s and
`rae-local-agent`'s in-repo `.github/repo/` folders, extended across repos):

- `repo-defaults/` — the universal baseline, as verbatim REST API bodies:
  merge policy (squash/rebase only, auto-merge, branch cleanup), Dependabot
  security updates, Actions token defaults, and a baseline `main` ruleset
  (PR required, linear history, no deletions — **no** required status
  checks, since check names are per-repo). `visibility` is deliberately
  absent so an apply can never flip a private repo public.
- `overrides/<repo>/<file>` — whole-file replacement of a default for one
  repo (e.g. a ruleset with that repo's required checks).
- `repos.txt` — the explicit fleet list. **Hybrid rule:** a repo with its
  own `.github/repo/` folder (currently `rae-local-agent`, `rae-local-chat`)
  is self-managed and skipped automatically.

```
python3 scripts/fleet_settings.py diff     # exit 1 on drift anywhere
python3 scripts/fleet_settings.py apply    # push the baseline (needs admin)
```

`scripts/repo_settings.py` is the shared engine (verbatim copy of the
in-repo original); `fleet_settings.py` drives it across `repos.txt`.

### Weekly drift audit

`.github/workflows/drift-audit.yml` runs the fleet diff every Monday and
opens (or comments on) a `fleet-drift` issue here when anything drifted.
It needs a `FLEET_ADMIN_TOKEN` secret — a fine-grained PAT with
**Administration: read** on all fleet repos — to read rulesets and Actions
permissions; without it most targets report `skipped`. Applying is always
done locally.

## Issue templates

- **Local agent task** (`.github/ISSUE_TEMPLATE/local-agent-task.md`) — pre-fills the
  YAML-frontmatter body that [rae-local-agent](https://github.com/rae004/rae-local-agent)'s
  issue poller parses, and applies the `local-agent` trigger label. It appears
  on every repo that has no issue templates of its own. Filing it only does
  something on repos the poller watches (listed in the machine-local
  `repos.yaml`) — those also carry the four `agent-*` labels, synced by
  `rae-local-agent`'s `scripts/polled_repo_labels.py`. On any other repo the
  label doesn't exist and the issue just sits there, unadopted.
