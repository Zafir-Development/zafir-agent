"""Contract between the Dockerfile and the build context it copies from.

Deleting a build input (a ``scripts/build/*.mjs`` helper, a workspace manifest)
or a whole build stage while its COPY consumers stay behind leaves ``docker
build`` failing minutes into the dependency layers -- and only where a daemon
runs, so a daemon-less developer host or a non-Docker CI lane sees nothing.
These checks run statically instead: every COPY source must exist in the build
context, and every ``COPY --from=<stage>`` must name a stage declared above it.

Regression for PR #4 (docs/removal/02-removal-plan.md step 2): the desktop
packaging removal deleted ``scripts/build/electron-runtime.mjs`` and
``scripts/build/webapp.mjs`` while the Dockerfile still copied the first and
still built the second in the ``webapp_build`` stage.

Sources are checked for existence in the checkout; ``.dockerignore`` filtering
is not modelled (docker build remains the authority for context contents).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"


@dataclass(frozen=True)
class Copy:
    """One ADD/COPY instruction: its line, --from target, sources, and stages."""

    line: int
    from_stage: str | None
    operands: tuple[str, ...]
    stages_before: tuple[str, ...]


def _logical_lines(text: str) -> list[tuple[int, str]]:
    """Dockerfile instructions with continuations joined; comments dropped."""
    logical: list[tuple[int, str]] = []
    start = 0
    pending = ""
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not pending and (not line or line.startswith("#")):
            continue
        if not pending:
            start = number
        if line.endswith("\\"):
            pending += line[:-1].rstrip() + " "
            continue
        logical.append((start, pending + line))
        pending = ""
    if pending:
        logical.append((start, pending))
    return logical


def _copy_instructions(text: str) -> list[Copy]:
    copies: list[Copy] = []
    stages: list[str] = []
    for number, instruction in _logical_lines(text):
        parts = instruction.split(None, 1)
        keyword = parts[0].upper()
        rest = parts[1].strip() if len(parts) > 1 else ""
        if keyword == "FROM":
            words = rest.split()
            if len(words) >= 3 and words[-2].upper() == "AS":
                stages.append(words[-1].lower())
        elif keyword in {"ADD", "COPY"}:
            copies.append(_parse_copy(number, rest, tuple(stages)))
    return copies


def _parse_copy(number: int, rest: str, stages_before: tuple[str, ...]) -> Copy:
    args = json.loads(rest) if rest.startswith("[") else rest.split()
    from_stage = None
    operands: list[str] = []
    for arg in args:
        if arg.startswith("--from="):
            from_stage = arg.split("=", 1)[1].lower()
        elif arg.startswith("--"):
            continue
        else:
            operands.append(arg)
    return Copy(number, from_stage, tuple(operands), stages_before)


def _missing_sources(text: str) -> list[str]:
    """COPY sources whose path is absent from the checkout (the build context)."""
    missing: list[str] = []
    for copy in _copy_instructions(text):
        if copy.from_stage is not None:
            continue
        for source in copy.operands[:-1]:
            if any(char in source for char in "*?["):
                found = next(iter(REPO_ROOT.glob(source)), None)
            else:
                path = REPO_ROOT / source
                found = path if path.exists() else None
            if found is None:
                missing.append(f"line {copy.line}: {source}")
    return missing


def _unresolved_from_stages(text: str) -> list[str]:
    """COPY --from targets that name neither a prior stage nor an image ref."""
    unresolved: list[str] = []
    for copy in _copy_instructions(text):
        stage = copy.from_stage
        if stage is None or stage in copy.stages_before:
            continue
        # A pulled image reference (registry/repo:tag@digest) is not a stage.
        if any(char in stage for char in "/:@.") or stage.isdigit():
            continue
        unresolved.append(f"line {copy.line}: --from={stage}")
    return unresolved


def test_every_copy_source_exists_in_the_build_context() -> None:
    missing = _missing_sources(DOCKERFILE.read_text(encoding="utf-8"))
    assert not missing, (
        "Dockerfile COPY sources missing from the build context "
        f"(docker build would fail): {missing}"
    )


def test_every_copy_from_names_a_stage_declared_above_it() -> None:
    unresolved = _unresolved_from_stages(DOCKERFILE.read_text(encoding="utf-8"))
    assert not unresolved, (
        "Dockerfile COPY --from targets with no matching earlier stage "
        f"(docker build would try to pull them): {unresolved}"
    )
