# Reusable pre-commit workflow

`.github/workflows/pre-commit.yml` runs every pre-commit hook in CI. Callers pin a release tag, so a
fix lands here once and reaches each repository when it moves its pin. This repository calls it by
local path.

## Calling it

Create a workflow in the caller. It owns the triggers, because a reusable workflow cannot set them.
It also owns concurrency, because concurrency set in the called workflow would apply to every
caller.

```yaml
name: pre-commit

on:
  pull_request:
    types: [opened, reopened, edited, synchronize]
  push:
    branches: [main]

concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

permissions:
  contents: read

jobs:
  pre-commit:
    uses: agentic-delivery-au/shared-workflows/.github/workflows/pre-commit.yml@v0.1.0
    with:
      node: true
```

Pin the exact release tag. The README explains how Dependabot moves the pin.

## Inputs

| Input             | Type    | Default  | Purpose                                                                            |
| ----------------- | ------- | -------- | ---------------------------------------------------------------------------------- |
| `node`            | boolean | `false`  | Set up Node and run `npm ci` before the hooks                                      |
| `node-version`    | string  | `"22"`   | Node version, used when `node` is true                                             |
| `python-version`  | string  | `"3.14"` | Python version pre-commit runs on                                                  |
| `uv`              | boolean | `false`  | Install uv and run `uv sync --locked` before the hooks                             |
| `uv-all-packages` | boolean | `false`  | Install uv and run `uv sync --all-packages --locked` instead, without needing `uv` |
| `uv-tool`         | boolean | `false`  | Install uv only, without `uv sync`, for hooks that run a tool through `uvx`        |

Set `node` when a hook is `language: system` and needs `node_modules` (for example, prettier). Set
`uv` when a hook shells out to uv (the Python templates' pyrefly).

Set `uv-all-packages` instead in uv workspace repos (`python-monorepo-template`,
`fullstack-simple-template`). Their root installs no members, so a plain sync leaves out the
packages pyrefly resolves imports against.

Set `uv-tool` in a repo with no Python project whose hooks call `uvx` (for example `adr-check`). It
installs uv and skips `uv sync`, which fails without a `pyproject.toml`.

A caller whose `.nvmrc` pins a version other than the `node-version` default must pass a matching
`node-version`. The workflow does not read `.nvmrc`, and the Node templates pin 24.

## The required check changes name

A job that calls a reusable workflow reports `<caller job id> / <called job name>`. The called job
is named `pre-commit`, so with the caller job above the check is `pre-commit / pre-commit`. Require
that name in the caller's ruleset in the same change that switches to this workflow. Until then the
old `pre-commit` check never reports and PRs block.

## Secret scanning needs the caller's hook config

The workflow has no scanning step of its own. It scans for secrets only through the caller's
`betterleaks` hook, and the hook shipped by default reads the staged diff. CI stages nothing, so
that diff is empty and the check passes having scanned nothing.

Override three hooks as agentic-delivery-au/base-template does, so each checks the files pre-commit
passes. This repo's `.pre-commit-config.yaml` has the same overrides:

```yaml
- id: check-merge-conflict
  args: [--assume-in-merge]
  stages: [pre-commit]
- id: check-added-large-files
  args: [--enforce-all]
  exclude: ^uv\.lock$
# ...
- id: betterleaks
  language_version: "1.27.0"
  entry: betterleaks dir --config .betterleaks.toml --no-banner --redact --verbose --
  pass_filenames: true
  stages: [pre-commit]
```

With these overrides the hooks check every committed file, not only staged ones:

- `check-merge-conflict` fails on any line that starts with seven `<` or `>` and a space, or is
  exactly `=======`, such as a heading underlined with seven `=` (as in
  agentic-delivery-au/base-template). `stages: [pre-commit]` keeps it, and betterleaks, out of
  `commit-msg`.
- `check-added-large-files` fails on any committed file over 500 KB, such as a generated lockfile or
  an image. Exclude it, move it to Git LFS, or raise `--maxkb`.
- `--config` must name a file that exists: betterleaks exits with an error when it does not, so the
  caller needs a `.betterleaks.toml` at its root.

One gap is accepted. The hook scans files as they stand, so a secret added and later removed within
a PR is not caught in CI. The local hook still catches it at commit time, unless someone uses
`--no-verify`.
