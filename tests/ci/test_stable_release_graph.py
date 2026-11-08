"""The source-only release workflows enforce publication ordering.

A stable release ships source (annotated tags + the GitHub release), the Docker
image and the source-install gates. There is no desktop bundle, update feed,
Store submission or packaged E2E in the graph any more.
"""
import ast
import json
import re
from pathlib import Path

import pytest

from ruamel.yaml import YAML

from scripts.releases import lanes as lane_set

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"
RELEASE_WORKFLOWS = ("stable-release.yml", "stable-release-publication.yml", "canary-release.yml")


def workflow(name):
    return YAML(typ="base").load((WORKFLOWS / name).read_text(encoding="utf-8"))


def direct_needs(jobs, name):
    needs = jobs[name].get("needs", [])
    return [needs] if isinstance(needs, str) else needs


def ancestors(jobs, name):
    seen = set()
    pending = [name]
    while pending:
        needs = jobs[pending.pop()].get("needs", [])
        for item in [needs] if isinstance(needs, str) else needs:
            if item not in seen:
                seen.add(item)
                pending.append(item)
    return seen


def gate(expression, inputs, needs, *, github=None):
    """Evaluate the workflow expression subset, including Actions' implicit success().

    Handles the bracket subscript form (``fromJSON(...)['job']``) that the
    lane flags use; anything else stays a plain boolean expression.
    """
    expression = str(expression).strip().removeprefix("${{").removesuffix("}}").strip()
    if not re.search(r"\b(always|cancelled|success|failure)\(", expression):
        if any(row.get("result") != "success" for row in needs.values()):
            return False

    def value(match):
        result = {"inputs": inputs, "needs": needs, "github": github or {}}
        for bit in match[0].split("."):
            result = result.get(bit, "") if isinstance(result, dict) else ""
        return repr(result)

    expression = re.sub(r"\b(?:inputs|needs|github)(?:\.[\w-]+)+", value, expression)
    expression = expression.replace("&&", " and ").replace("||", " or ")
    expression = re.sub(r"!(?!=)", " not ", expression)
    expression = re.sub(r"\btrue\b", "True", expression)
    expression = re.sub(r"\bfalse\b", "False", expression)
    return eval("(" + expression.strip() + ")", {"__builtins__": {}}, {
        "always": lambda: True, "cancelled": lambda: False,
        "success": lambda: True, "failure": lambda: False,
        "contains": lambda value, needle: needle in value,
        "fromJSON": ast.literal_eval,
    })


def test_admit_can_read_the_claim_draft():
    jobs = workflow("stable-release.yml")["jobs"]
    assert jobs["admit"]["permissions"]["contents"] == "write"


def test_release_reuses_whole_ci_and_docker_before_publication():
    jobs = workflow("stable-release.yml")["jobs"]
    assert jobs["ci"]["uses"] == "./.github/workflows/ci.yaml"
    assert jobs["ci"]["with"]["release"] == "true"
    assert "secrets" not in jobs["ci"]
    assert jobs["docker"]["uses"] == jobs["publish-docker"]["uses"]
    assert jobs["docker"]["with"]["release-phase"] == "test"
    # Every gate starts straight after admit; the acceptance join is what waits for CI.
    for parallel in ("docker", "nix", "pm-bundle", "windows-live", "install-e2e"):
        assert direct_needs(jobs, parallel) == ["admit"], parallel
    required = {"ci", "docker", "nix", "pm-bundle", "windows-live", "install-e2e"}
    assert required <= ancestors(jobs, "acceptance")
    # publish-docker starts when the docker tests pass; it does not wait for acceptance.
    assert jobs["publish-docker"]["needs"] == ["admit", "docker"]
    assert "acceptance" not in ancestors(jobs, "publish-docker")
    assert jobs["publication"]["needs"] == ["admit", "acceptance", "publish-docker"]
    assert {"admit", "ci", "docker", "acceptance", "publication", "publish-docker"} <= ancestors(jobs, "complete")
    # The gates must run to judge a failed or skipped prerequisite, not skip with it.
    for name in ("acceptance", "publication", "complete"):
        failed = {need: {"result": "failure"} for need in ancestors(jobs, name)}
        assert gate(jobs[name]["if"], {}, failed), name


