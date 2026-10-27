// The three hash kinds of D-P8-10: payload_hash, content_hash, definition_hash. sha256, canonical JSON, no float.
import { sha256Hex } from "./sha256";

/** Python's `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)`; a float is refused. */
export function canonicalJson(v: unknown): string {
  if (v === null || v === undefined) return "null";
  switch (typeof v) {
    case "boolean": return v ? "true" : "false";
    case "number":
      if (!Number.isInteger(v)) throw new RangeError("a float is not allowed in a canonical payload");
      return String(v);
    case "string": return asciiString(v);
    case "object": {
      if (Array.isArray(v)) return `[${v.map(canonicalJson).join(",")}]`;
      const keys = Object.keys(v as object).sort(cmpCodePoints);
      return `{${keys.map((k) => `${asciiString(k)}:${canonicalJson((v as Record<string, unknown>)[k])}`).join(",")}}`;
    }
    default: throw new RangeError(`not JSON: ${typeof v}`);
  }
}
const asciiString = (s: string): string => JSON.stringify(s).replace(/[\u007f-￿]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`);
/** String order by code point (Python's), which differs from UTF-16 order only for astral characters. */
export function cmpCodePoints(a: string, b: string): number {
  if (a === b) return 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    const x = a.charCodeAt(i), y = b.charCodeAt(i);
    if (x === y) continue;
    const sx = x >= 0xd800 && x <= 0xdfff, sy = y >= 0xd800 && y <= 0xdfff;
    if (sx !== sy) return sx ? 1 : -1;                              // an astral character (a surrogate pair) is above every BMP one
    return x < y ? -1 : 1;
  }
  return a.length < b.length ? -1 : 1;
}
export const payloadHash = (payload: unknown): string => sha256Hex(canonicalJson(payload));
/** sha256 of the sorted payload hashes of the included accepted records, joined with a newline. */
export const contentHash = (hashes: Iterable<string>): string => sha256Hex([...hashes].sort(cmpCodePoints).join("\n"));
export const definitionHash = (definition: string): string => sha256Hex(definition);
