# Reusable adr-check workflow

`.github/workflows/adr-check.yml` runs [adr-check](https://pypi.org/project/adr-check/) over a
repository's architecture decision records. It installs the pinned version from PyPI with `uvx`, so
a caller needs no other action. Callers pin a release tag of this repository, so a fix lands here
once and reaches each repository when it moves its pin.

## Calling it

Create a workflow in the caller. It owns the triggers, because a reusable workflow cannot set them.
It also owns concurrency, because concurrency set in the called workflow would apply to every
caller.

```yaml
name: adr-check

on:
  pull_request:
    types: [opened, reopened, synchronize, edited, labeled, unlabeled]
  push:
    branches: [main]

concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

permissions:
  contents: read

jobs:
  adr-check:
    uses: agentic-delivery-au/shared-workflows/.github/workflows/adr-check.yml@v0.1.0
    with:
      adr-check-version: "0.1.1"
```

Pin the exact release tag. The README explains how Dependabot moves the pin.

`labeled` and `unlabeled` are needed because the `adr-correction` label allows a change to an
accepted ADR's body. Without them, adding the label leaves a stale failure until the next push.
`edited` covers a PR retargeted to another base branch.

## Inputs

| Input               | Type   | Default    | Purpose                                                                  |
| ------------------- | ------ | ---------- | ------------------------------------------------------------------------ |
| `adr-check-version` | string | required   | adr-check version on PyPI, for example `0.1.1`                           |
| `adr-dir`           | string | `docs/adr` | Directory that holds the ADRs                                            |
| `base-ref`          | string | `""`       | Ref to compare the ADRs with. Empty means `origin/<base branch>` on a PR |

## Pinning the version

`adr-check-version` has no default. The version has to match the `uvx adr-check==X` pre-commit hook
in the caller, or the hook and CI can disagree about the same ADR. A default here would be a second
copy that moves on this repository's release schedule rather than the caller's. Bump both together.
The workflow runs `uvx adr-check==<version>`, so the version is exact.

## What it runs

The workflow checks out the full history, because comparing with the base branch needs it. It then
sets flags from the event:

| Event                                | Flags                                                      |
| ------------------------------------ | ---------------------------------------------------------- |
| Pull request                         | `--mode ci --base-ref origin/<base> --labels <PR labels>`  |
| Pull request into the default branch | the above, plus `--merging-to-main`                        |
| Push to the default branch           | `--merging-to-main`, with file checks only: no `--mode ci` |
| Push to another branch               | file checks only: no flags                                 |
| Any other event, without `base-ref`  | fails, because there is nothing to compare with            |

A push never compares, because it has no PR labels, so comparing would fail every merged
`adr-correction`.

## The required check is `adr-check / adr-check`

A job that calls a reusable workflow reports `<caller job id> / <called job name>`. The called job
is named `adr-check`, so with the caller job above the check is `adr-check / adr-check`. Require
that name in the caller's ruleset. A ruleset that names anything else waits for a check that never
reports.

A caller switching from the adr-check GitHub Action must change its ruleset's required check from
`adr-check` to `adr-check / adr-check` in the same change that switches to this workflow. Until then
the old `adr-check` check never reports and PRs block.
