"""Release admission, gates, and the final publication receipt are exact."""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.releases.draft_warning import (
    WARNING_CLOSE, WARNING_OPEN, strip_draft_warning,
)
from scripts.releases import lanes as lane_set
from scripts.releases.stable import (
    check_claim, ensure_final_tag, gate_expectations, require_gate, require_stable_identity,
    validate_claim, validate_final,
)
from scripts.releases.versioning import tag_record

ROOT = Path(__file__).resolve().parents[2]


def test_gate_requires_every_success_and_every_lane_skip_including_real_cli(tmp_path):
    required = ["admit", "ci", "docker", "acceptance", "publication"]
    success = {name: {"result": "success"} for name in required}
    require_gate(success, required, lanes=lane_set.DEFAULT)
    with pytest.raises(ValueError, match="required-job list"):
        require_gate(success, [], lanes=lane_set.DEFAULT)
    for name in required[1:]:
        for result in ("failure", "cancelled", "skipped", None):
            needs = copy.deepcopy(success)
            if result:
                needs[name]["result"] = result
            else:
                del needs[name]
            with pytest.raises(ValueError, match=name):
                require_gate(needs, required, lanes=lane_set.NAMES)
    summary = tmp_path / "summary.md"
    env = {**os.environ, "RELEASE_NEEDS": json.dumps(success), "GITHUB_STEP_SUMMARY": str(summary),
           "PYTHONPATH": str(ROOT), "LANES": json.dumps(lane_set.flags(lane_set.DEFAULT))}
    argv = [sys.executable, "-m", "scripts.releases.stable", "gate", *required]
    assert subprocess.run(argv, cwd=tmp_path, env=env, capture_output=True, check=False).returncode == 0
    empty = subprocess.run(argv[:4], cwd=tmp_path, env=env, capture_output=True, text=True,
                           encoding="utf-8", check=False)
    assert empty.returncode != 0
    assert "required-job list" in empty.stderr
    env["RELEASE_NEEDS"] = json.dumps({**success, "publication": {"result": "cancelled"}})
    result = subprocess.run(argv, cwd=tmp_path, env=env, capture_output=True, text=True,
                            encoding="utf-8", check=False)
    assert result.returncode != 0
    assert "publication=cancelled" in result.stderr


@pytest.mark.parametrize("lanes", [
    lane_set.select(without=["ci"]),
    lane_set.select(only=["docker"]),
    lane_set.select(only=["docker", "ci"]),
    lane_set.select(only=[]),
])
def test_gate_requires_every_lane_removed_job_to_have_skipped(tmp_path, lanes):
    required = ["admit", *lane_set.JOB_LANES]
    expected = gate_expectations(required, lanes)
    # Lanes never remove admission.
    assert expected["admit"] == "success"
    assert {name for name, result in expected.items() if result == "success"} - {"admit"} == \
        {job for job, runs in lane_set.jobs_to_run(lanes).items() if runs}
    needs = {name: {"result": result} for name, result in expected.items()}
    env = {**os.environ, "RELEASE_NEEDS": json.dumps(needs), "PYTHONPATH": str(ROOT),
           "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
           "LANES": json.dumps(lane_set.flags(lanes))}
    argv = [sys.executable, "-m", "scripts.releases.stable", "gate", *required]
    assert subprocess.run(argv, cwd=tmp_path, env=env, capture_output=True, check=False).returncode == 0
    # A removed job that ran anyway blocks the release, and so does a different lane set.
    removed = next(name for name, result in expected.items() if result == "skipped")
    env["RELEASE_NEEDS"] = json.dumps({**needs, removed: {"result": "success"}})
    ran = subprocess.run(argv, cwd=tmp_path, env=env, capture_output=True, text=True,
                         encoding="utf-8", check=False)
    assert ran.returncode != 0 and f"{removed}=success (expected skipped)" in ran.stderr
    env["RELEASE_NEEDS"] = json.dumps(needs)
    env["LANES"] = json.dumps(lane_set.flags(lane_set.NAMES))
    assert subprocess.run(argv, cwd=tmp_path, env=env, capture_output=True, check=False).returncode != 0
    del env["LANES"]
    missing = subprocess.run(argv, cwd=tmp_path, env=env, capture_output=True, text=True,
                             encoding="utf-8", check=False)
    assert missing.returncode != 0 and "lanes must be" in missing.stderr


