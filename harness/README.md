# DeepSeek Harness (dsh) support

This directory adapts the fork to the DeepSeek Harness. It ships every skill
in `../skills` (all 38, in their upstream buckets) through two mechanisms:

1. **Filesystem install** (`install.mjs`): copies the skills, flattened to one
   directory per skill, into a harness skill root. The harness's built-in
   filesystem provider discovers them live, with no restart.
2. **Cordis plugin** (`lib/index.js`): a portable skill provider that
   registers on `ctx.skills` and serves the skills straight from `../skills`,
   using `skills-index.json` for the parsed frontmatter.

## Layout

```
harness/
├── lib/index.js        # cordis plugin: registers a skill provider on ctx.skills
├── skills-index.json   # parsed frontmatter index (rebuilt by install.mjs)
├── install.mjs         # index builder + installer
├── install.sh          # shell wrapper for install.mjs
├── test.mjs            # standalone provider check (mock registry)
└── package.json        # plugin manifest (peer: @deepseek-ai/dsh-skill, cordis)
```

## Install

Run from your project (not from inside this repo):

```bash
# project-wide (this project's .dsh/skills), default
node harness/install.mjs

# user-wide (~/.dsh/skills, or $DSH_HOME/skills)
node harness/install.mjs --user

# anywhere you like
node harness/install.mjs --target /path/to/root

# rebuild skills-index.json only (after upstream changes)
node harness/install.mjs --index-only

# preview what would be installed
node harness/install.mjs --list
```

The installer refuses to install into the fork repo itself, since the skills
already live in `skills/`.

Each installed skill keeps its companion files (`agents/`, `scripts/`,
reference docs) next to `SKILL.md`, so relative paths referenced by skill
bodies keep resolving. Invocation policy from upstream frontmatter is
preserved: 23 skills set `disable-model-invocation: true` (user-invoked only,
matching upstream), the rest are model-invocable and appear in the session
skill catalog.

## Verify

- The session catalog advertises the model-invocable skills; load one with the
  harness `skill` tool, e.g. `skill(name="tdd")`.
- User-invoked skills work the same way through the skill UI.
- Plugin unit check: `node harness/test.mjs` (mock registry; lists all 38
  candidates and loads a full body).

## Keeping up with upstream

```bash
git checkout deepseek-harness
git fetch upstream
git merge upstream/main          # resolve conflicts in README.md if any
node harness/install.mjs         # rebuilds skills-index.json and reinstalls
```

If a new upstream skill appears, `install.mjs` picks it up automatically. The
fork adds no modifications to `skills/`, `docs/`, or the Claude Code plugin
manifests, so merges stay clean.
