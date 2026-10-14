#!/usr/bin/env bash
# One-liner: point this repo at its bundled hooks directory so the
# pre-commit hook runs scripts/check.sh before every commit.
cd "$(git rev-parse --show-toplevel)" && git config core.hooksPath scripts/hooks && echo "set core.hooksPath to scripts/hooks for $(pwd): pre-commit now runs scripts/check.sh"