# Stable runs from the default branch. GITHUB_SHA is main's tip, never the claim commit.
CONTROLLER_ENV = {
    "GITHUB_REPOSITORY": "example/hermes-agent",
    "GITHUB_EVENT_NAME": "workflow_dispatch",
    "GITHUB_REF": "refs/heads/main",
    "GITHUB_WORKFLOW_REF": "example/hermes-agent/.github/workflows/stable-release.yml@refs/heads/main",
    "GITHUB_SHA": "e" * 40,
}


def test_a_claim_run_is_found_by_its_run_name_on_main_or_by_its_tag_branch():
    from scripts.releases.stable import claim_run_title, is_claim_run

    tag, commit = "rc.1-v1.2.3", "a" * 40
    assert claim_run_title(tag) == "Stable release rc.1-v1.2.3"

    def match(**row):
        return is_claim_run(**{"title": None, "head_branch": "main", "head_sha": "e" * 40, **row},
                            claim_tag=tag, commit=commit)

    assert match(title="Stable release rc.1-v1.2.3")
    # Runs started before the controller moved sat on the tag at the claim commit.
    assert match(head_branch=tag, head_sha=commit)
    assert not match(title="Stable release rc.2-v1.2.3")
    assert not match(head_branch=tag, head_sha="e" * 40)
    assert not match()


def test_claim_must_run_from_the_default_branch_controller():
    base = {**CONTROLLER_ENV, "RELEASE_CLAIM_TAG": "rc.1-v1.2.3"}
    for wrong in (
        {"GITHUB_REF": "refs/tags/rc.1-v1.2.3"},
        {"GITHUB_REF": "refs/heads/feature"},
        {"GITHUB_EVENT_NAME": "workflow_run"},
        {"GITHUB_WORKFLOW_REF": "example/hermes-agent/.github/workflows/other.yml@refs/heads/main"},
        {"GITHUB_WORKFLOW_REF": "example/hermes-agent/.github/workflows/stable-release.yml@refs/tags/rc.1-v1.2.3"},
    ):
        with pytest.raises(ValueError, match="default-branch controller"):
            check_claim({**base, **wrong}, lambda argv: pytest.fail("no git before the controller check"))


def test_claim_object_movement_and_lightweight_tags_fail_closed(tmp_path, monkeypatch):
    commit = "a" * 40
    claim_object = "b" * 40
    ref = "refs/tags/rc.1-v1.2.3"
    env = {**CONTROLLER_ENV, "RELEASE_CLAIM_TAG": "rc.1-v1.2.3", "RELEASE_CLAIM_OBJECT": claim_object}
    message = {"schema": 1, "version": "1.2.3", "attempt": 1, "commit": commit,
               "autopublish": False, "lanes": sorted(lane_set.DEFAULT),
               "lanesRevision": lane_set.LANES_REVISION,
               "claimEpoch": 1_790_000_000}

    def git(argv):
        if argv[1] == "ls-remote":
            return f"{claim_object}\t{ref}\n{commit}\t{ref}^{{}}"
        if argv[1:3] == ["cat-file", "-t"]:
            return "tag"
        if argv[1:3] == ["cat-file", "-p"]:
            return "tagger Fixture <fixture@example.test> 1790000000 +0000\n"
        if argv[1] == "rev-parse":
            return claim_object if argv[-1] == ref else commit
        if argv[1] == "tag":
            return json.dumps(message)
        if argv[1] == "for-each-ref":
            return "refs/remotes/origin/release/1.2.3"
        return ""

    assert check_claim(env, git) == {
        "claim_tag": "rc.1-v1.2.3", "claim_object": claim_object,
        "tag": "v1.2.3", "version": "1.2.3", "attempt": 1, "commit": commit,
        "autopublish": False, "lanes": lane_set.DEFAULT,
        "claim_epoch": 1_790_000_000,
    }
    # The metadata binds the attempt its ref names.
    for wrong in ({**message, "attempt": 2}, {k: v for k, v in message.items() if k != "attempt"}):
        with pytest.raises(ValueError, match="metadata is invalid"):
            check_claim(env, lambda argv, wrong=wrong: json.dumps(wrong) if argv[1] == "tag" else git(argv))
    with pytest.raises(ValueError, match="tag moved"):
        check_claim(env, lambda argv: f"{'c' * 40}\t{ref}\n{commit}\t{ref}^{{}}"
                    if argv[1] == "ls-remote" else git(argv))
    with pytest.raises(ValueError, match="annotated"):
        check_claim(env, lambda argv: "commit" if argv[1] == "cat-file" else git(argv))

    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    repo.mkdir()
    monkeypatch.chdir(repo)
    subprocess.run(["git", "init", "-b", "main"], check=True, capture_output=True)
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "fixture"], check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], check=True)
    (repo / "input").write_text("first", encoding="utf-8")
    subprocess.run(["git", "add", "input"], check=True)
    subprocess.run(["git", "commit", "-m", "first"], check=True, capture_output=True)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, encoding="utf-8").strip()
    subprocess.run(["git", "remote", "add", "origin", str(remote)], check=True)
    metadata = json.dumps({
        "schema": 1, "version": "1.2.3", "attempt": 1, "commit": actual,
        "autopublish": False, "lanes": sorted(lane_set.DEFAULT),
        "lanesRevision": lane_set.LANES_REVISION,
        "claimEpoch": 1_790_000_000,
    }, sort_keys=True, separators=(",", ":"))
    subprocess.run(
        ["git", "tag", "-a", "rc.1-v1.2.3", "-m", metadata], check=True,
        env={**os.environ, "GIT_COMMITTER_DATE": "@1790000000 +0000"},
    )
    subprocess.run(["git", "push", "origin", "main", "rc.1-v1.2.3"], check=True, capture_output=True)
    env.update({"RELEASE_CLAIM_OBJECT": subprocess.check_output(
        ["git", "rev-parse", ref], text=True, encoding="utf-8").strip()})
    claim = check_claim(env)
    assert claim["commit"] == actual
    final_object = ensure_final_tag(
        "v1.2.3", actual, claim,
        docker_manifest_digest="sha256:" + "d" * 64,
        release_id=123,
    )
    remote_final = subprocess.check_output(
        ["git", "ls-remote", "origin", "refs/tags/v1.2.3", "refs/tags/v1.2.3^{}"],
        text=True, encoding="utf-8",
    )
    assert f"{final_object}\trefs/tags/v1.2.3" in remote_final
    assert f"{actual}\trefs/tags/v1.2.3^{{}}" in remote_final
    subprocess.run(["git", "--git-dir", str(remote), "update-ref", "-d", ref], check=True)
    with pytest.raises(ValueError, match="moved"):
        check_claim(env)


