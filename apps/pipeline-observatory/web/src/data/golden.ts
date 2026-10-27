// The golden fixture ships inside the bundle (a separate chunk, loaded only when a screen asks for it): the browser recomputes it from inputs.json
// exactly as the node checks do, and hashes the very text it holds against HASHES.json. The files are imported from tests/fixtures/golden so there is
// one copy of the fixture in the repository.
export interface GoldenFiles { inputsText: string; expectedText: string; hashes: Record<string, string>; texts: Record<string, string>; inputs: Record<string, unknown>; expected: Record<string, unknown> }
let cached: Promise<GoldenFiles> | null = null;
export function loadGolden(): Promise<GoldenFiles> {
  cached ??= (async (): Promise<GoldenFiles> => {
    const [a, b, c, d, e, f, g, h] = await Promise.all([
      import("../../../tests/fixtures/golden/inputs.json?raw"), import("../../../tests/fixtures/golden/expected.json?raw"), import("../../../tests/fixtures/golden/HASHES.json?raw"),
      import("../../../tests/fixtures/golden/CALCULATION.md?raw"), import("../../../tests/fixtures/golden/variant-rejected/inputs.json?raw"), import("../../../tests/fixtures/golden/variant-rejected/expected.json?raw"),
      import("../../../tests/fixtures/golden/variant-empty/inputs.json?raw"), import("../../../tests/fixtures/golden/variant-empty/expected.json?raw")]);
    const texts: Record<string, string> = { "inputs.json": a.default, "expected.json": b.default, "CALCULATION.md": d.default, "variant-rejected/inputs.json": e.default, "variant-rejected/expected.json": f.default,
      "variant-empty/inputs.json": g.default, "variant-empty/expected.json": h.default };
    return { inputsText: a.default, expectedText: b.default, hashes: (JSON.parse(c.default) as { sha256: Record<string, string> }).sha256, texts, inputs: JSON.parse(a.default), expected: JSON.parse(b.default) };
  })();
  return cached;
}
