#!/usr/bin/env bash
# Thin wrapper around compute_version.py
# Usage: ./compute-version.sh [--ci] [--update]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3 &>/dev/null; then
    echo "error: python3 is required" >&2
    exit 1
fi

exec python3 "$SCRIPT_DIR/compute_version.py" "$@"
