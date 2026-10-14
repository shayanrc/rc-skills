/**
 * rc-skills, a DeepSeek Harness skill plugin. rc-skills is a fork of
 * mattpocock/skills by Matt Pocock (https://github.com/mattpocock/skills);
 * this plugin lives in `harness/` of the fork and registers a same-process
 * skill provider that serves every SKILL.md under `skills/`.
 * The registry contract is the one defined by `@deepseek-ai/dsh-skill`:
 *
 *   - `list(options)`  -> candidate summaries (name/description/invocation/...)
 *   - `get(candidate)` -> the full skill definition, including body content
 *
 * Skill bodies are shipped verbatim inside `skills/` (the upstream repo,
 * category layout preserved). `skills-index.json` carries the parsed
 * frontmatter (name, description, invocation policy, metadata, body offset)
 * so the provider needs no YAML dependency at runtime.
 *
 * Install modes (see `install.mjs`):
 *   - project:  <projectRoot>/.dsh/skills/<name>/   (filesystem provider, rank 100)
 *   - user:     ~/.dsh/skills/<name>/                (filesystem provider, rank 400)
 *   - profile:  this package inside the profile's node_modules (this provider)
 */
import { readFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const name = "skill-rc-skills";
export const inject = ["skills"];

/** Where candidates come from, as reported in the skill catalog. */
export const PLUGIN_SOURCE = "plugin-rc-skills";
/**
 * Precedence: above user-level skill roots (400/500) and bundled skills (600),
 * below project roots (100/200) and configured custom dirs (300).
 */
export const PLUGIN_RANK = 350;

const libDir = dirname(fileURLToPath(import.meta.url));
const forkRoot = resolve(libDir, "..", "..");
const skillsRoot = resolve(process.env.DSH_RC_SKILLS_DIR ?? join(forkRoot, "skills"));
const indexFile = resolve(process.env.DSH_RC_SKILLS_INDEX ?? join(libDir, "..", "skills-index.json"));

/** Load and index the shipped skill catalog once per provider lifetime. */
async function loadIndex() {
	const entries = JSON.parse(await readFile(indexFile, "utf8"));
	const map = new Map();
	for (const entry of entries) map.set(entry.name, entry);
	return map;
}

/** Register the provider on the host's skill registry. */
export function apply(ctx) {
	ctx.skills.registerProvider((control) => new RcSkillsSkillProvider(ctx, control));
}

class RcSkillsSkillProvider {
	name = "rc-skills";
	#control;
	#indexPromise;
	#index;

	constructor(ctx, control) {
		this.#control = control;
		control.signal.addEventListener(
			"abort",
			() => {
				this.#index = void 0;
			},
			{ once: true },
		);
	}

	async #ensureIndex() {
		this.#indexPromise ??= loadIndex();
		const entries = await this.#indexPromise;
		if (this.#index === void 0) this.#index = new Map(entries);
		return this.#index;
	}

	/**
	 * List invocation-neutral candidate summaries for every replicated skill.
	 * @param options - registry view options; `signal` cancels discovery.
	 */
	async list(options) {
		this.#control.signal.throwIfAborted();
		const index = await this.#ensureIndex();
		options?.signal?.throwIfAborted();
		const candidates = [];
		for (const entry of index.values()) {
			candidates.push(this.#toCandidate(entry));
		}
		return candidates;
	}

	/**
	 * Load one full skill definition, reading the SKILL.md shipped with the
	 * package and slicing the body at the offset recorded in the index.
	 */
	async get(candidate, options) {
		this.#control.signal.throwIfAborted();
		const entry = candidate.locator;
		const filePath = join(skillsRoot, entry.relDir, "SKILL.md");
		let text;
		try {
			text = await readFile(filePath, "utf8");
		} catch (error) {
			if (error?.code === "ENOENT") return void 0;
			throw error;
		}
		options?.signal?.throwIfAborted();
		return {
			...this.#toCandidate(entry),
			content: text.slice(entry.bodyOffset).trim(),
		};
	}

	#toCandidate(entry) {
		return {
			name: entry.name,
			description: entry.description,
			...entry.whenToUse !== void 0 ? { whenToUse: entry.whenToUse } : {},
			invocation: {
				modelInvocable: entry.modelInvocable,
				userInvocable: entry.userInvocable,
			},
			source: PLUGIN_SOURCE,
			rank: PLUGIN_RANK,
			provider: this.name,
			resourceBase: {
				kind: "directory",
				path: join(skillsRoot, entry.relDir),
			},
			path: join(skillsRoot, entry.relDir, "SKILL.md"),
			...entry.metadata !== void 0 ? { metadata: entry.metadata } : {},
			locator: entry,
		};
	}
}
