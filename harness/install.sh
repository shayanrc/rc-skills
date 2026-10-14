#!/usr/bin/env bash
# Wrapper around install.mjs; forwards all arguments.
set -euo pipefail
exec node "$(dirname "$0")/install.mjs" "$@"
