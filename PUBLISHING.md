# Publishing rc-skills

rc-skills is a fork of [mattpocock/skills](https://github.com/mattpocock/skills), prepared to be published to GitHub under its own name. Nothing is published yet: run this checklist first.

## 1. Identity is filled in

The fork's own identity is set: `shayanrc` (GitHub account) and `Shayan Roychoudhury` (plugin author name), filled in `package.json`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `harness/package.json`, `.agents/install-block.md`, and `README.md`. If the fork ever moves to another GitHub account, find-and-replace those two values across those six files and re-run step 2.

## 2. Validate the manifests

```bash
bash scripts/check.sh
npm run check
claude plugin validate . --strict
npm run check-plugin-version
```

All must pass. `scripts/check.sh` owns every mechanical rule (prose characters, JS syntax, the harness provider test, skills-index freshness, plugin validation); `check-plugin-version` guards the `plugin.json` version, which the changeset Release workflow copies from `package.json`.

## 3. Push the fork

```bash
git remote add origin https://github.com/shayanrc/rc-skills.git
git push -u origin deepseek-harness
```

`deepseek-harness` is the fork's mainline branch (the fork additions and identity changes live there, on top of upstream `main`). On GitHub, either set `deepseek-harness` as the default branch, or open a PR from it into `main` and reset the default after merge. The `upstream` remote (`https://github.com/mattpocock/skills.git`) stays in place for syncing.

## 4. Know the divergence you are committing to

Because the fork publishes under its own name, these files intentionally diverge from upstream and will conflict on every upstream merge:

- `package.json` and `package-lock.json` (name, description, repository URL, the `check` script)
- `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` (plugin and marketplace identity)
- `.agents/install-block.md` and the install blocks in `README.md` (fork install story)
- `CLAUDE.md` (which `AGENTS.md` symlinks to): the fork pointer line and the split prose rule; `CODING_STANDARDS.md` (new fork file)
- `scripts/` (guardrail checks, the pre-commit hook, the hook installer) and `.github/workflows/check.yml` (new fork files)

On merge conflicts, resolve toward the fork identity, then re-run step 2. Upstream skill content (`skills/`, `docs/`) stays verbatim except: the grilling addition (`skills/productivity/grilling/SKILL.md`, mirrored in its docs page), and the mechanical en-dash rewrites committed in 8b6c62f (9 files). The upstream CHANGELOG, changesets, and issue history stay verbatim.

## 5. Optional follow-ups

- The `.github/ISSUE_TEMPLATE` links (discussions, SCOPE.md, CONTRIBUTING.md) currently point at `github.com/mattpocock/skills`. Repoint them at the fork if issues should land here, or leave them if the fork tracks upstream's tracker.
- The README still links Matt Pocock's newsletter and branding; the fork banner above it states the relationship, so leaving them is attribution, not confusion. Trim them only if you want the fork to stand fully alone.
- After the first release, the fork's own marketplace (`.claude-plugin/marketplace.json`) is what `claude plugin marketplace add` and the other install blocks consume; no push to `claude-plugins-official` is involved.
