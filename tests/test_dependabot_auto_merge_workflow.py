"""Tests for the decision script in the reusable dependabot-auto-merge workflow."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "dependabot-auto-merge.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _steps() -> list[dict]:
    return _workflow()["jobs"]["dependabot-auto-merge"]["steps"]


def _step(name: str) -> dict:
    return next(s for s in _steps() if s.get("name") == name)


_MISSING = object()


def _dep(name: str, prev: object, new: object, ecosystem: str = "pip") -> dict:
    """One entry of fetch-metadata's updated-dependencies-json."""
    return {
        "dependencyName": name,
        "dependencyType": "direct:production",
        "updateType": "version-update:semver-patch",
        "directory": "/",
        "packageEcosystem": ecosystem,
        "targetBranch": "main",
        "prevVersion": prev,
        "newVersion": new,
        "compatScore": 0,
        "maintainerChanges": False,
        "dependencyGroup": "",
        "alertState": "",
        "ghsaId": "",
        "cvss": 0,
    }


@pytest.fixture
def decide(tmp_path):
    script = tmp_path / "decide.py"
    script.write_text(_step("Decide")["run"])
    output = tmp_path / "output.txt"

    def run(payload: object) -> str:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        output.write_text("")
        env = {"UPDATED_DEPENDENCIES": text, "GITHUB_OUTPUT": str(output)}
        # The script is the workflow's own, read from the repo.
        result = subprocess.run(  # noqa: S603  # the workflow's own script
            [sys.executable, str(script)], env=env, capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
        lines = output.read_text().splitlines()
        assert len(lines) == 1
        return lines[0].removeprefix("decision=")

    return run


@pytest.mark.parametrize(
    ("prev", "new", "expected"),
    [
        ("4.2.1", "4.2.2", "merge"),
        ("4.2.1", "4.3.0", "merge"),
        ("4.2.1", "5.0.0", "review"),
        ("0.4.2", "0.5.0", "review"),
        ("0.4.2", "0.4.3", "merge"),
        ("0.0.3", "0.0.4", "review"),
        ("0.0.3", "0.1.0", "review"),
        ("0.17.3", "0.17.5", "merge"),
        ("4", "5", "review"),
        ("v4", "v5", "review"),
        ("v4.2", "v4.3", "merge"),
        ("v4.2.1", "v4.2.2", "merge"),
        ("V4.2.1", "V4.3.0", "merge"),
        ("4.2", "4.2.1", "merge"),
        ("4", "4.1", "merge"),
        ("1.2.3", "1.2.3-rc.1", "review"),
        ("1.2.3-rc.1", "1.2.3", "review"),
        ("1.2.3", "1.2.4+build.5", "review"),
        ("24.0.1+incompatible", "24.0.2+incompatible", "review"),
        ("1.2.3", "1.2.3.4", "review"),
        ("3d9f1c2", "a1b2c3d", "review"),
        ("1.2.3", "main", "review"),
        ("1.2.3", "", "review"),
        ("", "1.2.4", "review"),
        ("1.2.3", None, "review"),
        (None, "1.2.4", "review"),
        ("1.2.3", 124, "review"),
        ("1.2.3", "1.2.3", "review"),
        ("v1.2", "1.2.0", "review"),
        ("1.2.4", "1.2.3", "review"),
        ("2.0.0", "1.9.9", "review"),
        ("1.2", "1.1", "review"),
    ],
)
def test_single_dependency(decide, prev, new, expected):
    assert decide([_dep("pkg", prev, new)]) == expected


def test_grouped_patch_and_major_is_review(decide):
    assert decide([_dep("a", "1.0.0", "1.0.1"), _dep("b", "2.0.0", "3.0.0")]) == "review"


@pytest.mark.parametrize("ecosystem", [_MISSING, "", "  ", None, 123, ["github_actions"]])
def test_unreadable_ecosystem_is_review(decide, ecosystem):
    dep = _dep("actions/checkout", "v4.2.1", "v4.2.2")
    if ecosystem is _MISSING:
        del dep["packageEcosystem"]
    else:
        dep["packageEcosystem"] = ecosystem
    assert decide([dep]) == "review"


def test_pip_patch_alone_is_merge(decide):
    assert decide([_dep("a", "1.0.0", "1.0.1", "pip")]) == "merge"


@pytest.mark.parametrize(
    "ecosystem", ["github_actions", "github-actions", "GitHub_Actions", "github"]
)
def test_github_actions_patch_is_review(decide, ecosystem):
    assert decide([_dep("actions/checkout", "v4.2.1", "v4.2.2", ecosystem)]) == "review"


def test_grouped_pip_patch_and_github_actions_patch_is_review(decide):
    deps = [
        _dep("a", "1.0.0", "1.0.1"),
        _dep("actions/checkout", "v4.2.1", "v4.2.2", "github_actions"),
    ]
    assert decide(deps) == "review"


def test_grouped_patch_and_minor_is_merge(decide):
    assert decide([_dep("a", "1.0.0", "1.0.1"), _dep("b", "2.0.0", "2.1.0")]) == "merge"


def test_grouped_with_one_unreadable_version_is_review(decide):
    assert decide([_dep("a", "1.0.0", "1.0.1"), _dep("b", "", "2.1.0")]) == "review"


def test_same_package_twice_in_one_group(decide):
    deps = [_dep("picomatch", "2.3.1", "2.3.2"), _dep("picomatch", "4.0.1", "4.0.2")]
    assert decide(deps) == "merge"


def test_security_update_follows_the_same_rules(decide):
    security = {"alertState": "OPEN", "ghsaId": "GHSA-xxxx-xxxx-xxxx", "cvss": 7.5}
    patch = {**_dep("a", "1.0.0", "1.0.1"), **security}
    major = {**_dep("a", "1.0.0", "2.0.0"), **security}
    assert decide([patch]) == "merge"
    assert decide([major]) == "review"


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "",
        "{}",
        '{"prevVersion": "1.0.0"}',
        "[]",
        "null",
        '"x"',
        "[1]",
        "[null]",
        "[{}]",
    ],
)
def test_malformed_payload_is_review(decide, payload):
    assert decide(payload) == "review"