def test_the_graph_is_source_only():
    jobs = workflow("stable-release.yml")["jobs"]
    assert set(jobs) == {
        "admit", "ci", "docker", "nix", "pm-bundle", "windows-live", "install-e2e",
        "acceptance", "publish-docker", "publication", "complete",
    }
    # No desktop packaging, Store submission, candidate or transition job survives.
    gone = {"candidates", "candidate-manifest", "transitions", "windows-packaged",
            "macos-packaged-arm64", "bootstrap-version", "publish-bundles",
            "termux-checks", "windows-store"}
    for name in jobs:
        assert not any(name.startswith(prefix) for prefix in gone), name
    for job in jobs.values():
        uses = job.get("uses", "")
        assert "desktop-bundled-release.yml" not in uses, uses
        assert "desktop-bundle-smoke.yml" not in uses, uses


def test_the_release_workflows_name_no_desktop_or_r2_machinery():
    forbidden = (
        "CLOUDFLARE_R2", "MS_STORE", "DOCKER_MANIFEST_DIGEST", "candidate-manifest",
        "publish-bundles", "candidates-", "transitions-", "windows-packaged",
        "macos-packaged", "bootstrap-version", "render-builds-table", "ruamel",
        "desktop-bundled-release.yml", "desktop-bundle-smoke.yml", "windows-store",
        "termux-checks", "baseline-manifest", "hermes_yaml",
    )
    for name in RELEASE_WORKFLOWS:
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{name} still names {token}"


LANE_SETS = {
    "default": lane_set.DEFAULT,
    "everything": frozenset(lane_set.NAMES),
    "docker only": lane_set.select(only=["docker"]),
    "no docker": lane_set.select(without=["docker"]),
    "no tests": lane_set.select(only=["docker"]),
    "nothing": frozenset(),
    # Each lane alone and each lane missing, so no job's condition can borrow another lane's flag.
    **{f"only {name}": frozenset({name}) for name in lane_set.NAMES},
    **{f"everything but {name}": frozenset(lane_set.NAMES) - {name} for name in lane_set.NAMES},
}


@pytest.mark.parametrize("lanes", LANE_SETS.values(), ids=LANE_SETS)
def test_every_lane_controlled_job_runs_exactly_when_the_lane_table_says(lanes):
    """The workflow's `if` conditions and the gate's expectations describe the same graph."""
    jobs = workflow("stable-release.yml")["jobs"]
    runs = lane_set.jobs_to_run(lanes)
    admit = {"result": "success", "outputs": {"lanes": json.dumps(lane_set.flags(lanes)),
                                              "jobs": json.dumps(runs)}}

    def result(name):
        if name == "admit":
            return admit
        # What the job does under these lanes is what the table says (a job outside it never skips).
        return {"result": "success" if runs.get(name, True) else "skipped"}

    for name, wanted in runs.items():
        assert name in jobs, name
        needs = {need: result(need) for need in direct_needs(jobs, name)}
        assert gate(jobs[name].get("if", "true"), {}, needs) == wanted, (name, sorted(lanes))
    # A job that is not lane-controlled never skips with the lanes.
    for name in set(jobs) - set(runs) - {"admit", "acceptance", "publication", "complete"}:
        assert "outputs.jobs" not in str(jobs[name].get("if", "")), name


