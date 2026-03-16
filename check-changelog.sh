#!/usr/bin/env bash
# Hook: validates bump comment presence when ## Unreleased section exists
set -euo pipefail

if [ ! -f CHANGELOG.md ]; then
    exit 0
fi

if grep -q '## Unreleased' CHANGELOG.md; then
    if ! grep -qP '<!--\s*bump:\s*(patch|minor|major)\s*-->' CHANGELOG.md; then
        echo "error: ## Unreleased exists but no <!-- bump: TYPE --> comment found" >&2
        echo "Add <!-- bump: patch|minor|major --> to CHANGELOG.md" >&2
        exit 1
    fi
fi
