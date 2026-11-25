"""Tests for the reusable dependabot-auto-merge workflow: its gate, decision, and actions."""

import json
import os
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


def test_job_only_runs_for_dependabot_pr_and_actor():
    job = _workflow()["jobs"]["dependabot-auto-merge"]
    assert job["if"] == (
        "github.event.pull_request.user.login == 'dependabot[bot]'"
        " && github.actor == 'dependabot[bot]'"
    )


def test_decide_step_is_python_and_reads_fetch_metadata():
    step = _step("Decide")
    assert step["shell"] == "python"
    assert step["id"] == "decide"
    assert step["env"]["UPDATED_DEPENDENCIES"] == (
        "${{ steps.metadata.outputs.updated-dependencies-json }}"
    )
    assert _steps()[0]["id"] == "metadata"
    assert _steps()[0]["uses"].startswith("dependabot/fetch-metadata@v3")


def test_github_token_is_read_only_and_job_exposes_the_decision():
    workflow = _workflow()
    assert workflow["permissions"] == {"contents": "read", "pull-requests": "read"}
    job = workflow["jobs"]["dependabot-auto-merge"]
    assert job["outputs"] == {"decision": "${{ steps.decide.outputs.decision }}"}


def _by_id(step_id: str) -> dict:
    return next(s for s in _steps() if s.get("id") == step_id)


REVIEW_NAME = "Label for review"
MERGE_NAME = "Approve and arm auto-merge"


def test_secrets_are_declared_and_required():
    secrets = _workflow()[True]["workflow_call"]["secrets"]
    assert set(secrets) == {"app-client-id", "app-private-key"}
    for secret in secrets.values():
        assert secret["required"] is True
        assert secret["description"]


def test_token_step_is_scoped_to_this_repository():
    step = _by_id("app-token")
    assert step["uses"] == "actions/create-github-app-token@v3"
    assert step["with"] == {
        "client-id": "${{ secrets.app-client-id }}",
        "private-key": "${{ secrets.app-private-key }}",
        "permission-contents": "write",
        "permission-pull-requests": "write",
    }
    assert _steps().index(step) > _steps().index(_by_id("decide"))


def test_path_conditions():
    assert _step(REVIEW_NAME)["if"] == "steps.decide.outputs.decision != 'merge'"
    assert _step(MERGE_NAME)["if"] == "steps.decide.outputs.decision == 'merge'"


def test_no_run_script_interpolates_expressions():
    runs = [s["run"] for s in _steps() if "run" in s and s.get("shell") != "python"]
    assert runs
    assert not any("${{" in run for run in runs)


@pytest.mark.parametrize("name", [REVIEW_NAME, MERGE_NAME])
def test_path_steps_take_values_from_env(name):
    step = _step(name)
    assert step["env"] == {
        "GH_TOKEN": "${{ steps.app-token.outputs.token }}",
        "PR_URL": "${{ github.event.pull_request.html_url }}",
        "GH_REPO": "${{ github.repository }}",
        **({"HEAD_SHA": "${{ github.event.pull_request.head.sha }}"} if name == MERGE_NAME else {}),
    }
    assert "set -euo pipefail" in step["run"]


