# Reusable dependabot-auto-merge workflow

`.github/workflows/dependabot-auto-merge.yml` approves and auto-merges low-risk Dependabot updates
and labels the rest `needs-review`. Callers pin a release tag, so a fix lands here once and reaches
each repository when it moves its pin.

## Calling it

Create a workflow in the caller. It owns the triggers, because a reusable workflow cannot set them.
It also owns concurrency, because concurrency set in the called workflow would apply to every
caller.

```yaml
name: dependabot-auto-merge

on:
  pull_request:
    types: [opened, reopened, synchronize]

concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

permissions:
  contents: read
  pull-requests: read

jobs:
  dependabot-auto-merge:
    uses: agentic-delivery-au/shared-workflows/.github/workflows/dependabot-auto-merge.yml@v0.1.0
    secrets:
      app-client-id: ${{ secrets.AUTO_MERGE_APP_CLIENT_ID }}
      app-private-key: ${{ secrets.AUTO_MERGE_APP_PRIVATE_KEY }}
```

Pin the exact release tag. The README explains how Dependabot moves the pin.

`pull-requests: read` is required. fetch-metadata lists the PR's commits, and a called workflow
cannot hold more than its caller grants, so leaving it out fails the run.

`AUTO_MERGE_APP_CLIENT_ID` and `AUTO_MERGE_APP_PRIVATE_KEY` must be org-level **Dependabot**
secrets, not Actions secrets, because a Dependabot-triggered run sees only Dependabot secrets.

## Secrets

The workflow has no inputs.

| Secret            | Purpose                                  |
| ----------------- | ---------------------------------------- |
| `app-client-id`   | Client ID of the auto-merge GitHub App   |
| `app-private-key` | Private key of the auto-merge GitHub App |

## What it decides

| Update                                                                                                                       | Decision                                         |
| ---------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| Patch or minor                                                                                                               | merge                                            |
| Major                                                                                                                        | review                                           |
| On `0.x`: a minor                                                                                                            | review                                           |
| On `0.x`: a patch                                                                                                            | merge                                            |
| Any `0.0.x` change                                                                                                           | review                                           |
| A grouped PR                                                                                                                 | the biggest bump; any review makes the PR review |
| A security update                                                                                                            | the same rules                                   |
| Any GitHub Actions dependency                                                                                                | review                                           |
| Anything unreadable: SHAs, prereleases or build suffixes, a missing or unreadable version or ecosystem, downgrades, bad JSON | review                                           |

GitHub Actions updates go to review because the App holds no Workflows permission, and GitHub
refuses an App merge of a PR that edits `.github/workflows/`.

## What it does

The job runs only when both the PR's author and the triggering actor are `dependabot[bot]`. It never
checks out PR code.

- **Merge:** skips if the PR is already labelled `needs-review`. Otherwise it approves, then arms
  squash auto-merge pinned to the head commit that was decided on.
- **Review:** turns off an auto-merge an earlier run armed, creates the `needs-review` label if it
  is missing (an existing label is left alone), and adds the label.

## Opting a repo in

- Required approving reviews are 0.
- The repo's tests are a **required status check** on the default branch. Without one, auto-merge
  merges immediately, before tests finish, so a failing update can land.
- The repo setting **Allow auto-merge** is on. Without it, the arm step fails after approving.
- The caller workflow above is added.
- The repo is added to the App's installation and to the Dependabot secrets' repository list.

[#9](https://github.com/agentic-delivery-au/shared-workflows/issues/9) covers creating the App:
Contents read/write, Pull requests read/write and Metadata read, installed only on opted-in repos.

## The check name

The check reports as `<caller job> / dependabot-auto-merge`, so
`dependabot-auto-merge / dependabot-auto-merge` with the caller above. Do not make it a required
check: it is skipped on every PR that is not from Dependabot.

## Releases

In a repo whose releases come from Conventional Commit types, an auto-merged Dependabot PR keeps its
`chore(deps)` title, so it never cuts a release, even when it bumps something callers use. Such a
repo should exclude those ecosystems, or accept that the bumps ship with the next release.

## Out of scope

- PRs not opened by Dependabot.
- Notifications.
- Repos that require reviews or code owner approval.

## Known limits

- Multi-ecosystem groups: [#12](https://github.com/agentic-delivery-au/shared-workflows/issues/12).
- The approval is not pinned to the head, and a non-Dependabot push skips the disarm:
  [#13](https://github.com/agentic-delivery-au/shared-workflows/issues/13).