def test_lane_inputs_reach_the_workflows_they_configure():
    jobs = workflow("stable-release.yml")["jobs"]
    assert jobs["docker"]["with"]["skip-tests"] == \
        "${{ !fromJSON(needs.admit.outputs.lanes)['docker-tests'] }}"
    assert "skip-signed" not in jobs["docker"]["with"]
    assert "skip-store" not in str(jobs["docker"]["with"])
    assert {"lanes", "jobs"} <= set(jobs["admit"]["outputs"])
    for name in ("acceptance", "publication", "complete"):
        gate_step = next(step for step in jobs[name]["steps"]
                         if "scripts.releases.stable gate" in step.get("run", ""))
        assert gate_step["env"] == {"RELEASE_NEEDS": "${{ toJSON(needs) }}",
                                    "LANES": "${{ needs.admit.outputs.lanes }}"}
        gated = gate_step["run"].split(" gate ", 1)[1].split()
        assert set(gated) <= set(direct_needs(jobs, name)), name


def test_admit_emits_the_same_lanes_and_jobs_the_gate_reads(tmp_path):
    from unittest import mock

    from scripts.releases import stable

    output = tmp_path / "output"
    summary = tmp_path / "summary"
    admitted = {"claim_tag": "rc.1-v1.2.3", "claim_object": "a" * 40, "tag": "v1.2.3", "commit": "b" * 40,
                "version": "1.2.3", "attempt": 1, "claim_epoch": 1, "autopublish": False,
                "lanes": lane_set.select(only=["docker", "ci"])}
    env = {"GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(summary), "GITHUB_REPOSITORY": "o/r"}
    with mock.patch.object(stable, "check_claim", return_value=admitted), \
            mock.patch.object(stable, "output", return_value=json.dumps(
                {"tagName": "rc.1-v1.2.3", "isDraft": True, "isPrerelease": False, "databaseId": 7})):
        stable.admit(env)
    emitted = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
    assert lane_set.from_flags(json.loads(emitted["lanes"])) == admitted["lanes"]
    assert json.loads(emitted["jobs"]) == lane_set.jobs_to_run(admitted["lanes"])
    assert "on: docker, ci" in summary.read_text(encoding="utf-8")


def test_claim_custody_and_final_payload_identity_reach_every_privileged_phase():
    release = workflow("stable-release.yml")
    jobs = release["jobs"]
    # The claim is the one record of the attempt's policy; a dispatch cannot override it.
    inputs = set(release["on"]["workflow_dispatch"]["inputs"])
    assert inputs == {"tag"}
    assert {"claim-tag", "claim-object", "tag", "commit", "version", "release-id", "release-epoch"} <= \
        set(jobs["admit"]["outputs"])
    for name in ("docker", "nix"):
        assert jobs[name]["with"]["version"] == "${{ needs.admit.outputs.version }}"
    assert "version" not in jobs["pm-bundle"]["with"]
    for name in ("docker", "publish-docker"):
        assert jobs[name]["with"]["tag"] == "${{ needs.admit.outputs.claim-tag }}"
    complete = jobs["complete"]["steps"]
    assert not any("Create the final tag" in step.get("name", "") for step in complete)
    reconcile = next(i for i, step in enumerate(complete) if step.get("name", "").startswith("Reconcile ordered"))
    assert "python -m scripts.releases.sequencer" == complete[reconcile]["run"]


def test_publication_reconciler_has_every_recovery_trigger_and_shared_lock():
    stable = workflow("stable-release.yml")
    publication = workflow("stable-release-publication.yml")

    assert stable["concurrency"] == publication["concurrency"] == {
        "group": "stable-release", "cancel-in-progress": "false",
    }
    assert {"workflow_dispatch", "workflow_run"} <= set(publication["on"])
    assert publication["on"]["workflow_run"] == {
        "workflows": ["Stable Release"], "types": ["completed"],
    }
    reconcile = publication["jobs"]["reconcile"]
    assert reconcile["environment"] == "release-signing"
    assert publication["permissions"] == {"contents": "write", "actions": "write"}
    # Reconcile after a dispatched run of this repository that did not succeed;
    # a manual dispatch of the reconciler always runs.
    def run_of(**overrides):
        workflow_run = {"conclusion": "failure", "event": "workflow_dispatch",
                        "head_repository": {"full_name": "o/r"}, **overrides}
        return {"event_name": "workflow_run", "repository": "o/r", "event": {"workflow_run": workflow_run}}

    assert gate(reconcile["if"], {}, {}, github=run_of())
    assert gate(reconcile["if"], {}, {}, github={"event_name": "workflow_dispatch"})
    for refused in ({"conclusion": "success"}, {"event": "push"}, {"head_repository": {"full_name": "fork/r"}}):
        assert not gate(reconcile["if"], {}, {}, github=run_of(**refused)), refused
    checkout = reconcile["steps"][0]
    assert checkout["with"]["ref"] == "${{ github.event.repository.default_branch }}"
    assert checkout["with"]["persist-credentials"] == "false"
    assert not any(step.get("run", "").startswith("sleep ") for step in reconcile["steps"])
    step = next(item for item in reconcile["steps"]
                if item.get("name") == "Reconcile stable drafts and Docker aliases")
    assert step["run"] == "python -m scripts.releases.sequencer"
    assert set(step["env"]) == {"GH_TOKEN", "REQUESTED_VERSION"}


def test_canary_release_tags_and_publishes_the_source_receipt():
    release = workflow("canary-release.yml")
    jobs = release["jobs"]
    assert set(jobs) == {"tag", "prune"}
    assert {"schedule", "workflow_dispatch"} <= set(release["on"])
    # No build dispatch, no R2 prune: the tag and its prerelease are the canary.
    assert release["permissions"] == {"contents": "write"}
    assert jobs["tag"]["if"] == "github.ref_name == github.event.repository.default_branch"
    steps = {step.get("name"): step for step in jobs["tag"]["steps"]}
    assert "scripts/release.py --canary --publish" in steps["Tag and publish"]["run"]
    assert "python3 scripts/release.py --prune-canaries --publish" in \
        next(step["run"] for step in jobs["prune"]["steps"] if step.get("name") == "Prune")
    for job in jobs.values():
        assert "environment" not in job, job
        assert not any(step.get("uses", "").startswith("./.github/workflows/") for step in job.get("steps", []))


DELETED_RELEASE_MODULES = (
    "channels", "channel_build", "channel_publish", "channel_releases", "channel_disposable",
    "store", "handoff", "desktop_targets", "job_groups", "stamping", "commit_build",
    "bundle_env", "darwin", "r2_multipart", "dispatch_log",
)


def test_no_workflow_references_a_deleted_release_module():
    for path in sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        for module in DELETED_RELEASE_MODULES:
            assert f"scripts/releases/{module}.py" not in text, path.name
        assert "scripts/render-builds-table.py" not in text, path.name


def test_the_nix_release_lane_stamps_its_package_version():
    nix = workflow("nix.yml")["jobs"]
    prepare = next(step["run"] for step in nix["flake-check"]["steps"]
                   if step.get("name") == "Prepare isolated release source")
    assert "scripts/releases/nix_stamp.py" in prepare
    assert "--version" in prepare


def test_every_run_step_receives_the_variables_it_reads():
    """A run step reading $VAR it was never given gets an empty string."""
    runner = {"GITHUB_REPOSITORY", "GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY", "GITHUB_ENV", "GITHUB_SHA",
              "GITHUB_RUN_ID", "GITHUB_WORKSPACE", "RUNNER_TEMP", "HOME", "PATH"}
    for name, job in workflow("stable-release.yml")["jobs"].items():
        given = set(job.get("env") or {})
        for step in job.get("steps", []):
            used = set(re.findall(r"\$\{?([A-Z][A-Z0-9_]+)", step.get("run", ""))) - runner
            missing = used - given - set(step.get("env") or {})
            assert not missing, f"{name} / {step.get('name') or step['run'][:40]}: {sorted(missing)}"
