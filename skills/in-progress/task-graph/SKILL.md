---
name: task-graph
description: Maintain the project's pending-task dependency graph in docs/task_dependencies.mmd (readable mermaid), regenerating DOT/PNG/SVG representations only on request. Use when the user wants a task graph, asks what's pending or next, plans or re-sequences multi-task work, adds or removes dependencies, or when tracked tasks are created, moved, or closed.
---

# Task Graph

## Purpose

The graph of the project's pending work and its dependencies. `docs/task_dependencies.mmd` is the single source of truth: it holds only the readable structure (nodes, status tags, edges, clusters, title), while the visual layer (colors, line styles, legend, the octagon goal node) lives in a theme file owned by the renderer.

## When to use

- **Automatic (no invocation needed):** update the `.mmd` whenever a task transition changes the graph's shape: a task is created, a status moves between actionable / in-flight / done / blocked, a dependency edge is added or removed, or a goal node fires. Routine status checks that change nothing do not need an edit. Do NOT regenerate the images on every edit.
- **User trigger:** when the user asks "show me the graph", "what's pending?", or "what's next?", render on request and surface the PNG.

## Where the files live

| File | Purpose |
|---|---|
| `docs/task_dependencies.mmd` | Canonical source of truth: the readable mermaid graph |
| `docs/task_dependencies.theme.json` | Optional project override of the default visual layer |
| `docs/task_dependencies.dot` | Generated DOT, produced only on request |
| `docs/task_dependencies.png` | Generated PNG at 150 DPI for inline display, produced only on request |
| `docs/task_dependencies.svg` | Generated SVG for crisp zooming, produced only on request |

The `.mmd` is always checked into git. The generated `.dot`, `.png`, and `.svg` are checked in only when they were generated, and always as a unit: never commit a PNG or SVG without its DOT.

## Status vocabulary

Status rides a `:::status` tag on the node: `nodeId:::status` or `nodeId["label"]:::status`. Seven tags:

- `actionable`: ready to start, nothing blocking it.
- `in-flight`: being worked right now.
- `goal`: the outcome the graph is aiming at, rendered as an octagon.
- `pending`: not yet actionable, waiting on a hard dependency.
- `done`: finished, kept for context until the surrounding work closes.
- `recurring`: a loop or monitor, paused between firings.
- `blocked`: stuck on external state, not on a missing dependency edge.

## Edge semantics

The edge kind rides the arrow form; the label carries the meaning in words.

- `-->` hard dependency: downstream cannot start until upstream finishes.
- `-.->` soft dependency, "surfaced by", or "may obviate".
- `==>` recurring supervision: a loop or monitor watching a goal.

Label edges (`|blocks|` or `-- blocks -->`) so the meaning stays readable without a legend lookup.

## House style

- Palette: green `actionable`, blue `in-flight`, gold `goal` (octagon), white with a dashed outline `pending`, gray `done`, blue with a dotted outline `recurring`, red `blocked`.
- Group nodes into labeled `subgraph` cluster boxes. Recurring loops and monitors get their own `scheduled tasks / loops` cluster.
- The title is a `%%` comment line at the top of the file: `%% <repo name>: pending task dependencies (YYYY-MM-DD HH:MM TZ)\n<one-line note of what changed>`. Update it on every edit; the renderer copies it onto the rendered graph, and the `\n` becomes the line break under the title.
- The visual layer lives in the theme file: the skill default `theme.default.json`, overridable per project by `docs/task_dependencies.theme.json` (override keys win, missing keys fall back to the default). The rendered DOT/PNG/SVG is where the HTML legend and the octagon goal appear.
- Never upload the graph to an external mermaid/Kroki renderer. `mmdc` is not required and must not be used.

## Rendering (on request)

```bash
cd <path-to-this-skill>
python3 scripts/render.py /path/to/project/docs/task_dependencies.mmd
```

An equivalent relative path works too. The renderer parses the `.mmd`, merges the theme, writes `<stem>.dot` next to the `.mmd`, then renders the PNG at 150 DPI and the SVG with the local graphviz `dot`. It prints the paths written, and on any failure it exits non-zero with an error that names the line and the construct. `--theme <file>` forces a specific theme; otherwise `docs/task_dependencies.theme.json` is used when present, else the skill default. Render only when asked, never on every `.mmd` edit.

## Bookkeeping rules

1. **Single source of truth.** The `.mmd` is canonical. Generated `.dot`/`.png`/`.svg` are produced only on request; when generated, commit the bundle together, never a PNG or SVG alone.
2. **Update on every transition that changes the shape.** New task, add a node. Status change, retag. Dependency added, add an edge. Goal fires, retag the goal node and propagate any unblocks.
3. **Keep done nodes around** for the current plan cycle so the graph shows why the pending work has its current shape. Prune them only once the surrounding pending work has all closed.
4. **Title timestamp.** Update the `%%` title line on every edit with the current date, time, and timezone, plus a one-line note of what changed.
5. **Commit message** when updating: short, naming the task that triggered the edit. Examples:
   - `tasks: mark #244 done, add #253 follow-up`
   - `tasks: #251 + #252 to in-flight (V1.4 follow-up workstream)`
   - `tasks: re-render after V1.4 plan close-out`

## Parallel instances

Multiple agent instances (different machines, sibling worktrees, or parent plus subagent) can all edit the `.mmd`, but only with explicit coordination. It is a single shared text file: git handles the sync, and the workflow below keeps the rendered files from drifting.

| scenario | OK? | mechanism |
|---|---|---|
| Different machines, both pull main | yes | Standard git workflow. First push wins; second hits non-fast-forward and rebases. |
| Same machine, separate sibling worktrees | yes | git treats them as independent checkouts. |
| Parent + subagent in their own worktrees | yes | The subagent commits the `.mmd` edit in its branch; the parent picks up the merged state after it lands. |
| Same machine, same working tree | no | Both instances stomp the index and working tree. Don't do this. |

Rules:

1. **`git pull --rebase` before editing the `.mmd`.** From a worktree: `git fetch origin main && git rebase origin/main`. This kills the most common conflict source.
2. **On conflict, re-render from the merged `.mmd`, never hand-merge the generated files.** Git can't reconcile binaries. After resolving the `.mmd` text conflict, delete the stale `.png` and `.svg` and run the renderer again.
3. **One writer per cycle.** A subagent that closes a task bundles the `.mmd` edit into its own branch. The parent does not also write the `.mmd` in the same cycle; it picks up the merged state afterwards.
4. **Sibling worktrees, not shared working trees.** Two instances against the same checkout stomp the index. `git worktree add wt-<purpose>` is cheap; use it for isolation.
5. **No locking.** The file is too small to need a mutex. Pull-rebase plus re-render handles the common case cleanly.

## Cross-references

- `to-tickets`: the tickets it writes declare blocking edges, which become the hard `-->` edges of this graph.
- `wayfinder`: its decision tickets are pending work worth tracking here while the map is open.
- `implement-spec`: it works a spec's tickets as a task graph; this skill is the visual layer that graph gets rendered through on request.

These are contextual pointers: they name neighboring skills, not operative Skill-tool calls.
