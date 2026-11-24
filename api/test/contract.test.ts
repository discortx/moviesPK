// Cross-language contract suite, TypeScript side (plan §13): the same fixtures as the
// Python suite must pass (valid) or fail (invalid) the Zod schemas; vocabularies must
// equal shared/constants.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { CONTRACT_SCHEMAS } from "../src/schemas/contract.js";
import { POSTER_KEY_PATTERN, POSTER_WIDTHS, VOCABULARIES } from "../src/schemas/vocab.js";

const SHARED = join(import.meta.dirname, "..", "..", "shared");
const FIXTURES = join(SHARED, "fixtures", "contract");
const CONSTANTS = join(SHARED, "constants");

const readJson = (path: string): unknown => JSON.parse(readFileSync(path, "utf8"));

function lookup<T>(table: Record<string, T>, key: string): T {
  const value = table[key];
  if (value === undefined) throw new Error(`no entry for ${key}`);
  return value;
}

function cases(kind: "valid" | "invalid"): [string, string, string][] {
  const out: [string, string, string][] = [];
  for (const type of readdirSync(join(FIXTURES, kind)).sort()) {
    for (const file of readdirSync(join(FIXTURES, kind, type)).sort()) {
      out.push([`${type}/${file}`, type, join(FIXTURES, kind, type, file)]);
    }
  }
  return out;
}

describe("contract fixtures", () => {
  it("every schema type has a Zod schema", () => {
    const types = readdirSync(join(SHARED, "schemas"))
      .map((f) => f.replace(/\.json$/, ""))
      .filter((t) => t !== "common")
      .sort();
    expect(Object.keys(CONTRACT_SCHEMAS).sort()).toEqual(types);
  });

  it.each(cases("valid"))("valid %s passes", (_id, type, path) => {
    const result = lookup(CONTRACT_SCHEMAS, type).safeParse(readJson(path));
    expect(result.error?.issues ?? []).toEqual([]);
  });

  it.each(cases("invalid"))("invalid %s fails", (_id, type, path) => {
    expect(lookup(CONTRACT_SCHEMAS, type).safeParse(readJson(path)).success).toBe(false);
  });
});

describe("vocabularies", () => {
  it.each(Object.keys(VOCABULARIES).sort())("%s equals shared/constants", (name) => {
    expect([...lookup(VOCABULARIES, name)]).toEqual(readJson(join(CONSTANTS, `${name}.json`)));
  });

  it("every vocabulary file is covered", () => {
    const files = readdirSync(CONSTANTS)
      .filter((f) => f.endsWith(".json"))
      .map((f) => f.replace(/\.json$/, ""))
      .filter((f) => !["cities", "images", "bounds"].includes(f))
      .sort();
    expect(Object.keys(VOCABULARIES).sort()).toEqual(files);
  });

  it("image constants match", () => {
    const images = readJson(join(CONSTANTS, "images.json")) as {
      posterWidths: number[];
      posterKeyPattern: string;
    };
    expect(images.posterWidths).toEqual([...POSTER_WIDTHS]);
    expect(images.posterKeyPattern).toBe(POSTER_KEY_PATTERN);
  });
});
