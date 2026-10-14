# Coding standards

`AGENTS.md` carries the always-loaded rules for each repo area; this file is the review checklist on top, kept pointers-first: details stay in the files it names.

## Mechanical checks

`scripts/check.sh` owns every mechanical rule: prose characters (no em-dashes or en-dashes) and trailing whitespace, JS syntax, the harness provider test, skills-index freshness, and plugin validation.

- Review agents: run `bash scripts/check.sh`; any failure is a finding.
- Implementers: run it before committing.
- Pre-commit hook installer: `scripts/install-hooks.sh`.

## Judgement rules

- Em-dashes: where a sentence reaches for an em-dash or en-dash, rewrite it with a comma, colon, period, parentheses, or a conjunction, whichever the sentence actually wants; never do a blind character substitution.
- Upstream merge conflicts resolve toward the fork identity, then re-run `scripts/check.sh`. `PUBLISHING.md` section 4 lists the diverged files.
- Promoted-bucket skills carry the docs-page and README/plugin-manifest obligations named in `AGENTS.md`; reach for it instead of restating the list here.