def test_missing_env_is_review(tmp_path):
    script = tmp_path / "decide.py"
    script.write_text(_step("Decide")["run"])
    output = tmp_path / "output.txt"
    result = subprocess.run(  # noqa: S603  # the workflow's own script
        [sys.executable, str(script)],
        env={"GITHUB_OUTPUT": str(output)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert output.read_text() == "decision=review\n"


def test_logs_one_line_per_dependency(tmp_path):
    script = tmp_path / "decide.py"
    script.write_text(_step("Decide")["run"])
    env = {
        "UPDATED_DEPENDENCIES": json.dumps(
            [_dep("a", "1.0.0", "1.0.1"), _dep("b", "2.0.0", "3.0.0")]
        ),
        "GITHUB_OUTPUT": str(tmp_path / "output.txt"),
    }
    result = subprocess.run(  # noqa: S603  # the workflow's own script
        [sys.executable, str(script)], env=env, capture_output=True, text=True, check=False
    )
    lines = result.stdout.splitlines()
    assert len(lines) == 2
    assert "a" in lines[0] and "1.0.0 → 1.0.1" in lines[0] and "merge" in lines[0]
    assert "b" in lines[1] and "2.0.0 → 3.0.0" in lines[1] and "review" in lines[1]


def test_workflow_never_checks_out_code():
    uses = [s.get("uses", "") for s in _steps()]
    assert not any(u.startswith("actions/checkout") for u in uses)


def test_job_only_runs_for_dependabot():
    job = _workflow()["jobs"]["dependabot-auto-merge"]
    assert job["if"] == "github.event.pull_request.user.login == 'dependabot[bot]'"


def test_decide_step_is_python_and_reads_fetch_metadata():
    step = _step("Decide")
    assert step["shell"] == "python"
    assert step["id"] == "decide"
    assert step["env"]["UPDATED_DEPENDENCIES"] == (
        "${{ steps.metadata.outputs.updated-dependencies-json }}"
    )
    assert _steps()[0]["id"] == "metadata"
    assert _steps()[0]["uses"].startswith("dependabot/fetch-metadata@v3")


def test_workflow_is_read_only_and_exposes_the_decision():
    workflow = _workflow()
    assert workflow["permissions"] == {"contents": "read", "pull-requests": "read"}
    job = workflow["jobs"]["dependabot-auto-merge"]
    assert job["outputs"] == {"decision": "${{ steps.decide.outputs.decision }}"}
