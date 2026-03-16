#!/usr/bin/env bash
# Hook: validates ## Unreleased section and <!-- bump: TYPE --> comment on source changes
set -euo pipefail

if ! git diff --cached --name-only | grep -qvE '(CHANGELOG|\.md$)'; then
    exit 0  # No source changes, skip
fi

if [ ! -f CHANGELOG.md ]; then
    echo "warning: CHANGELOG.md not found" >&2
    exit 0
fi

if ! grep -q '## Unreleased' CHANGELOG.md; then
    echo "error: source files changed but CHANGELOG.md has no ## Unreleased section" >&2
    echo "Add an ## Unreleased section with your changes." >&2
    exit 1
fi

if ! grep -qP '<!--\s*bump:\s*(patch|minor|major)\s*-->' CHANGELOG.md; then
    echo "error: ## Unreleased exists but no <!-- bump: TYPE --> comment found" >&2
    echo "Add <!-- bump: patch|minor|major --> to CHANGELOG.md" >&2
    exit 1
fi
