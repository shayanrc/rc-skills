#!/usr/bin/env bash
# Guardrail checks for rc-skills, a fork of mattpocock/skills.
#
# Run directly (bash scripts/check.sh), through `npm run check`, in CI
# (.github/workflows/check.yml), or as a pre-commit hook. Fails fast:
# the first failing check exits non-zero, with the violation printed.
#
# The prose pattern uses \x{2013} and \x{2014} escapes, so this script
# itself contains no literal en dash or em dash characters.
set -u

cd "$(git rev-parse --show-toplevel 2>/dev/null || dirname "$(dirname "$0")")" || {
  echo "check.sh: cannot locate the repo root" >&2
  exit 1
}

fail() {
  echo "check.sh: FAILED: $1" >&2
  exit 1
}

echo "1/5 prose: no U+2013/U+2014 dashes, no trailing whitespace in text files"
violations="$(grep -rPHn '\x{2013}|\x{2014}| +$' \
  --include='*.md' --include='*.mjs' --include='*.js' \
  --include='*.yaml' --include='*.yml' --include='*.json' \
  --exclude='package-lock.json' --exclude='CHANGELOG.md' \
  --exclude-dir='.git' --exclude-dir='.changeset' --exclude-dir='node_modules' \
  . 2>/dev/null || true)"
if [ -n "$violations" ]; then
  echo "$violations" >&2
  fail "prose: en/em dashes or trailing whitespace found above"
fi
echo "  prose: OK"

echo "2/5 js syntax: node --check on the harness entry points"
for file in harness/lib/index.js harness/install.mjs harness/test.mjs; do
  node --check "$file" || fail "js syntax: node --check $file"
done
echo "  js syntax: OK"

echo "3/5 provider test: node harness/test.mjs"
node harness/test.mjs || fail "provider test: node harness/test.mjs"
echo "  provider test: OK"

echo "4/5 index freshness: rebuild the index, then diff harness/skills-index.json"
node harness/install.mjs --index-only || fail "index freshness: node harness/install.mjs --index-only"
if ! git diff --exit-code -- harness/skills-index.json; then
  fail "index freshness: harness/skills-index.json is stale, run node harness/install.mjs --index-only and commit the result"
fi
echo "  index freshness: OK"

echo "5/5 plugin: claude plugin validate . --strict, then the version sync check"
if command -v claude >/dev/null 2>&1; then
  claude plugin validate . --strict || fail "plugin: claude plugin validate . --strict"
else
  echo "  WARNING: 'claude' binary not found, skipping 'claude plugin validate . --strict' (CI may not have it)"
fi
node scripts/sync-plugin-version.mjs --check || fail "plugin: node scripts/sync-plugin-version.mjs --check"
echo "  plugin: OK"

echo "check.sh: all 5 checks passed"
