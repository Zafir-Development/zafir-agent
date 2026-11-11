"""The stable release lanes: what a lane set builds, tests, and records in its claim."""
import pytest

from scripts.releases import lanes as lane_set


def test_every_lane_is_on_by_default():
    assert lane_set.DEFAULT == set(lane_set.NAMES)
    assert lane_set.select() == lane_set.DEFAULT
    assert set(lane_set.NAMES) == {
        "docker", "ci", "docker-tests", "pm-bundle", "windows-live", "install-e2e",
    }


@pytest.mark.parametrize("kwargs,expected", [
    ({"only": ["docker"]}, {"docker"}),
    ({"without": ["docker"]}, set(lane_set.DEFAULT) - {"docker"}),
    ({"only": ["docker"], "with_": ["install-e2e"], "without": ["docker"]}, {"install-e2e"}),
    ({"only": []}, set()),
])
def test_select_edits_the_default_or_replaces_it(kwargs, expected):
    assert lane_set.select(**kwargs) == expected


def test_select_refuses_unknown_and_contradictory_lanes():
    with pytest.raises(ValueError, match="unknown lane windows"):
        lane_set.select(with_=["windows"])
    with pytest.raises(ValueError, match="unknown lane macos-arm64"):
        lane_set.select(only=["macos-arm64"])
    with pytest.raises(ValueError, match="both name ci"):
        lane_set.select(with_=["ci"], without=["ci"])


def test_options_flatten_repeats_and_commas():
    assert lane_set.parse_list(["docker, ci", "pm-bundle"]) == ["docker", "ci", "pm-bundle"]
    assert lane_set.parse_list(None) is None


def test_every_job_names_real_lanes():
    for job, needs in lane_set.JOB_LANES.items():
        assert needs <= set(lane_set.NAMES), job
    # Every job the workflow gates by lanes is in the table and vice versa.
    assert set(lane_set.JOB_LANES) == {
        "ci", "docker", "publish-docker", "pm-bundle", "windows-live", "install-e2e",
    }


def test_a_job_runs_only_when_every_lane_it_needs_is_on():
    docker_only = lane_set.jobs_to_run(["docker"])
    assert {job for job, runs in docker_only.items() if runs} == {"docker", "publish-docker"}
    assert lane_set.jobs_to_run(["ci"]) == {
        "ci": True, "docker": False, "publish-docker": False,
        "pm-bundle": False, "windows-live": False, "install-e2e": False,
    }
    assert not any(lane_set.jobs_to_run([]).values())
    # `docker-tests` is a lane input to the docker job, not a job of its own.
    assert lane_set.jobs_to_run(["docker-tests"])["docker"] is False


def test_flags_round_trip_and_refuse_anything_loose():
    flags = lane_set.flags(["docker", "ci"])
    assert flags["docker"] is True and flags["ci"] is True
    assert set(flags) == set(lane_set.NAMES)
    assert lane_set.from_flags(flags) == {"docker", "ci"}
    for bad in (None, {}, {**flags, "extra": True}, {**flags, "ci": "true"},
                {name: flags[name] for name in flags if name != "ci"}):
        with pytest.raises(ValueError, match="boolean for every lane"):
            lane_set.from_flags(bad)


def test_a_claim_records_the_source_only_lane_set():
    claim = {"lanes": ["ci", "docker"], "lanesRevision": lane_set.LANES_REVISION}
    assert lane_set.claim_lanes(claim) == {"ci", "docker"}
    # Desktop-era lane names, legacy skip flags and an older revision are not readable.
    for stale in (
        {"lanes": ["docker", "windows"], "lanesRevision": lane_set.LANES_REVISION},
        {"lanes": ["docker"], "lanesRevision": 1},
        {"skipBundles": False, "skipTests": True},
        {"lanes": ["docker"]},
        {"lanes": ["docker", "docker"], "lanesRevision": lane_set.LANES_REVISION},
    ):
        with pytest.raises(ValueError, match="invalid"):
            lane_set.claim_lanes(stale)


def test_describe_names_what_is_on_and_off():
    assert lane_set.describe(["docker"]) == "on: docker; off: ci, docker-tests, pm-bundle, windows-live, install-e2e"
    assert lane_set.describe(lane_set.DEFAULT).endswith("off: none")
