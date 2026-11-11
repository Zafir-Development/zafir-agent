"""Record each verified upload for the GitHub job summary.

The record is a log. A missing summary file must not fail an upload that
already landed. The process exit writes the table, so a step that uploads and
then exits still reports its objects.
"""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path


_KEYS: list[str] = []
_REGISTERED = False


def note(key: str) -> None:
    """Remember one object key that a verified upload just wrote."""
    global _REGISTERED
    if not isinstance(key, str) or not key or key in _KEYS:
        return
    _KEYS.append(key)
    if not _REGISTERED and os.environ.get("GITHUB_STEP_SUMMARY"):
        atexit.register(flush)
        _REGISTERED = True


def render(keys: list[str]) -> str:
    """One markdown table. Empty when the step uploaded nothing."""
    if not keys:
        return ""
    lines = ["", "### Uploads", "", "| Object |", "|---|"]
    lines.extend(f"| `{key}` |" for key in keys)
    return "\n".join(lines) + "\n"


def flush() -> None:
    """Append the table once. A second call, or a missing summary, writes nothing."""
    summary = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if not summary or not _KEYS:
        return
    text = render(list(_KEYS))
    _KEYS.clear()
    if not text:
        return
    try:
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(text)
    except OSError:
        return


def main() -> None:
    """Print the table for keys a caller already recorded."""
    raw = os.environ.get("UPLOAD_KEYS", "")
    keys = json.loads(raw) if raw else []
    if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
        raise SystemExit("UPLOAD_KEYS must be a JSON list of object keys")
    print(render(keys), end="")


if __name__ == "__main__":
    main()
