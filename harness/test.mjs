/**
 * Standalone check for lib/index.js: exercises the provider contract
 * (registerProvider -> list() -> get()) against a mock skill registry,
 * without a live cordis host.
 */
import assert from "node:assert/strict";
import { PLUGIN_SOURCE, PLUGIN_RANK, apply } from "./lib/index.js";

// Capture the provider the plugin registers.
let captured;
const mockRegistry = {
	registerProvider(create) {
		captured = create({
			signal: new AbortController().signal,
			invalidate() {},
		});
	},
};

apply({ skills: mockRegistry });

assert.ok(captured, "plugin must register a provider");
assert.equal(captured.name, "rc-skills");

// list(): 39 candidates, each honoring the registry's candidate contract.
const candidates = await captured.list({});
assert.equal(candidates.length, 39, "expected all 39 skills");

const names = new Set(candidates.map((c) => c.name));
assert.equal(names.size, 39, "skill names must be unique");
assert.ok(names.has("tdd") && names.has("grilling") && names.has("loop-me"), "spot-check known skills");

for (const c of candidates) {
	assert.match(c.name, /^[a-z0-9]+(?:-[a-z0-9]+)*$/, "kebab-case name");
	assert.equal(typeof c.description, "string");
	assert.ok(c.description.length > 0);
	assert.equal(c.source, PLUGIN_SOURCE);
	assert.equal(c.rank, PLUGIN_RANK);
	assert.equal(c.provider, captured.name);
	assert.deepEqual(c.invocation, {
		modelInvocable: c.invocation.modelInvocable,
		userInvocable: c.invocation.userInvocable,
	});
	assert.equal(typeof c.locator, "object");
	assert.equal(typeof c.resourceBase.path, "string");
	assert.equal(typeof c.path, "string");
}

// get(): full definitions load, body content is non-trivial and trimmed.
let modelInvocable = 0;
let userOnly = 0;
for (const c of candidates) {
	if (c.invocation.modelInvocable) modelInvocable += 1;
	else userOnly += 1;
	const def = await captured.get(c, {});
	assert.equal(def.name, c.name);
	assert.equal(def.description, c.description);
	assert.ok(def.content.length > 10, `body for ${c.name} should be non-trivial (got ${def.content.length} chars)`);
	assert.equal(def.content, def.content.trim(), `body for ${c.name} should be trimmed`);
	assert.equal(def.resourceBase.kind, "directory");
}
assert.equal(modelInvocable, 16, "16 skills are model-invocable");
assert.equal(userOnly, 23, "23 skills are user-invoked only");

// get() on a missing skill returns undefined (candidate locator points nowhere).
const ghost = await captured.get({
	name: "tdd",
	locator: { relDir: "no/such/dir", bodyOffset: 0 },
}, {});
assert.equal(ghost, void 0);

console.log(`provider OK: ${candidates.length} skills, ${modelInvocable} model-invocable, ${userOnly} user-only; full bodies load`);
