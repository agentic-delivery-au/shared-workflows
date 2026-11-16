"""Tests for the branching in the reusable adr-check workflow's run script."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "adr-check.yml"
BASE_ARGS = ["adr-check==0.1.1", "--adr-dir", "docs/adr"]


def _step() -> dict:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    steps = workflow["jobs"]["adr-check"]["steps"]
    return next(s for s in steps if s.get("name") == "Run adr-check")


@pytest.fixture
def run_script(tmp_path):
    stub = tmp_path / "uvx"
    log = tmp_path / "args.txt"
    stub.write_text(f'#!/bin/sh\nprintf \'%s\\n\' "$@" > "{log}"\n')
    stub.chmod(0o755)
    script = _step()["run"]

    def run(**env):
        full_env = {
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "ADR_CHECK_VERSION": "0.1.1",
            "ADR_DIR": "docs/adr",
            "BASE_REF": "",
            "EVENT_NAME": "pull_request",
            "MERGING_TO_MAIN": "false",
            "LABELS": "[]",
            **env,
        }
        # The script is the workflow's own, read from the repo; bash is the runner's shell.
        result = subprocess.run(  # noqa: S603
            ["/bin/bash", "-c", script], env=full_env, capture_output=True, text=True, check=False
        )
        args = log.read_text().splitlines() if log.exists() else None
        return result, args

    return run


def test_pull_request_into_default_branch(run_script):
    result, args = run_script(
        EVENT_NAME="pull_request",
        MERGING_TO_MAIN="true",
        BASE_REF="origin/main",
        LABELS='["x"]',
    )
    assert result.returncode == 0
    assert args == [
        *BASE_ARGS,
        "--merging-to-main",
        "--mode",
        "ci",
        "--base-ref",
        "origin/main",
        "--labels",
        '["x"]',
    ]


def test_pull_request_into_other_branch(run_script):
    result, args = run_script(
        EVENT_NAME="pull_request",
        MERGING_TO_MAIN="false",
        BASE_REF="origin/develop",
        LABELS='["x"]',
    )
    assert result.returncode == 0
    assert args == [
        *BASE_ARGS,
        "--mode",
        "ci",
        "--base-ref",
        "origin/develop",
        "--labels",
        '["x"]',
    ]


def test_push_to_default_branch(run_script):
    result, args = run_script(EVENT_NAME="push", MERGING_TO_MAIN="true", BASE_REF="")
    assert result.returncode == 0
    assert args == [*BASE_ARGS, "--merging-to-main"]
    assert "::notice::" in result.stdout


def test_push_to_other_branch(run_script):
    result, args = run_script(EVENT_NAME="push", MERGING_TO_MAIN="false", BASE_REF="")
    assert result.returncode == 0
    assert args == BASE_ARGS


def test_non_push_event_without_base_ref_fails(run_script):
    result, args = run_script(EVENT_NAME="workflow_dispatch", BASE_REF="")
    assert result.returncode == 1
    assert "::error::base-ref is empty" in result.stdout
    assert args is None


def test_env_expressions_keep_their_pieces():
    env = _step()["env"]
    assert "format('origin/{0}', github.base_ref)" in env["BASE_REF"]
    assert "github.event.repository.default_branch" in env["MERGING_TO_MAIN"]
    assert "toJSON(github.event.pull_request.labels.*.name)" in env["LABELS"]


def test_own_caller_passes_the_pre_commit_pin():
    """This repo checks its own ADRs through the reusable workflow, at the hook's version."""
    root = WORKFLOW.parent.parent.parent
    caller = yaml.safe_load((root / ".github" / "workflows" / "adr-check-pr.yml").read_text())
    job = caller["jobs"]["adr-check"]
    hooks = yaml.safe_load((root / ".pre-commit-config.yaml").read_text())["repos"]
    entry = next(h["entry"] for r in hooks for h in r["hooks"] if h["id"] == "adr-check")
    assert job["uses"] == "./.github/workflows/adr-check.yml"
    assert entry == f"uvx adr-check=={job['with']['adr-check-version']}"


def test_own_caller_reruns_on_label_and_retarget():
    """Adding adr-correction or retargeting the PR re-runs the check, not leaving a stale result."""
    root = WORKFLOW.parent.parent.parent
    caller = yaml.safe_load((root / ".github" / "workflows" / "adr-check-pr.yml").read_text())
    types = caller[True]["pull_request"]["types"]
    assert {"labeled", "unlabeled", "edited"} <= set(types)