def test_a_claim_from_the_desktop_pipeline_is_refused():
    """No lane-name aliasing: desktop-era claims are not readable by this pipeline."""
    commit = "a" * 40
    base = {"schema": 1, "version": "0.21.7", "attempt": 11, "commit": commit,
            "autopublish": True, "claimEpoch": 1_790_000_000}
    for stale in (
        {**base, "skipBundles": False, "skipTests": True},
        {**base, "lanes": ["docker", "windows"], "lanesRevision": 2},
        {**base, "lanes": ["docker", "windows"], "lanesRevision": lane_set.LANES_REVISION},
        {**base, "lanes": sorted(lane_set.DEFAULT), "lanesRevision": 1},
        {**base, "lanes": sorted(lane_set.DEFAULT)},
        {**base, "lanes": sorted(lane_set.DEFAULT), "lanesRevision": lane_set.LANES_REVISION,
         "skipTests": True},
    ):
        with pytest.raises(ValueError, match="metadata is invalid"):
            validate_claim(stale, version="0.21.7", attempt=11, commit=commit)
    current = {**base, "lanes": sorted(lane_set.DEFAULT),
               "lanesRevision": lane_set.LANES_REVISION}
    assert validate_claim(current, version="0.21.7", attempt=11, commit=commit)["lanes"] == lane_set.DEFAULT


def _claim_fixture(tmp_path, *, tag, version, lanes=lane_set.DEFAULT):
    """A real checkout + bare remote carrying one annotated attempt claim."""
    from scripts.releases.versioning import parse_attempt_ref

    epoch = 1_790_000_000
    repo, remote = tmp_path / "repo", tmp_path / "remote.git"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "fixture"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repo, check=True)
    (repo / "input").write_text("first", encoding="utf-8")
    subprocess.run(["git", "add", "input"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "first"], cwd=repo, check=True, capture_output=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True, encoding="utf-8").strip()
    attempt = parse_attempt_ref(tag)[1]
    metadata = json.dumps({
        "schema": 1, "version": version, "attempt": attempt, "commit": commit,
        "autopublish": False, "lanes": sorted(lanes),
        "lanesRevision": lane_set.LANES_REVISION,
        "claimEpoch": epoch,
    }, sort_keys=True, separators=(",", ":"))
    subprocess.run(
        ["git", "tag", "-a", tag, "-m", metadata], cwd=repo, check=True,
        env={**os.environ, "GIT_COMMITTER_DATE": f"@{epoch} +0000"},
    )
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True)
    subprocess.run(["git", "push", "origin", "main", tag], cwd=repo, check=True, capture_output=True)
    tag_object = subprocess.check_output(["git", "rev-parse", tag], cwd=repo, text=True, encoding="utf-8").strip()
    return commit, tag_object


