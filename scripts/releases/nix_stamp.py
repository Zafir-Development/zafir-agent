"""Stamp the nix package version into an archived release tree.

Python and npm package versions are inert source placeholders. Runtime identity
comes from ``install-stamp.json``; this adapter exists only because the nix
package declares its own version, and the nix release lane builds from an
archived tree that must report the released version.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path


def stamp(tree: Path, version: str) -> list[Path]:
    """Rewrite the nix package version input under ``tree``."""
    nix_package = tree / "nix" / "hermes-agent.nix"
    if not nix_package.exists():
        return []
    raw = nix_package.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8-sig").replace("\r\n", "\n")
    updated = re.sub(r'^  version \? "[^"]+",', f'  version ? "{version}",', text,
                     count=1, flags=re.MULTILINE)
    nix_package.write_bytes(updated.replace("\n", newline).encode("utf-8"))
    return [nix_package]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args(argv)
    stamp(args.tree.resolve(), args.version)


if __name__ == "__main__":
    main()
