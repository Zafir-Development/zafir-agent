"""Stable release admission, gates, and the final publication receipt."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from hermes_cli.update_channel import STABLE_TAG_RE
from scripts.releases import lanes as lane_set
from scripts.releases.draft_warning import strip_draft_warning
from scripts.releases.versioning import tag_record

SHA = re.compile(r"[a-f0-9]{40}")


# Stable releases are cut from ``main`` or from a ``release/*`` maintenance branch.
RELEASE_LINE_BRANCHES = ("main", "release/*")


def release_line_refspecs(remote_prefix: str) -> list[str]:
    """Fetch refspecs that mirror every release-line branch under ``refs/remotes/<remote_prefix>/``."""
    return [f"+refs/heads/{branch}:refs/remotes/{remote_prefix}/{branch}"
            for branch in RELEASE_LINE_BRANCHES]


def release_line_contains(commit: str, remote_prefix: str) -> list[str]:
    """The git command that lists the fetched release-line branches holding ``commit``.

    Empty output means the commit is on no release line. Git matches the
    ``release/*`` pattern across the slash, so ``release/0.22.1`` qualifies.
    """
    return ["git", "for-each-ref", "--contains", commit, "--format=%(refname)",
            *(f"refs/remotes/{remote_prefix}/{branch}" for branch in RELEASE_LINE_BRANCHES)]


def admit_claim(tag: str, commit: str, *, on_main) -> dict:
    """Admit a release from its claim ref. The checkout version is not read.

    ``main`` carries ``0.0.0`` on purpose, so the version and the attempt come
    from ``rc.<N>-vX.Y.Z`` and the only question about the commit is whether
    it is on a release line: ``main`` or a ``release/*`` branch. ``on_main`` is
    that predicate; the name predates release branches.
    """
    from scripts.releases.versioning import parse_attempt_ref

    parsed = parse_attempt_ref(tag)
    if parsed is None:
        raise ValueError(f"{tag} is not a claim tag")
    version, attempt = parsed
    if not on_main(commit):
        raise ValueError(f"{commit} is not on main or a release/* branch")
    return {"claim_tag": tag, "tag": f"v{version}", "version": version, "attempt": attempt,
            "commit": commit}


def require_stable_identity(tag: str, commit: str) -> None:
    """Validate the final payload identity without requiring its future ref."""
    if not isinstance(tag, str) or not STABLE_TAG_RE.fullmatch(tag) or not SHA.fullmatch(commit or ""):
        raise ValueError("Invalid stable payload identity")


def gate_expectations(required: list[str], lanes: Iterable[str]) -> dict:
    """Each gated job's required result under the claim's lanes: `skipped` for a job a
    lane it needs is off for, `success` for every other."""
    runs = lane_set.jobs_to_run(lanes)
    return {name: "success" if runs.get(name, True) else "skipped" for name in required}


def require_gate(needs: dict, required: list[str], *, lanes: Iterable[str]) -> None:
    """Require every gate passed, and a lane-removed job really was skipped."""
    if not required or len(set(required)) != len(required):
        raise ValueError("Invalid required-job list")
    expected = gate_expectations(required, lanes)
    failures = [f"{name}={needs.get(name, {}).get('result', 'missing')} (expected {want})"
                for name, want in expected.items() if needs.get(name, {}).get("result") != want]
    if failures:
        raise ValueError("Release blocked: " + ", ".join(failures))


def output(argv: list[str]) -> str:
    return subprocess.check_output(argv, text=True, encoding="utf-8").strip()


def validate_claim(metadata: object, *, version: str, attempt: int, commit: str) -> dict:
    """The claim message's exact shape. It is the one record of the attempt's policy."""
    expected = {"schema": 1, "version": version, "attempt": attempt, "commit": commit}
    if (not isinstance(metadata, dict)
            or any(metadata.get(key) != value for key, value in expected.items())
            or not isinstance(metadata.get("autopublish"), bool)
            or not isinstance(metadata.get("claimEpoch"), int)
            or metadata["claimEpoch"] <= 0
            or set(metadata) != {*expected, "autopublish", "claimEpoch", "lanes", "lanesRevision"}):
        raise ValueError("Stable claim metadata is invalid")
    return {**metadata, "lanes": lane_set.claim_lanes(metadata)}


def _claim_metadata(raw: str, *, version: str, attempt: int, commit: str) -> dict:
    try:
        metadata = tag_record(raw)
    except (TypeError, AttributeError, json.JSONDecodeError) as error:
        raise ValueError("Stable claim metadata is invalid") from error
    return validate_claim(metadata, version=version, attempt=attempt, commit=commit)


def validate_final(final: object, *, version: str, commit: str, claim_tag: str,
                   claim_object: str, claim: dict) -> dict:
    """The final receipt tag's exact shape, bound to its validated claim.

    The source-only pipeline builds no desktop bundle, so the receipt always
    records ``candidateManifestSha256: null``. A claim that builds no Docker
    image records ``dockerManifestDigest: null``.
    """
    if not isinstance(final, dict):
        raise ValueError("Final tag metadata differs from its claim")
    docker = final.get("dockerManifestDigest")
    expected = {
        "schema": 1, "version": version, "commit": commit,
        "claimTag": claim_tag, "claimTagObject": claim_object,
        "autopublish": claim["autopublish"],
        "claimEpoch": claim["claimEpoch"],
        "releaseId": final.get("releaseId"),
        "candidateManifestSha256": None,
        "dockerManifestDigest": docker,
        "archive": f"releases/tag/{claim_tag}/",
    }
    docker_ok = (bool(re.fullmatch(r"sha256:[a-f0-9]{64}", docker or ""))
                 if "docker" in claim["lanes"] else docker is None)
    if (final != expected
            or not isinstance(final["releaseId"], int) or final["releaseId"] <= 0
            or not docker_ok):
        raise ValueError("Final tag metadata differs from its claim")
    return final


def tagger_epoch(tag_object: str, run=output) -> int:
    body = run(["git", "cat-file", "-p", tag_object])
    tagger = next((line for line in body.splitlines() if line.startswith("tagger ")), None)
    if tagger is None:
        raise ValueError("Stable claim has no tagger timestamp")
    try:
        epoch = int(tagger.rsplit(" ", 2)[1])
    except (IndexError, ValueError) as error:
        raise ValueError("Stable claim tagger timestamp is invalid") from error
    if epoch <= 0:
        raise ValueError("Stable claim tagger timestamp is invalid")
    return epoch


CONTROLLER_BRANCH = "main"
CONTROLLER_REF = f"refs/heads/{CONTROLLER_BRANCH}"
CONTROLLER_WORKFLOW = "stable-release.yml"


def claim_run_title(claim_tag: str) -> str:
    """The run-name stable-release.yml sets. Every run is on the default branch, so this names the claim."""
    return f"Stable release {claim_tag}"


def is_claim_run(*, title: str | None, head_branch: str | None, head_sha: str | None,
                 claim_tag: str, commit: str) -> bool:
    """A Stable Release run for this claim. Runs started before the controller moved sat on the tag."""
    return title == claim_run_title(claim_tag) or (head_branch == claim_tag and head_sha == commit)


def check_controller(env: dict) -> None:
    """Require the default-branch dispatch of Stable Release.

    Reusable workflows keep the top-level caller's identity, so the same check holds
    inside every called workflow. The commit under test comes from the claim tag, not
    from GITHUB_SHA, which is the default branch tip here.
    """
    repository = env.get("GITHUB_REPOSITORY", "")
    expected = f"{repository}/.github/workflows/{CONTROLLER_WORKFLOW}@{CONTROLLER_REF}"
    if (not repository or env.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
            or env.get("GITHUB_REF") != CONTROLLER_REF or env.get("GITHUB_WORKFLOW_REF") != expected):
        raise ValueError("Stable release must run from the default-branch controller workflow")


def check_claim(env: dict, run=output) -> dict:
    """Bind the run to one remote annotated claim object and its commit."""
    claim_tag = env.get("RELEASE_CLAIM_TAG")
    if not isinstance(claim_tag, str) or not claim_tag:
        raise ValueError("Stable release needs a claim tag")
    check_controller(env)
    claim_ref = f"refs/tags/{claim_tag}"
    local_object = run(["git", "rev-parse", claim_ref])
    local_commit = run(["git", "rev-parse", f"{claim_ref}^{{commit}}"])
    if run(["git", "cat-file", "-t", local_object]) != "tag":
        raise ValueError("Stable claim must be an annotated tag")
    remote = dict(line.split()[::-1] for line in run(
        ["git", "ls-remote", "origin", claim_ref, f"{claim_ref}^{{}}"]
    ).splitlines())
    remote_object = remote.get(claim_ref)
    remote_commit = remote.get(f"{claim_ref}^{{}}")
    expected_object = env.get("RELEASE_CLAIM_OBJECT")
    commit = local_commit
    if not SHA.fullmatch(commit):
        raise ValueError("Stable claim needs an exact commit")
    if (remote_commit != commit or remote_object != local_object
            or (expected_object and remote_object != expected_object)):
        raise ValueError("Stable claim tag moved")
    run(["git", "fetch", "origin", *release_line_refspecs("origin")])

    def on_main(sha: str) -> bool:
        return bool(run(release_line_contains(sha, "origin")))

    admitted = admit_claim(claim_tag, commit, on_main=on_main)
    raw_metadata = run(["git", "tag", "-l", claim_tag, "--format=%(contents)"])
    metadata = _claim_metadata(raw_metadata, version=admitted["version"],
                               attempt=admitted["attempt"], commit=commit)
    claim_epoch = tagger_epoch(local_object, run)
    if metadata["claimEpoch"] != claim_epoch:
        raise ValueError("Stable claim epoch differs from its annotated tagger timestamp")
    return {**admitted, "claim_object": local_object,
            "autopublish": metadata["autopublish"], "lanes": metadata["lanes"],
            "claim_epoch": claim_epoch}


def stable_context(env: dict, run=output) -> tuple[str, str, dict]:
    claim = check_claim(env, run=run)
    tag = env.get("RELEASE_TAG")
    if not isinstance(tag, str) or tag != claim["tag"]:
        raise ValueError("Stable payload tag differs from the admitted claim")
    return tag, claim["commit"], claim


def final_context(env: dict, run=output) -> tuple[str, str, dict]:
    """Verify the final annotated receipt, its claim, and published release."""
    repository = env.get("GITHUB_REPOSITORY", "")
    tag = env.get("RELEASE_TAG", "")
    commit = env.get("RELEASE_COMMIT", "")
    claim_tag = env.get("RELEASE_CLAIM_TAG", "")
    claim_object = env.get("RELEASE_CLAIM_OBJECT", "")
    require_stable_identity(tag, commit)
    admitted = admit_claim(claim_tag, commit, on_main=lambda _commit: True)
    if admitted["tag"] != tag or not SHA.fullmatch(claim_object):
        raise ValueError("Final release differs from its claim")

    refs = {}
    for line in run(["git", "ls-remote", "origin",
                     f"refs/tags/{claim_tag}", f"refs/tags/{claim_tag}^{{}}",
                     f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"]).splitlines():
        sha, ref = line.split()
        refs[ref] = sha
    if (refs.get(f"refs/tags/{claim_tag}") != claim_object
            or refs.get(f"refs/tags/{claim_tag}^{{}}") != commit
            or refs.get(f"refs/tags/{tag}^{{}}") != commit
            or not refs.get(f"refs/tags/{tag}")):
        raise ValueError("Final release tag custody changed")

    run(["git", "fetch", "origin", *release_line_refspecs("origin"),
         f"+refs/tags/{claim_tag}:refs/tags/{claim_tag}",
         f"+refs/tags/{tag}:refs/tags/{tag}"])
    for receipt, expected_object in ((claim_tag, claim_object),
                                     (tag, refs[f"refs/tags/{tag}"])):
        local_object = run(["git", "rev-parse", f"refs/tags/{receipt}"])
        if local_object != expected_object or run(["git", "cat-file", "-t", local_object]) != "tag":
            raise ValueError("Final release local tag differs from the remote")
    if not run(release_line_contains(commit, "origin")):
        raise ValueError(f"{commit} is not on main or a release/* branch")
    claim = _claim_metadata(
        run(["git", "tag", "-l", claim_tag, "--format=%(contents)"]),
        version=admitted["version"], attempt=admitted["attempt"], commit=commit,
    )
    final = validate_final(
        tag_record(run(["git", "tag", "-l", tag, "--format=%(contents)"])),
        version=admitted["version"], commit=commit, claim_tag=claim_tag,
        claim_object=claim_object, claim=claim,
    )
    release = json.loads(run([
        "gh", "api", f"repos/{repository}/releases/tags/{tag}",
    ]))
    if (release.get("id") != final["releaseId"] or release.get("tag_name") != tag
            or release.get("draft") is not False
            or release.get("prerelease") is not False or not release.get("published_at")):
        raise ValueError("Stable channel requires the published final release")
    return tag, commit, {**admitted, "claim_object": claim_object,
                         "autopublish": claim["autopublish"],
                         "lanes": claim["lanes"],
                         "claim_epoch": claim["claimEpoch"],
                         "release_id": final["releaseId"],
                         "candidate_manifest_sha256": final["candidateManifestSha256"],
                         "docker_manifest_digest": final["dockerManifestDigest"]}


def emit(values: dict, env: dict) -> None:
    with Path(env["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as file:
        file.writelines(f"{key}={value if isinstance(value, str) else json.dumps(value, separators=(',', ':'))}\n" for key, value in values.items())


def summary(text: str, env: dict) -> None:
    with Path(env["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as file:
        file.write(text + "\n")


def admit(env: dict) -> None:
    """Admit the claim. The checkout carries 0.0.0, so the tag is the version."""
    admitted = check_claim(env)
    repository = env["GITHUB_REPOSITORY"]
    release = json.loads(output([
        "gh", "release", "view", admitted["claim_tag"], "--repo", repository,
        "--json", "databaseId,tagName,isDraft,isPrerelease",
    ]))
    if (release.get("tagName") != admitted["claim_tag"] or release.get("isDraft") is not True
            or release.get("isPrerelease") is not False or not isinstance(release.get("databaseId"), int)):
        raise ValueError("Stable claim must already own one non-prerelease draft")
    emit({
        "claim-tag": admitted["claim_tag"], "claim-object": admitted["claim_object"],
        "tag": admitted["tag"], "commit": admitted["commit"], "version": admitted["version"],
        "release-id": release["databaseId"], "release-epoch": admitted["claim_epoch"],
        # `lanes` is every lane's flag; `jobs` is every lane-controlled job's run flag. Each
        # job's `if` reads `jobs`, so the lane table is the only place that says what runs.
        "lanes": lane_set.flags(admitted["lanes"]), "jobs": lane_set.jobs_to_run(admitted["lanes"]),
    }, env)
    summary(
        f"## Stable candidate {admitted['claim_tag']}\nCommit: {admitted['commit']}\n"
        f"Version: {admitted['version']}\nPayload tag: {admitted['tag']}\n"
        f"Lanes {lane_set.describe(admitted['lanes'])}\n",
        env,
    )


def verify(env: dict) -> None:
    """Revalidate claim custody in a reusable privileged workflow."""
    tag, commit, claim = stable_context(env)
    emit({"tag": tag, "sha": commit, "channel": "stable", "payload-version": tag[1:],
          "release-epoch": claim["claim_epoch"]}, env)


def _final_metadata(tag: str, commit: str, claim: dict,
                    docker_manifest_digest: str | None, release_id: int) -> dict:
    if "docker" not in claim["lanes"]:
        if docker_manifest_digest is not None:
            raise ValueError("A claim that builds no Docker image cannot bind a Docker digest")
    elif not re.fullmatch(r"sha256:[a-f0-9]{64}", docker_manifest_digest or ""):
        raise ValueError("Final tag Docker manifest digest is invalid")
    if not isinstance(release_id, int) or release_id <= 0:
        raise ValueError("Final tag release database ID is invalid")
    return {
        "schema": 1, "version": tag[1:], "commit": commit,
        "claimTag": claim["claim_tag"], "claimTagObject": claim["claim_object"],
        "autopublish": claim["autopublish"],
        "claimEpoch": claim["claim_epoch"],
        "releaseId": release_id,
        "candidateManifestSha256": None,
        "dockerManifestDigest": docker_manifest_digest,
        "archive": f"releases/tag/{claim['claim_tag']}/",
    }


def authenticated_push(ref: str, env: dict | None = None) -> list[str]:
    """``git push origin <ref>`` that authenticates with GH_TOKEN when it is set.

    The publication checkout runs with persist-credentials: false, so git has
    no token of its own; gh hands GH_TOKEN to this one push as a credential
    helper, keeping the token out of argv and out of .git/config.
    """
    env = os.environ if env is None else env
    auth = (["-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential"]
            if env.get("GH_TOKEN") else [])
    return ["git", *auth, "push", "origin", ref]


def ensure_final_tag(tag: str, commit: str, claim: dict, *, docker_manifest_digest: str | None,
                     release_id: int, run=output) -> str:
    """Create or verify the immutable annotated final tag."""
    require_stable_identity(tag, commit)
    expected = _final_metadata(tag, commit, claim, docker_manifest_digest, release_id)
    ref = f"refs/tags/{tag}"
    remote_raw = run(["git", "ls-remote", "origin", ref, f"{ref}^{{}}"])
    if not remote_raw:
        try:
            local_object = run(["git", "rev-parse", "--verify", ref])
        except subprocess.CalledProcessError:
            message = json.dumps(expected, sort_keys=True, separators=(",", ":"))
            run([
                "git", "-c", "user.name=Hermes Release Automation",
                "-c", "user.email=release-bot@users.noreply.github.com",
                "tag", "-a", tag, commit, "-m", message,
            ])
        else:
            if (run(["git", "cat-file", "-t", local_object]) != "tag"
                    or run(["git", "rev-parse", f"{ref}^{{commit}}"]) != commit
                    or tag_record(run(["git", "tag", "-l", tag, "--format=%(contents)"])) != expected):
                raise ValueError("Local final tag collision")
        run(authenticated_push(ref))
        remote_raw = run(["git", "ls-remote", "origin", ref, f"{ref}^{{}}"])
    remote = dict(line.split()[::-1] for line in remote_raw.splitlines())
    tag_object, peeled = remote.get(ref), remote.get(f"{ref}^{{}}")
    if not tag_object or peeled != commit:
        raise ValueError("Final stable tag points at the wrong commit or is lightweight")
    try:
        local_object = run(["git", "rev-parse", ref])
    except subprocess.CalledProcessError:
        run(["git", "fetch", "origin", f"{ref}:{ref}"])
        local_object = run(["git", "rev-parse", ref])
    if local_object != tag_object or run(["git", "cat-file", "-t", local_object]) != "tag":
        raise ValueError("Final stable tag object differs from the verified remote")
    metadata = tag_record(run(["git", "tag", "-l", tag, "--format=%(contents)"]))
    if metadata != expected:
        raise ValueError("Final stable tag metadata differs from the accepted artifacts")
    return tag_object


def edit_draft_release(repository: str, release_id: int, tag: str, commit: str, *,
                       run=output) -> None:
    """Retarget the draft onto the receipt tag and strip the warning blocks.

    Immutable releases take no edits after publication, so every edit happens
    here while the release is still a draft, and the tag name, draft flag, and
    body are read back before anything else touches the release. A release that
    is already public is left alone: nothing can repair it.
    """
    endpoint = f"repos/{repository}/releases/{release_id}"
    current = json.loads(run(["gh", "api", endpoint]))
    if current.get("id") != release_id:
        raise ValueError("Stable draft release id changed")
    if (current.get("tag_name") == tag and current.get("draft") is False
            and current.get("prerelease") is False):
        return
    if current.get("draft") is not True:
        raise ValueError("Stable release is no longer a draft and cannot be repaired")
    body = strip_draft_warning(current.get("body") or "")
    run([
        "gh", "api", "--method", "PATCH", endpoint,
        "--raw-field", f"tag_name={tag}", "--raw-field", f"target_commitish={commit}",
        "--raw-field", "make_latest=true",
        "--field", "prerelease=false", "--field", "draft=true",
        "--raw-field", f"body={body}",
    ])
    release = json.loads(run(["gh", "api", endpoint]))
    if (release.get("id") != release_id or release.get("tag_name") != tag
            or release.get("prerelease") is not False or release.get("draft") is not True):
        raise ValueError("Stable draft retarget did not persist")
    # A fence that survives the edit — balanced or not — means the body was
    # changed underneath this call, and the release must not go public.
    if strip_draft_warning(release.get("body") or "") != body:
        raise ValueError("Stable draft body edit did not persist")


def publish_release_draft(repository: str, release_id: int, tag: str, *, run=output) -> None:
    """Make the release public as its own final call.

    Under immutable releases this is the last edit the release ever takes, so
    it runs only after the retarget and the strip have both been read back.
    """
    endpoint = f"repos/{repository}/releases/{release_id}"
    run(["gh", "api", "--method", "PATCH", endpoint, "--field", "draft=false"])
    release = json.loads(run(["gh", "api", endpoint]))
    if (release.get("id") != release_id or release.get("tag_name") != tag
            or release.get("prerelease") is not False or release.get("draft") is not False
            or not release.get("published_at")):
        raise ValueError("Stable release publication did not persist")


def publish_attempt(record: dict, *, repository: str, run=output) -> dict:
    """The one ordered publication pass, steps 1-4, each read back before the next.

    Explicit publish and autopublish converge here. The Docker digest the image
    was pushed under is read from the registry (nothing records it earlier),
    the receipt tag is written, the draft is retargeted and stripped while still
    a draft, and only then does the final call make it public. Returns the digest
    the receipt binds, so the alias promotion that follows in the same pass
    checks the receipt it just wrote.
    """
    from scripts.releases import docker

    claim = {"claim_tag": record["claim_tag"], "claim_object": record["claim_object"],
             "autopublish": record["autopublish"], "lanes": record["lanes"],
             "claim_epoch": record["claim_epoch"]}
    # A claim that built no image pushed none, so its receipt binds no digest.
    docker_digest = docker.published_digest(record["claim_tag"], run) if "docker" in record["lanes"] else None
    ensure_final_tag(record["tag"], record["commit"], claim,
                     docker_manifest_digest=docker_digest,
                     release_id=record["release_id"], run=run)
    edit_draft_release(repository, record["release_id"], record["tag"], record["commit"], run=run)
    publish_release_draft(repository, record["release_id"], record["tag"], run=run)
    return {"docker_manifest_digest": docker_digest}


def main(argv: list[str] | None = None, env: dict | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    env = os.environ if env is None else env
    if argv and argv[0] in {"-h", "--help"}:
        print("usage: python -m scripts.releases.stable {admit|verify|gate JOB...}")
        print("  admit        admit the claim; emit its lanes, jobs and release identities")
        print("  verify       revalidate claim custody; emit the payload identity")
        print("  gate JOB...  require the named job results (RELEASE_NEEDS, LANES)")
        return
    if argv and argv[0] == "gate":
        needs = json.loads(env["RELEASE_NEEDS"])
        summary("\n".join(f"- {name}: {needs.get(name, {}).get('result', 'missing')}" for name in argv[1:]), env)
        require_gate(needs, argv[1:], lanes=lane_set.from_flags(json.loads(env.get("LANES") or "null")))
        return
    commands = {"admit": admit, "verify": verify}
    if len(argv) != 1 or argv[0] not in commands:
        raise ValueError("Expected admit, verify or gate")
    commands[argv[0]](env)


if __name__ == "__main__":
    main()
