"""Canary policy on real Git refs; GitHub publication stays an inert boundary."""
from datetime import datetime, timezone, UTC
from types import SimpleNamespace
import json
import subprocess

import pytest

from tests.scripts.test_release_tags import release, release_repo


@pytest.fixture
def canary_repo(tmp_path, monkeypatch, release_repo):
    git = release_repo
    remote = tmp_path / "remote.git"
    git("init", "--bare", "-q", str(remote))
    git("remote", "add", "origin", "https://github.com/fixture/release")

    calls = []
    releases: dict[str, dict] = {}
    actual_run = subprocess.run

    def run(argv, *args, **kwargs):
        if argv[0] != "gh":
            if argv[:2] in (["git", "push"], ["git", "ls-remote"]):
                argv = ["git", "-c", f"url.{remote.as_uri()}.insteadOf=https://github.com/fixture/release", *argv[1:]]
            return actual_run(argv, *args, **kwargs)
        calls.append(argv)
        if argv[1:3] == ["release", "create"]:
            tag = argv[3]
            releases[tag] = {"tagName": tag, "isDraft": False, "isPrerelease": True,
                             "url": f"https://github.com/fixture/release/releases/tag/{tag}"}
            return subprocess.CompletedProcess(argv, 0, stdout=releases[tag]["url"] + "\n", stderr="")
        if argv[1:3] == ["release", "view"]:
            release_row = releases.get(argv[3])
            if release_row is None:
                return subprocess.CompletedProcess(argv, 1, "", "release not found")
            return subprocess.CompletedProcess(argv, 0, json.dumps(release_row), "")
        if argv[1:3] == ["release", "edit"]:
            assert "--draft=false" in argv, argv
            releases[argv[3]]["isDraft"] = False
            return subprocess.CompletedProcess(argv, 0, "", "")
        raise AssertionError(f"unexpected gh command: {argv}")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(release, "generate_changelog", lambda *args, **kwargs: "fixture notes")
    from scripts.releases import versioning
    monkeypatch.setattr(versioning, "published_stable_identity", lambda repository: ("1.2.3", None))
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    return git, remote, calls, releases


def _args(**overrides):
    options = {"date": "20260818T103000Z", "publish": True, "no_changelog": True, "remote": "origin"}
    options.update(overrides)
    return SimpleNamespace(**options)


def test_canary_cut_tags_and_publishes_the_receipt_immediately(canary_repo):
    git, remote, calls, releases = canary_repo
    git("commit", "--allow-empty", "-qm", "stable")
    git("tag", "v1.2.3")
    git("tag", "v9.9.9")
    git("commit", "--allow-empty", "-qm", "feat: next")
    tag = "v1.2.3+canary.20260818T103000Z"

    release.cmd_canary(_args())

    create = next(call for call in calls if call[1:3] == ["release", "create"])
    assert create[3] == tag
    # A source-only canary has nothing to build: it is published, not drafted.
    assert {"--prerelease", "--verify-tag"} <= set(create)
    assert "--draft" not in create
    assert releases[tag]["isPrerelease"] is True and releases[tag]["isDraft"] is False
    assert not any(call[1:3] == ["workflow", "run"] for call in calls)
    assert git("--git-dir", str(remote), "rev-parse", tag + "^{commit}") == git("rev-parse", "HEAD")

    calls.clear()
    release.cmd_canary(_args())
    assert not any(call[1:3] == ["release", "create"] for call in calls)


def test_unchanged_head_does_not_cut_another_timestamp(canary_repo):
    git, _remote, calls, _releases = canary_repo
    git("commit", "--allow-empty", "-qm", "stable")
    git("tag", "v1.2.3")
    git("commit", "--allow-empty", "-qm", "feat: next")
    release.cmd_canary(_args())
    calls.clear()

    release.cmd_canary(_args(date="20260818T103001Z"))

    assert not any(call[1:3] == ["release", "create"] for call in calls)
    assert set(git("tag", "--list").splitlines()) == {"v1.2.3", "v1.2.3+canary.20260818T103000Z"}


def test_an_interrupted_canary_publication_resumes_without_a_new_tag(canary_repo):
    git, _remote, calls, releases = canary_repo
    git("commit", "--allow-empty", "-qm", "stable")
    git("tag", "v1.2.3")
    git("commit", "--allow-empty", "-qm", "feat: next")
    release.cmd_canary(_args())
    calls.clear()
    # The tag is pushed but the release never got created.
    releases.clear()

    release.cmd_canary(_args())

    assert [call[1:3] for call in calls].count(["release", "create"]) == 1
    assert not any(call[1:3] == ["workflow", "run"] for call in calls)


def test_a_draft_left_by_an_older_flow_is_published(canary_repo):
    git, _remote, calls, releases = canary_repo
    git("commit", "--allow-empty", "-qm", "stable")
    git("tag", "v1.2.3")
    git("commit", "--allow-empty", "-qm", "feat: next")
    release.cmd_canary(_args())
    calls.clear()
    tag = "v1.2.3+canary.20260818T103000Z"
    releases[tag]["isDraft"] = True

    release.cmd_canary(_args())

    edit = next(call for call in calls if call[1:3] == ["release", "edit"])
    assert edit[3] == tag and "--draft=false" in edit
    assert releases[tag]["isDraft"] is False


def test_canary_dry_run_only_prints_the_notes(canary_repo, capsys):
    git, _remote, calls, _releases = canary_repo
    git("commit", "--allow-empty", "-qm", "stable")
    git("tag", "v1.2.3")
    git("commit", "--allow-empty", "-qm", "feat: next")

    release.cmd_canary(_args(publish=False))

    assert calls == []
    assert "fixture notes" in capsys.readouterr().out
    assert not any(tag.endswith("Z") for tag in git("tag", "--list").splitlines())


def test_tag_shape_and_prune_use_canonical_receipts(canary_repo, monkeypatch, capsys):
    git, _, calls, _releases = canary_repo
    assert release.canary_tag_for_date("0.27.4", "20260818T103000Z") == "v0.27.4+canary.20260818T103000Z"
    assert release.canary_tag_for_date("v1.4.0", "20261231T235959Z") == "v1.4.0+canary.20261231T235959Z"
    tags = [
        "v0.27.1+canary.20260801T000000Z",
        "v0.27.1+canary.20260801T235959Z",
        "v0.27.1+canary.20260804T000000Z",
        "v0.27.1+canary.20260804T235959Z",
        "v0.27.1+canary.invalid",
        "v0.27.1",
        "v2026.7.20",
    ]
    for tag in tags:
        git("tag", tag)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 8, 18, tzinfo=UTC)

    monkeypatch.setattr(release, "datetime", Clock)
    release.prune_old_canaries(SimpleNamespace(remote="origin", publish=False))
    deleted = {
        line.removeprefix("Would delete ")
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("Would delete ")
    }
    assert deleted == set(tags[:2])
    assert calls == []
    assert set(git("tag", "--list").splitlines()) == set(tags)
