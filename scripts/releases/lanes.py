"""The stable release lanes, defined once.

A stable release is a set of lanes. A build lane produces something users get
(a source release or the Docker image); a test lane is a suite that gates the
release. The claim records the set, ``admit`` turns it into one flag per lane
and one run flag per workflow job, and every gate judges each job against that
same set.

``release.py release`` starts from DEFAULT and edits it with ``--only``,
``--with`` and ``--without``. Lanes are independent switches, but a job runs
only when every lane it needs is on (JOB_LANES).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class Lane:
    name: str
    default: bool
    doc: str


LANES = (
    Lane("docker", True, "build and publish the Docker image"),
    Lane("ci", True, "the full CI pipeline"),
    Lane("nix", True, "Nix checks"),
    Lane("docker-tests", True, "tests of the Docker image before it is published"),
    Lane("pm-bundle", True, "PM bundle acceptance"),
    Lane("windows-live", True, "Windows live venv E2E"),
    Lane("install-e2e", True, "install and update E2E"),
)
NAMES = tuple(lane.name for lane in LANES)
DEFAULT = frozenset(lane.name for lane in LANES if lane.default)

# Each stable-release.yml job and the lanes that must all be on for it to run. A job named here
# reports `skipped` when one is off and `success` otherwise; a job not named never skips.
JOB_LANES: dict[str, frozenset[str]] = {name: frozenset(needs) for name, needs in {
    "ci": ("ci",),
    "nix": ("nix",),
    "docker": ("docker",),
    "publish-docker": ("docker",),
    "pm-bundle": ("pm-bundle",),
    "windows-live": ("windows-live",),
    "install-e2e": ("install-e2e",),
}.items()}


def select(*, only: Iterable[str] | None = None, with_: Iterable[str] = (),
           without: Iterable[str] = ()) -> frozenset[str]:
    """The lane set a ``release`` command asks for. ``only`` replaces DEFAULT as the base."""
    base, added, removed = (_known(group) for group in (DEFAULT if only is None else only, with_, without))
    if added & removed:
        raise ValueError(f"--with and --without both name {', '.join(sorted(added & removed))}")
    return frozenset((base | added) - removed)


def _known(names: Iterable[str]) -> frozenset[str]:
    names = frozenset(names)
    unknown = names - set(NAMES)
    if unknown:
        raise ValueError(f"unknown lane {', '.join(sorted(unknown))}; lanes are {', '.join(NAMES)}")
    return names


def parse_list(values: Iterable[str] | None) -> list[str] | None:
    """Flatten repeated comma-separated option values; None when the option was not given."""
    if values is None:
        return None
    return [name.strip() for value in values for name in value.split(",") if name.strip()]


def flags(lanes: Iterable[str]) -> dict[str, bool]:
    """One flag per lane: what ``admit`` hands the workflow."""
    on = frozenset(lanes)
    return {name: name in on for name in NAMES}


def from_flags(raw: object) -> frozenset[str]:
    """The lane set of a ``flags`` mapping; refuses anything but a boolean for every lane."""
    if not isinstance(raw, Mapping) or set(raw) != set(NAMES) \
            or any(not isinstance(value, bool) for value in raw.values()):
        raise ValueError("lanes must be a boolean for every lane")
    return frozenset(name for name in NAMES if raw[name])


def jobs_to_run(lanes: Iterable[str]) -> dict[str, bool]:
    """Whether each lane-controlled job runs. Every ``if`` in the workflow reads this."""
    on = frozenset(lanes)
    return {job: needs <= on for job, needs in JOB_LANES.items()}


# Claims record `lanesRevision` next to `lanes`. A claim cut by an earlier, desktop-inclusive
# pipeline carries lane names this pipeline no longer has; it is skipped, never translated.
LANES_REVISION = 3


def claim_lanes(metadata: Mapping) -> frozenset[str]:
    """The lanes a claim message records, or ValueError for anything cut by the old pipeline."""
    lanes = metadata.get("lanes")
    if (not isinstance(lanes, list) or any(not isinstance(name, str) for name in lanes)
            or lanes != sorted(set(lanes))):
        raise ValueError("Stable claim metadata is invalid")
    if metadata.get("lanesRevision") != LANES_REVISION:
        raise ValueError("Stable claim metadata is invalid")
    try:
        return _known(lanes)
    except ValueError as error:
        raise ValueError("Stable claim metadata is invalid") from error


def describe(lanes: Iterable[str]) -> str:
    on = frozenset(lanes)
    off = [name for name in NAMES if name not in on]
    return f"on: {', '.join(name for name in NAMES if name in on) or 'none'}; off: {', '.join(off) or 'none'}"
