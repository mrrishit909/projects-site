// JSON that keeps what the text says. `JSON.parse` turns 3.0 into 3 and 9007199254740993 into 9007199254740992, so a number the contract must refuse
// (D-09, R8-04: a quantity is an integer of magnitude at most 2**53) would look valid. `parseJsonExact` reads the same grammar but returns a `JsonNumber`
// (the lexeme) for every number that has a fraction or an exponent and for every integer beyond 2**53; those are not integers to the domain
// (`isInt`, `isQuantity` are false for them), exactly as Python reads 3.0 as a float and keeps 9007199254740993 an exact int that the contract refuses.
export class JsonNumber {
  constructor(readonly lexeme: string) {}
  toString(): string { return this.lexeme; }
  toJSON(): string { return this.lexeme; }
}
const NUMBER_RE = /-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/y;
const MAX_SAFE = 9007199254740992n;

export function parseJsonExact(text: string): unknown {
  let i = 0;
  const fail = (msg: string): never => { throw new SyntaxError(`${msg} at position ${i}`); };
  const ws = (): void => { while (i < text.length) { const c = text.charCodeAt(i); if (c === 32 || c === 10 || c === 13 || c === 9) i++; else break; } };
  const value = (depth: number): unknown => {
    if (depth > 512) fail("nesting is too deep");
    ws();
    const c = text[i];
    if (c === "{") {
      i++;
      const o: Record<string, unknown> = {};
      ws();
      if (text[i] === "}") { i++; return o; }
      for (;;) {
        ws();
        if (text[i] !== '"') fail("expected a string key");
        const k = str();
        ws();
        if (text[i] !== ":") fail("expected ':'");
        i++;
        Object.defineProperty(o, k, { value: value(depth + 1), enumerable: true, writable: true, configurable: true });
        ws();
        if (text[i] === ",") { i++; continue; }
        if (text[i] === "}") { i++; return o; }
        fail("expected ',' or '}'");
      }
    }
    if (c === "[") {
      i++;
      const a: unknown[] = [];
      ws();
      if (text[i] === "]") { i++; return a; }
      for (;;) {
        a.push(value(depth + 1));
        ws();
        if (text[i] === ",") { i++; continue; }
        if (text[i] === "]") { i++; return a; }
        fail("expected ',' or ']'");
      }
    }
    if (c === '"') return str();
    if (text.startsWith("true", i)) { i += 4; return true; }
    if (text.startsWith("false", i)) { i += 5; return false; }
    if (text.startsWith("null", i)) { i += 4; return null; }
    NUMBER_RE.lastIndex = i;
    const m = NUMBER_RE.exec(text);
    if (!m) return fail("unexpected token");
    i += m[0].length;
    const lex = m[0];
    if (/[.eE]/.test(lex)) return new JsonNumber(lex);
    const big = BigInt(lex);
    if (big > MAX_SAFE || big < -MAX_SAFE) return new JsonNumber(lex);
    return big === 0n ? 0 : Number(lex);                                  // -0 is the integer 0, as in Python
  };
  const str = (): string => {
    const start = i;
    i++;
    let escaped = false;
    for (;;) {
      if (i >= text.length) fail("unterminated string");
      const c = text.charCodeAt(i);
      if (c === 34) break;
      if (c === 92) { escaped = true; i += 2; continue; }
      if (c < 32) fail("control character in string");
      i++;
    }
    i++;
    const lit = text.slice(start, i);
    return escaped ? (JSON.parse(lit) as string) : lit.slice(1, -1);
  };
  const v = value(0);
  ws();
  if (i !== text.length) fail("trailing characters");
  return v;
}