@pytest.fixture
def run_path(tmp_path):
    stub = tmp_path / "gh"
    log = tmp_path / "calls.txt"
    counter = tmp_path / "probes.txt"
    stub.write_text(
        "#!/bin/sh\n"
        f'echo "$*" >> "{log}"\n'
        'case "$1 $2" in\n'
        '  "pr view")\n'
        '    [ "${STUB_VIEW_FAIL:-}" = 1 ] && exit 1\n'
        '    case "$*" in\n'
        '      *labels*) echo "${STUB_LABELED:-false}" ;;\n'
        '      *) echo "${STUB_ARMED:-false}" ;;\n'
        "    esac ;;\n"
        '  "api repos/o/r/labels/needs-review")\n'
        f'    n=$(cat "{counter}" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "{counter}"\n'
        '    exit "$(echo "$STUB_PROBES" | cut -d" " -f"$n")" ;;\n'
        '  "label create") exit "${STUB_CREATE_EXIT:-0}" ;;\n'
        "esac\n"
    )
    stub.chmod(0o755)

    def run(
        name: str,
        *,
        armed: bool = False,
        probes: str = "0",
        create_exit: int = 0,
        view_fails: bool = False,
        labeled: bool = False,
        ok: bool = True,
    ) -> list[str]:
        env = {
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "PR_URL": "https://github.com/o/r/pull/1",
            "GH_TOKEN": "t",
            "GH_REPO": "o/r",
            "HEAD_SHA": "abc123",
            "STUB_ARMED": "true" if armed else "false",
            "STUB_LABELED": "true" if labeled else "false",
            "STUB_PROBES": probes,
            "STUB_CREATE_EXIT": str(create_exit),
            "STUB_VIEW_FAIL": "1" if view_fails else "0",
        }
        # The script is the workflow's own, read from the repo; bash is the runner's shell.
        result = subprocess.run(  # noqa: S603  # the workflow's own script
            ["/bin/bash", "-c", _step(name)["run"]],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert (result.returncode == 0) == ok, result.stderr
        return log.read_text().splitlines() if log.exists() else []

    return run


PR = "https://github.com/o/r/pull/1"


@pytest.mark.parametrize("armed", [True, False])
@pytest.mark.parametrize("label_exists", [True, False])
def test_review_path_never_approves_or_arms(run_path, armed, label_exists):
    calls = run_path(REVIEW_NAME, armed=armed, probes="0" if label_exists else "1")
    assert f"pr edit {PR} --add-label needs-review" in calls
    assert not any(c.startswith("pr review") or c.startswith("pr merge --auto") for c in calls)


def test_review_path_disarms_an_armed_auto_merge(run_path):
    calls = run_path(REVIEW_NAME, armed=True)
    assert f"pr merge --disable-auto {PR}" in calls


def test_review_path_leaves_unarmed_pr_alone(run_path):
    calls = run_path(REVIEW_NAME, armed=False)
    assert not any("--disable-auto" in c for c in calls)


def test_review_path_keeps_an_existing_label(run_path):
    calls = run_path(REVIEW_NAME, probes="0")
    assert not any(c.startswith("label create") for c in calls)


def test_review_path_creates_a_missing_label_without_force(run_path):
    creates = [c for c in run_path(REVIEW_NAME, probes="1") if c.startswith("label create")]
    assert len(creates) == 1
    assert creates[0].startswith("label create needs-review ")
    assert "--force" not in creates[0]


def test_review_path_tolerates_a_label_created_by_a_racing_run(run_path):
    calls = run_path(REVIEW_NAME, probes="1 0", create_exit=1)
    assert f"pr edit {PR} --add-label needs-review" in calls


def test_review_path_fails_when_label_create_really_fails(run_path):
    calls = run_path(REVIEW_NAME, probes="1 1", create_exit=1, ok=False)
    assert not any(c.startswith("pr edit") for c in calls)


def test_review_path_fails_loud_when_the_armed_check_fails(run_path):
    calls = run_path(REVIEW_NAME, view_fails=True, ok=False)
    assert not any(c.startswith(("pr edit", "pr merge --auto")) for c in calls)


def test_merge_path_approves_then_arms_auto_merge_pinned_to_head(run_path):
    assert run_path(MERGE_NAME) == [
        f'pr view {PR} --json labels --jq [.labels[].name] | index("needs-review") != null',
        f"pr review --approve {PR}",
        f"pr merge --auto --squash --match-head-commit abc123 {PR}",
    ]


def test_merge_path_skips_a_pr_labelled_needs_review(run_path):
    calls = run_path(MERGE_NAME, labeled=True)
    assert not any(c.startswith(("pr review", "pr merge")) for c in calls)


def test_merge_path_fails_loud_when_the_label_check_fails(run_path):
    calls = run_path(MERGE_NAME, view_fails=True, ok=False)
    assert not any(c.startswith(("pr review", "pr merge")) for c in calls)
