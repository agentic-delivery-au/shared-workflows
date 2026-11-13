# shared-workflows

Reusable CI workflows for agentic-delivery-au repositories. Repos call them and pin to a release, so
a fix lands once and reaches each repo when it moves its pin.

The repo's toolchain is pre-commit, Ruff, pytest, Conventional Commits and release-please. This
README covers what differs from the templates and keeps the Python setup the repo still uses.

## What it provides

| Item                         | Path                               |
| ---------------------------- | ---------------------------------- |
| Reusable pre-commit workflow | `.github/workflows/pre-commit.yml` |
| Reusable adr-check workflow  | `.github/workflows/adr-check.yml`  |

`.github/workflows/pre-commit.yml` is the reusable workflow.
[Its inputs and the check name are in `docs/pre-commit-workflow.md`](docs/pre-commit-workflow.md).
This repo's own CI is `.github/workflows/pre-commit-ci.yml`, which calls the reusable workflow
locally. The required check here is `pre-commit / pre-commit`.

`.github/workflows/adr-check.yml` is the reusable workflow that runs the ADR check from PyPI.
[Its inputs and the check name are in `docs/adr-check-workflow.md`](docs/adr-check-workflow.md).

An ADR is an architecture decision record. The check is
[adr-check](https://github.com/agentic-delivery-au/adr-check).

## Using it from another repo

A caller can use a reusable workflow once a release that includes it is tagged. It pins an exact
release tag, which release-please creates in the form `vX.Y.Z`. The same applies to both reusable
workflows, `pre-commit.yml` and `adr-check.yml`:

```yaml
jobs:
  pre-commit:
    uses: agentic-delivery-au/shared-workflows/.github/workflows/pre-commit.yml@v0.1.0
```

The pre-commit inputs are in [`docs/pre-commit-workflow.md`](docs/pre-commit-workflow.md) and the
adr-check inputs are in [`docs/adr-check-workflow.md`](docs/adr-check-workflow.md). There is no
floating major tag, so a release never changes a caller until the caller moves its pin. Dependabot
moves it. Every template's `dependabot.yml` has the `github-actions` ecosystem, which covers `uses:`
references to reusable workflows. The bump PR runs the caller's own CI.

One condition has to hold: **the caller's ruleset must require the right check name.** A
reusable-workflow job reports as `<caller job> / <called job>`, for example `lint / pre-commit`. A
ruleset that still requires the old job name waits for a check that never reports. Change the
ruleset in the same PR that switches to the shared workflow.

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```bash
uv sync             # create .venv and install the dev dependencies
pre-commit install  # one-time, sets up the pre-commit and commit-msg hooks
```

`requires-python` in `pyproject.toml` is `>=3.14`. It is a lower bound, so uv may select a newer
interpreter. Ruff infers its `target-version` from it.

| Task                       | Command                      |
| -------------------------- | ---------------------------- |
| Run the tests              | `uv run pytest`              |
| Lint                       | `uv run ruff check .`        |
| Format                     | `uv run ruff format .`       |
| Everything the hooks check | `pre-commit run --all-files` |

### Tests

`uv run pytest` runs the suite, the same run `tests.yml` makes in CI. The tests check the branching
in the reusable adr-check workflow's run script.

The ruleset requires four checks: `Validate PR title`, `adr-check / adr-check`,
`pre-commit / pre-commit` and `pytest`. `adr-check / adr-check` and `pre-commit / pre-commit` are
the caller job id and the called job name, from `adr-check-pr.yml` and `pre-commit-ci.yml`, which
run this repo's own reusable workflows. `pytest` is the job id in `tests.yml`.
`scripts/bootstrap_repo.py` lists the same strings. Rename one without the other and the check never
reports, which blocks every pull request.

### `scripts/`

`scripts/bootstrap_repo.py` and its tests arrive with base-template. Ruff skips them through
`extend-exclude`. Checking them here would invite local fixes that diverge from upstream.

## Repository settings

Creating a repo from a template copies files and nothing else. A new repo starts with no branch
protection, GitHub's default merge settings, and the Actions permission release-please needs
switched off. `scripts/bootstrap_repo.py` applies them. It prints a plan and changes nothing until
you pass `--apply`. It needs gh 2.48 or later.

```bash
python3 scripts/bootstrap_repo.py            # what it would change
python3 scripts/bootstrap_repo.py --apply    # change it
```

The script requires `pre-commit / pre-commit` and `adr-check / adr-check`, the same names this
repo's workflows report, so re-running it is safe for those checks.

Read the plan first. Applying replaces an existing ruleset wholesale, so a `-` line is policy this
repo has and the template does not, and applying loses it.

### Release bot (GitHub App)

`release-please.yml` authenticates as a GitHub App rather than with `GITHUB_TOKEN`, because a pull
request opened with `GITHUB_TOKEN` triggers no workflows: the checks the ruleset requires would
never report on the release PR, and it could never merge.

**Do this before merging anything that runs the workflow.** There is deliberately no fallback to
`GITHUB_TOKEN` — a silent downgrade would reintroduce the unmergeable release PR — so until the App
exists and both credentials are set, every push to `main` fails at the token step.

1. Create the App under the organisation: Settings → Developer settings → GitHub Apps → New. It
   needs no webhook and no callback URL.
1. Grant it exactly three repository permissions: **Contents** write, **Issues** write, **Pull
   requests** write. Nothing else.
1. Install it (App settings → Install App) on the repositories that cut releases.
1. Generate a private key (App settings → Private keys) and download the `.pem`.
1. Store both credentials on the repository, under Settings → Secrets and variables → Actions:
   `RELEASE_BOT_CLIENT_ID` as a **variable**, and `RELEASE_BOT_PRIVATE_KEY` as a **secret** holding
   the whole `.pem`, `BEGIN` and `END` lines included.

The token is narrowed three times over, and the middle one is the one that gets missed:

- The App's own permissions are the ceiling. It can never mint a token holding more than the three
  granted in step 2, whatever a workflow asks for.
- `permission-contents`, `permission-issues` and `permission-pull-requests` on the token step narrow
  each run to release-please's documented minimum. Omit them and the token inherits **every**
  permission the installation holds — the ceiling becomes the grant.
- No `owner` or `repositories` input, so the token reaches only the repository running the workflow.
  The action revokes it when the job finishes, and it expires within the hour regardless.

`permissions: {}` at the top of the workflow then leaves `GITHUB_TOKEN` itself with nothing, since
the App token does all the work.

## Releasing

[release-please](https://github.com/googleapis/release-please) reads the Conventional Commits landed
on `main` and keeps an open release PR that bumps the version and updates `CHANGELOG.md`. Merging
that PR tags the release as `vX.Y.Z` and publishes the GitHub release. Those tags are what callers
pin.

Release-please decides from each commit's type, not from which files changed. `ci:`, `chore:`,
`docs:`, `test:`, `refactor:` and `style:` never release, and the PR title is the squash commit's
subject. In most repos a workflow change is `ci:`, but here the workflows are the product, and `ci:`
never releases. So pick the type by who uses the change:

| Change                                                                             | Type                                                           |
| ---------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| Anything callers use: a reusable workflow                                          | `feat:` or `fix:`; `feat!:` when callers must change something |
| This repo's own tooling: its caller workflows, dev dependencies, the template's CI | `ci:` or `chore:`, which do not release                        |

A fix to a reusable workflow titled `ci:` merges and never reaches a caller.

Dependabot titles its PRs `chore(deps)`, which does not release. When a bump touches something
callers use, such as an action pinned inside a reusable workflow, retitle the PR `fix(deps):` before
merging, so the bump reaches callers.

`release-please.yml` authenticates as a GitHub App, so the release PR triggers the checks the
ruleset requires. It reads a `RELEASE_BOT_CLIENT_ID` variable and a `RELEASE_BOT_PRIVATE_KEY`
secret. Without both, every push to `main` fails at the token step.

`release-please-config.json` keeps the `shared-workflows` entry in `uv.lock` at the release version,
through `extra-files`. A change that renames the project updates that entry too.
