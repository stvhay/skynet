#!/usr/bin/env python3
"""Compute and optionally update version for skynet packages.

Reads versions from mesh-server/pyproject.toml and agent-runtime/pyproject.toml.
In --ci mode, reads bump type from <!-- bump: TYPE --> in CHANGELOG.md and
rewrites ## Unreleased to ## vX.Y.Z.

Usage:
    python compute_version.py                  # print current versions
    python compute_version.py --ci             # print what would be bumped
    python compute_version.py --ci --update    # apply bump and rewrite changelog
"""

import argparse
import re
import sys
from pathlib import Path

PACKAGES = [
    Path("mesh-server/pyproject.toml"),
    Path("agent-runtime/pyproject.toml"),
]
CHANGELOG = Path("CHANGELOG.md")

VERSION_RE = re.compile(r'^version\s*=\s*"(\d+\.\d+\.\d+)"', re.MULTILINE)
BUMP_RE = re.compile(r"<!--\s*bump:\s*(patch|minor|major)\s*-->")


def read_version(toml_path: Path) -> str:
    text = toml_path.read_text()
    m = VERSION_RE.search(text)
    if not m:
        print(f"error: no version found in {toml_path}", file=sys.stderr)
        sys.exit(1)
    return m.group(1)


def bump_version(version: str, bump_type: str) -> str:
    major, minor, patch = (int(x) for x in version.split("."))
    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    else:
        return f"{major}.{minor}.{patch + 1}"


def write_version(toml_path: Path, new_version: str) -> None:
    text = toml_path.read_text()
    new_text = VERSION_RE.sub(f'version = "{new_version}"', text, count=1)
    toml_path.write_text(new_text)


def get_bump_type() -> str | None:
    if not CHANGELOG.exists():
        return None
    text = CHANGELOG.read_text()
    m = BUMP_RE.search(text)
    return m.group(1) if m else None


def rewrite_changelog(new_version: str) -> None:
    text = CHANGELOG.read_text()
    text = text.replace("## Unreleased", f"## v{new_version}", 1)
    CHANGELOG.write_text(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute/update package versions")
    parser.add_argument(
        "--ci", action="store_true", help="CI mode: read bump type from CHANGELOG.md"
    )
    parser.add_argument(
        "--update", action="store_true", help="Apply version bump (requires --ci)"
    )
    args = parser.parse_args()

    if args.update and not args.ci:
        print("error: --update requires --ci", file=sys.stderr)
        sys.exit(1)

    for pkg in PACKAGES:
        version = read_version(pkg)
        print(f"{pkg.parent.name}: {version}")

    if args.ci:
        bump_type = get_bump_type()
        if not bump_type:
            print("no bump comment found in CHANGELOG.md — nothing to do")
            sys.exit(0)

        # Use mesh-server as the primary version source
        current = read_version(PACKAGES[0])
        new_ver = bump_version(current, bump_type)
        print(f"bump: {bump_type} {current} -> {new_ver}")

        if args.update:
            for pkg in PACKAGES:
                write_version(pkg, new_ver)
                print(f"  updated {pkg}")
            rewrite_changelog(new_ver)
            print(f"  rewrote CHANGELOG.md: ## v{new_ver}")


if __name__ == "__main__":
    main()
