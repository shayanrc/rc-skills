#!/usr/bin/env node
/**
 * rc-skills installer. Lives in `harness/` of the rc-skills fork of
 * mattpocock/skills (https://github.com/mattpocock/skills); the skill
 * sources are the fork's own `skills/` tree.
 *
 * Two jobs:
 *   1. Rebuild `skills-index.json` from the `skills/` SKILL.md files.
 *   2. Install the skills, flattened to one directory per skill, into a
 *      DeepSeek Harness skill root:
 *        - project  (default):  <projectRoot>/.dsh/skills   (rank 100)
 *        - user:                ~/.dsh/skills               (rank 400)
 *        - --target <dir>:      any explicit directory
 *
 * Usage:
 *   node install.mjs [--project|--user|--target <dir>|--index-only] [--list]
 */
import { cp, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const forkRoot = resolve(process.env.DSH_RC_SKILLS_SRC ?? join(here, ".."));
const skillsRoot = join(forkRoot, "skills");
const indexFile = join(here, "skills-index.json");

const SKILL_NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/* ------------------------------------------------------------------ */
/* Tiny YAML-subset frontmatter parser (maps of scalars only).         */
/* Upstream frontmatter uses exactly: name, description,               */
/* disable-model-invocation, argument-hint, and one nested `metadata`. */
/* ------------------------------------------------------------------ */
function parseFrontmatter(raw) {
	const firstLineEnd = raw.indexOf("\n");
	if (firstLineEnd < 0) return void 0;
	if (raw.slice(0, firstLineEnd).replace(/\r$/, "") !== "---") return void 0;
	let lineStart = firstLineEnd + 1;
	while (lineStart <= raw.length) {
		const nextNewline = raw.indexOf("\n", lineStart);
		const lineEnd = nextNewline < 0 ? raw.length : nextNewline;
		if (raw.slice(lineStart, lineEnd).replace(/\r$/, "") === "---") {
			const bodyOffset = nextNewline < 0 ? raw.length : nextNewline + 1;
			const frontmatter = raw.slice(firstLineEnd + 1, lineStart);
			const data = parseYamlMap(frontmatter);
			if (typeof data !== "object" || data === null) return void 0;
			return { data, bodyOffset };
		}
		if (nextNewline < 0) return void 0;
		lineStart = nextNewline + 1;
	}
	return void 0;
}

function parseYamlMap(text) {
	const root = {};
	const stack = [{ indent: -1, map: root }];
	for (const line of text.split(/\r?\n/)) {
		if (line.trim() === "" || line.trim().startsWith("#")) continue;
		const m = /^(\s*)([a-zA-Z0-9_-]+):(\s*(.*))?$/.exec(line);
		if (!m) throw new Error(`unsupported frontmatter line: ${JSON.stringify(line)}`);
		const indent = m[1].length;
		const key = m[2];
		const hasValue = m[3] !== void 0;
		const rawValue = m[4] ?? "";
		while (stack.length > 1 && stack[stack.length - 1].indent >= indent) stack.pop();
		const parent = stack[stack.length - 1].map;
		if (hasValue) {
			parent[key] = scalarValue(unquote(rawValue.trim()));
		} else {
			const child = {};
			parent[key] = child;
			stack.push({ indent, map: child });
		}
	}
	return root;
}

function unquote(value) {
	if (value.length >= 2) {
		const first = value[0];
		const last = value[value.length - 1];
		if (first === '"' && last === '"') return value.slice(1, -1).replaceAll('\\"', '"');
		if (first === "'" && last === "'") return value.slice(1, -1).replaceAll("''", "'");
	}
	return value;
}

function scalarValue(value) {
	if (value === "true") return true;
	if (value === "false") return false;
	return value;
}

/* ------------------------------------------------------------------ */
/* Discovery + indexing                                                */
/* ------------------------------------------------------------------ */
async function collectSkillDirs(root) {
	const out = [];
	async function walk(dir) {
		for (const entry of await readdir(dir, { withFileTypes: true })) {
			if (!entry.isDirectory()) continue;
			const full = join(dir, entry.name);
			if (entry.name === "deprecated") continue; // upstream: README only, no skills
			let hasSkill = true;
			try {
				await readFile(join(full, "SKILL.md"), "utf8");
			} catch {
				hasSkill = false;
			}
			if (hasSkill) {
				out.push(full);
			} else {
				await walk(full);
			}
		}
	}
	await walk(root);
	out.sort((a, b) => a.localeCompare(b));
	return out;
}

async function buildIndex() {
	const dirs = await collectSkillDirs(skillsRoot);
	const entries = [];
	for (const dir of dirs) {
		const raw = await readFile(join(dir, "SKILL.md"), "utf8");
		const parsed = parseFrontmatter(raw);
		if (parsed === void 0) throw new Error(`no valid frontmatter in ${dir}/SKILL.md`);
		const { data, bodyOffset } = parsed;
		const name = data.name;
		const description = data.description;
		if (typeof name !== "string" || name.length === 0) throw new Error(`missing name in ${dir}/SKILL.md`);
		if (typeof description !== "string" || description.length === 0) throw new Error(`missing description in ${dir}/SKILL.md`);
		if (!SKILL_NAME.test(name)) throw new Error(`invalid skill name "${name}" in ${dir}/SKILL.md`);
		entries.push({
			name,
			description,
			...data.whenToUse !== void 0 ? { whenToUse: String(data.whenToUse) } : {},
			modelInvocable: data["disable-model-invocation"] !== true,
			userInvocable: data["user-invocable"] !== false,
			...data.metadata !== void 0 && typeof data.metadata === "object" && data.metadata !== null ? { metadata: data.metadata } : {},
			relDir: relative(skillsRoot, dir),
			bodyOffset,
		});
	}
	const names = new Set(entries.map((e) => e.name));
	if (names.size !== entries.length) throw new Error("duplicate skill names detected");
	await writeFile(indexFile, JSON.stringify(entries, null, "\t") + "\n");
	return entries;
}

/* ------------------------------------------------------------------ */
/* Install                                                             */
/* ------------------------------------------------------------------ */
async function installTo(target) {
	const entries = await buildIndex();
	await mkdir(target, { recursive: true });
	for (const entry of entries) {
		const dest = join(target, entry.name);
		await rm(dest, { recursive: true, force: true });
		await cp(join(skillsRoot, entry.relDir), dest, { recursive: true });
	}
	return entries;
}

async function findProjectRoot(cwd) {
	let current = resolve(cwd);
	while (true) {
		try {
			await readdir(join(current, ".git"));
			return current;
		} catch {}
		const parent = dirname(current);
		if (parent === current) return resolve(cwd);
		current = parent;
	}
}

/* ------------------------------------------------------------------ */
/* CLI                                                                 */
/* ------------------------------------------------------------------ */
const args = process.argv.slice(2);
const listOnly = args.includes("--list");
const indexOnly = args.includes("--index-only");
let target;
if (args.includes("--target")) {
	const i = args.indexOf("--target");
	target = args[i + 1];
	if (target === void 0) {
		console.error("--target requires a directory");
		process.exit(2);
	}
} else if (args.includes("--user")) {
	target = join(process.env.DSH_HOME ?? join(homedir(), ".dsh"), "skills");
} else if (indexOnly || listOnly) {
	target = void 0;
} else {
	target = join(await findProjectRoot(process.cwd()), ".dsh", "skills");
}

if (target !== void 0) {
	if (resolve(target).startsWith(forkRoot + "/")) {
		console.error(`refusing to install into ${target}: it is inside this fork repo (the skills already live in skills/). Run from your project root, or pass --target.`);
		process.exit(2);
	}
}
const entries = target !== void 0 ? await installTo(target) : await buildIndex();
console.log(`skills-index.json: ${entries.length} skills (from ${skillsRoot})`);
if (target !== void 0) console.log(`installed ${entries.length} skills into ${target}`);
if (listOnly || target !== void 0) {
	for (const e of entries) console.log(`  ${e.name.padEnd(34)} ${e.modelInvocable ? "model" : "user "}-invocable  ${e.relDir}`);
}