def _fenced_body(notes="## What's changed\n- x"):
    """A draft body the way the entrypoint builds it: warning block, notes, warning block."""
    block = WARNING_OPEN + "\nDO NOT PUBLISH THIS BY HAND\n" + WARNING_CLOSE
    return block + "\n" + notes + "\n" + block


def test_strip_removes_both_blocks_and_keeps_the_notes():
    assert strip_draft_warning(_fenced_body()).strip() == "## What's changed\n- x"
    # A body without fences passes through untouched.
    assert strip_draft_warning("just notes") == "just notes"


@pytest.mark.parametrize("body", [
    WARNING_OPEN + "\nunbalanced",
    "text\n" + WARNING_CLOSE,
    WARNING_OPEN + "\n" + WARNING_OPEN + "\n" + WARNING_CLOSE,
    WARNING_OPEN + "text",
])
def test_strip_refuses_an_unbalanced_fence(body):
    with pytest.raises(ValueError, match="unbalanced"):
        strip_draft_warning(body)


def _publish_record(commit, tag_object, *, epoch, release_id=42, lanes=lane_set.DEFAULT):
    return {"claim_tag": "rc.2-v1.2.3", "claim_object": tag_object, "tag": "v1.2.3",
            "commit": commit, "version": "1.2.3", "attempt": 2, "release_id": release_id,
            "autopublish": False, "lanes": frozenset(lanes), "claim_epoch": epoch}


def test_publish_attempt_writes_the_receipt_retargets_and_makes_it_public(tmp_path, monkeypatch):
    from scripts.releases import stable

    commit, tag_object = _claim_fixture(tmp_path, tag="rc.2-v1.2.3", version="1.2.3")
    monkeypatch.chdir(tmp_path / "repo")
    epoch = tag_record(subprocess.check_output(
        ["git", "tag", "-l", "rc.2-v1.2.3", "--format=%(contents)"],
        text=True, encoding="utf-8"))["claimEpoch"]
    docker_digest = "sha256:" + "d" * 64
    release = {"id": 42, "tag_name": "rc.2-v1.2.3", "draft": True, "prerelease": False,
               "body": _fenced_body(), "published_at": None}
    patches = []
    inspected_images = []

    def run(argv):
        if argv[0] == "git":
            return subprocess.check_output(argv, text=True, encoding="utf-8").strip()
        if argv[:3] == ["docker", "buildx", "imagetools"]:
            inspected_images.append(argv[4])
            assert argv[4] in {
                "nousresearch/hermes-agent:rc.2-v1.2.3",
                "nousresearch/hermes-agent:rc.2-v1.2.3-desktop",
            }
            return json.dumps(docker_digest)
        if argv[:3] == ["gh", "api", "--method"]:
            fields = {}
            for _flag, value in zip(argv[5::2], argv[6::2]):
                name, _, raw = value.partition("=")
                fields[name] = raw
            patches.append((fields.get("tag_name"), fields.get("draft")))
            release.update({key: (raw == "true") if key in {"draft", "prerelease"} else raw
                            for key, raw in fields.items()
                            if key in {"tag_name", "draft", "prerelease", "body"}})
            if release["draft"] is False:
                release["published_at"] = "2026-09-22T00:00:00Z"
            return "{}"
        if argv[:2] == ["gh", "api"]:
            assert argv[2].endswith("/releases/42")
            return json.dumps(release)
        raise AssertionError(argv)

    digests = stable.publish_attempt(
        _publish_record(commit, tag_object, epoch=epoch),
        repository="example/project", run=run,
    )

    assert digests == {"docker_manifest_digest": docker_digest}
    receipt = tag_record(subprocess.check_output(
        ["git", "tag", "-l", "v1.2.3", "--format=%(contents)"],
        text=True, encoding="utf-8"))
    assert receipt["claimTag"] == "rc.2-v1.2.3"
    assert receipt["archive"] == "releases/tag/rc.2-v1.2.3/"
    # The source-only pipeline builds no desktop bundle, so the receipt binds no manifest.
    assert receipt["candidateManifestSha256"] is None
    assert receipt["dockerManifestDigest"] == docker_digest
    assert inspected_images == [
        "nousresearch/hermes-agent:rc.2-v1.2.3",
        "nousresearch/hermes-agent:rc.2-v1.2.3-desktop",
    ]
    assert receipt["releaseId"] == 42
    remote = subprocess.check_output(
        ["git", "ls-remote", "origin", "refs/tags/v1.2.3", "refs/tags/v1.2.3^{}"],
        text=True, encoding="utf-8")
    assert commit in remote
    # The retarget and the strip happen while the release is still a draft;
    # draft=false is its own final call, after both read back.
    assert [draft for _tag, draft in patches] == ["true", "false"]
    assert [tag for tag, _draft in patches] == ["v1.2.3", None]
    assert release["tag_name"] == "v1.2.3" and release["draft"] is False
    assert release["body"] == "## What's changed\n- x"


