// Code-point order for strings (R5-16): Python and PostgreSQL ("C" collation) order text by code point, while JavaScript's
// `<` and `.sort()` order by UTF-16 code unit, which puts a character outside the BMP (a surrogate pair, 0xD800..0xDFFF) BEFORE
// U+E000..U+FFFF. Every ordering that decides a result goes through this comparator.
export function cmp(a: string, b: string): number {
  if (a === b) return 0;
  let i = 0, j = 0;
  while (i < a.length && j < b.length) {
    const ca = a.codePointAt(i)!, cb = b.codePointAt(j)!;
    if (ca !== cb) return ca < cb ? -1 : 1;
    i += ca > 0xffff ? 2 : 1;
    j += cb > 0xffff ? 2 : 1;
  }
  return i < a.length ? 1 : j < b.length ? -1 : 0;
}