@pytest.mark.parametrize("lanes,binds_docker", [
    (lane_set.select(only=["docker"]), True),
    (lane_set.select(only=[]), False),
])
def test_the_final_receipt_binds_only_what_the_claims_lanes_built(
        tmp_path, monkeypatch, lanes, binds_docker):
    from scripts.releases import stable

    commit, tag_object = _claim_fixture(tmp_path, tag="rc.2-v1.2.3", version="1.2.3", lanes=lanes)
    monkeypatch.chdir(tmp_path / "repo")
    epoch = tag_record(subprocess.check_output(
        ["git", "tag", "-l", "rc.2-v1.2.3", "--format=%(contents)"],
        text=True, encoding="utf-8"))["claimEpoch"]
    release = {"id": 42, "tag_name": "rc.2-v1.2.3", "draft": True, "prerelease": False,
               "body": "notes", "published_at": None}

    def run(argv):
        if argv[0] == "git":
            return subprocess.check_output(argv, text=True, encoding="utf-8").strip()
        if argv[:3] == ["docker", "buildx", "imagetools"]:
            assert binds_docker, "a claim without the docker lane reads no image"
            return json.dumps("sha256:" + "d" * 64)
        if argv[:3] == ["gh", "api", "--method"]:
            fields = dict(value.partition("=")[::2] for value in argv[6::2])
            release.update({key: (raw == "true") if key in {"draft", "prerelease"} else raw
                            for key, raw in fields.items() if key in {"tag_name", "draft", "prerelease", "body"}})
            if release["draft"] is False:
                release["published_at"] = "2026-09-22T00:00:00Z"
            return "{}"
        if argv[:2] == ["gh", "api"]:
            return json.dumps(release)
        raise AssertionError(argv)

    digests = stable.publish_attempt(
        _publish_record(commit, tag_object, epoch=epoch, lanes=lanes),
        repository="example/project", run=run)
    assert (digests["docker_manifest_digest"] is not None) == binds_docker
    final = tag_record(subprocess.check_output(["git", "tag", "-l", "v1.2.3", "--format=%(contents)"],
                                               text=True, encoding="utf-8"))
    assert final["candidateManifestSha256"] is None
    claim = {"autopublish": False, "claimEpoch": epoch, "lanes": frozenset(lanes)}
    stable.validate_final(final, version="1.2.3", commit=commit, claim_tag="rc.2-v1.2.3",
                          claim_object=tag_object, claim=claim)
    # The receipt of a different lane set is refused.
    other = lane_set.select(only=["docker"]) if not binds_docker else lane_set.select(only=[])
    with pytest.raises(ValueError, match="differs from its claim"):
        stable.validate_final(final, version="1.2.3", commit=commit, claim_tag="rc.2-v1.2.3",
                              claim_object=tag_object,
                              claim={**claim, "lanes": frozenset(other)})


def test_publish_attempt_refuses_a_release_that_is_no_longer_a_draft(tmp_path, monkeypatch):
    from scripts.releases import stable

    commit, tag_object = _claim_fixture(tmp_path, tag="rc.2-v1.2.3", version="1.2.3")
    monkeypatch.chdir(tmp_path / "repo")
    epoch = tag_record(subprocess.check_output(
        ["git", "tag", "-l", "rc.2-v1.2.3", "--format=%(contents)"],
        text=True, encoding="utf-8"))["claimEpoch"]
    release = {"id": 42, "tag_name": "rc.2-v1.2.3", "draft": False, "prerelease": False,
               "body": "notes", "published_at": "2026-09-22T00:00:00Z"}

    def run(argv):
        if argv[0] == "git":
            return subprocess.check_output(argv, text=True, encoding="utf-8").strip()
        if argv[:3] == ["docker", "buildx", "imagetools"]:
            return json.dumps("sha256:" + "d" * 64)
        if argv[:2] == ["gh", "api"]:
            return json.dumps(release)
        raise AssertionError(argv)

    with pytest.raises(ValueError, match="no longer a draft"):
        stable.publish_attempt(
            _publish_record(commit, tag_object, epoch=epoch),
            repository="example/project", run=run,
        )
    # The custody receipt still exists: a public release cannot be repaired,
    # but the tag must not be skipped either.
    assert "refs/tags/v1.2.3" in subprocess.check_output(
        ["git", "ls-remote", "origin", "refs/tags/v1.2.3"], text=True, encoding="utf-8")


def test_edit_draft_release_refuses_a_body_that_still_carries_a_fence(tmp_path, monkeypatch):
    from scripts.releases import stable

    commit, _tag_object = _claim_fixture(tmp_path, tag="rc.2-v1.2.3", version="1.2.3")
    monkeypatch.chdir(tmp_path / "repo")
    release = {"id": 42, "tag_name": "rc.2-v1.2.3", "draft": True, "prerelease": False,
               "body": _fenced_body(), "published_at": None}

    # The PATCH is dropped on the floor: the read-back still shows the fence.
    def run(argv):
        if argv[0] == "git":
            return subprocess.check_output(argv, text=True, encoding="utf-8").strip()
        if argv[:3] == ["gh", "api", "--method"]:
            return "{}"
        if argv[:2] == ["gh", "api"]:
            return json.dumps(release)
        raise AssertionError(argv)

    with pytest.raises(ValueError):
        stable.edit_draft_release("example/project", 42, "v1.2.3", commit, run=run)


def test_edit_draft_release_sends_the_notes_byte_for_byte(tmp_path, monkeypatch):
    """Notes that open with a mention must not be read as a file by ``gh api``."""
    from scripts.releases import stable
    from scripts.releases.draft_warning import draft_body

    commit, _tag_object = _claim_fixture(tmp_path, tag="rc.2-v1.2.3", version="1.2.3")
    monkeypatch.chdir(tmp_path / "repo")
    notes = "@alice fixed the updater\n\n42\ntrue"
    release = {"id": 42, "tag_name": "rc.2-v1.2.3", "draft": True, "prerelease": False,
               "body": draft_body(version="1.2.3", attempt_ref="rc.2-v1.2.3", notes=notes),
               "published_at": None}

    def gh_value(flag, value):
        # gh api: -f/--raw-field is a literal string; -F/--field reads @file and
        # converts true/false/null/integers.
        if flag == "--raw-field":
            return value
        if value.startswith("@"):
            raise FileNotFoundError(value[1:])
        return {"true": True, "false": False, "null": None}.get(
            value, int(value) if value.isdigit() else value)

    def run(argv):
        if argv[0] == "git":
            return subprocess.check_output(argv, text=True, encoding="utf-8").strip()
        if argv[:3] == ["gh", "api", "--method"]:
            pairs = zip(argv[5::2], argv[6::2])
            for flag, field in pairs:
                key, _, value = field.partition("=")
                release[key] = gh_value(flag, value)
            return "{}"
        if argv[:2] == ["gh", "api"]:
            return json.dumps(release)
        raise AssertionError(argv)

    stable.edit_draft_release("example/project", 42, "v1.2.3", commit, run=run)

    assert release["body"].strip() == notes
    assert release["tag_name"] == "v1.2.3" and release["draft"] is True


def test_the_final_tag_push_authenticates_with_gh_token_without_persisted_credentials():
    """The publication checkout persists no credentials; the push brings GH_TOKEN itself."""
    from scripts.releases.stable import authenticated_push
    ref = "refs/tags/v1.2.3"
    argv = authenticated_push(ref, {"GH_TOKEN": "token"})
    assert argv[0] == "git" and argv[-3:] == ["push", "origin", ref]
    # Reset inherited helpers first, then hand git the token through gh.
    assert argv[1:5] == ["-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential"]
    assert "token" not in " ".join(argv)
    assert authenticated_push(ref, {}) == ["git", "push", "origin", ref]


def test_a_payload_identity_must_be_an_exact_stable_tag_and_sha():
    require_stable_identity("v1.2.3", "a" * 40)
    for tag, commit in (("v1.2", "a" * 40), ("v1.2.3", "short"), ("2026.9.21", "a" * 40)):
        with pytest.raises(ValueError, match="payload identity"):
            require_stable_identity(tag, commit)
