// Python's `random.Random(<str>)` (CPython 3.11): the string seed is hashed with SHA-512 and fed to MT19937 through
// init_by_array; `random()`, `expovariate` and `choices` follow random.py. This lets the browser draw the same demand
// path as domain/serviceflow/simulation.py for the same seed. The only floating-point values are the generator's own
// draws (as in Python); nothing downstream of the rounding to 1/10000 minute is floating point.

const M64 = (x: bigint): bigint => BigInt.asUintN(64, x);
function iroot(n: bigint, k: bigint): bigint { // floor(n^(1/k)) by Newton
  if (n < 2n) return n;
  let x = 1n << BigInt(Math.ceil(n.toString(2).length / Number(k)) + 1);
  for (;;) {
    const y = ((k - 1n) * x + n / x ** (k - 1n)) / k;
    if (y >= x) return x;
    x = y;
  }
}
const PRIMES: number[] = [];
for (let n = 2; PRIMES.length < 80; n++) if (PRIMES.every((p) => n % p !== 0)) PRIMES.push(n);
// FIPS 180-4: first 64 fractional bits of the square roots (initial hash) and cube roots (round constants) of the primes.
const H0 = PRIMES.slice(0, 8).map((p) => M64(iroot(BigInt(p) << 128n, 2n)));
const K = PRIMES.map((p) => M64(iroot(BigInt(p) << 192n, 3n)));
const rotr = (x: bigint, n: bigint): bigint => M64((x >> n) | (x << (64n - n)));

export function sha512(msg: Uint8Array): Uint8Array {
  const len = msg.length;
  const total = Math.ceil((len + 17) / 128) * 128;
  const buf = new Uint8Array(total);
  buf.set(msg); buf[len] = 0x80;
  let bits = BigInt(len) * 8n;
  for (let i = 0; i < 16; i++) { buf[total - 1 - i] = Number(bits & 0xffn); bits >>= 8n; }
  const h = [...H0];
  const w = new Array<bigint>(80).fill(0n);
  for (let off = 0; off < total; off += 128) {
    for (let t = 0; t < 16; t++) { let v = 0n; for (let b = 0; b < 8; b++) v = (v << 8n) | BigInt(buf[off + t * 8 + b]!); w[t] = v; }
    for (let t = 16; t < 80; t++) {
      const s0 = rotr(w[t - 15]!, 1n) ^ rotr(w[t - 15]!, 8n) ^ (w[t - 15]! >> 7n);
      const s1 = rotr(w[t - 2]!, 19n) ^ rotr(w[t - 2]!, 61n) ^ (w[t - 2]! >> 6n);
      w[t] = M64(w[t - 16]! + s0 + w[t - 7]! + s1);
    }
    let [a, b, c, d, e, f, g, hh] = h as [bigint, bigint, bigint, bigint, bigint, bigint, bigint, bigint];
    for (let t = 0; t < 80; t++) {
      const S1 = rotr(e, 14n) ^ rotr(e, 18n) ^ rotr(e, 41n);
      const ch = (e & f) ^ (~e & g);
      const t1 = M64(hh + S1 + M64(ch) + K[t]! + w[t]!);
      const S0 = rotr(a, 28n) ^ rotr(a, 34n) ^ rotr(a, 39n);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = M64(S0 + maj);
      hh = g; g = f; f = e; e = M64(d + t1); d = c; c = b; b = a; a = M64(t1 + t2);
    }
    [a, b, c, d, e, f, g, hh].forEach((v, i) => { h[i] = M64(h[i]! + v); });
  }
  const out = new Uint8Array(64);
  h.forEach((v, i) => { for (let b = 0; b < 8; b++) out[i * 8 + 7 - b] = Number((v >> BigInt(8 * b)) & 0xffn); });
  return out;
}

const N = 624, MM = 397;
export class PyRandom {
  private mt = new Uint32Array(N);
  private idx = N + 1;

  /** `random.Random(seed)` for a str seed (version 2 seeding). */
  constructor(seed: string) {
    const raw = new TextEncoder().encode(seed);
    const digest = sha512(raw);
    let v = 0n;
    for (const b of raw) v = (v << 8n) | BigInt(b);
    for (const b of digest) v = (v << 8n) | BigInt(b);
    const key: number[] = [];
    while (v > 0n) { key.push(Number(v & 0xffffffffn)); v >>= 32n; }
    if (key.length === 0) key.push(0);
    this.initByArray(key);
  }

  private initGenrand(s: number): void {
    const mt = this.mt;
    mt[0] = s >>> 0;
    for (let i = 1; i < N; i++) mt[i] = (Math.imul(1812433253, mt[i - 1]! ^ (mt[i - 1]! >>> 30)) + i) >>> 0;
    this.idx = N;
  }
  private initByArray(key: number[]): void {
    this.initGenrand(19650218);
    const mt = this.mt;
    let i = 1, j = 0;
    for (let k = Math.max(N, key.length); k > 0; k--) {
      mt[i] = ((mt[i]! ^ Math.imul(mt[i - 1]! ^ (mt[i - 1]! >>> 30), 1664525)) + key[j]! + j) >>> 0;
      i++; j++;
      if (i >= N) { mt[0] = mt[N - 1]!; i = 1; }
      if (j >= key.length) j = 0;
    }
    for (let k = N - 1; k > 0; k--) {
      mt[i] = ((mt[i]! ^ Math.imul(mt[i - 1]! ^ (mt[i - 1]! >>> 30), 1566083941)) - i) >>> 0;
      i++;
      if (i >= N) { mt[0] = mt[N - 1]!; i = 1; }
    }
    mt[0] = 0x80000000;
    this.idx = N;
  }
  private genrand(): number {
    const mt = this.mt;
    if (this.idx >= N) {
      let kk = 0;
      const mag = (y: number): number => (y & 1 ? 0x9908b0df : 0);
      for (; kk < N - MM; kk++) { const y = (mt[kk]! & 0x80000000) | (mt[kk + 1]! & 0x7fffffff); mt[kk] = mt[kk + MM]! ^ (y >>> 1) ^ mag(y); }
      for (; kk < N - 1; kk++) { const y = (mt[kk]! & 0x80000000) | (mt[kk + 1]! & 0x7fffffff); mt[kk] = mt[kk + (MM - N)]! ^ (y >>> 1) ^ mag(y); }
      const y = (mt[N - 1]! & 0x80000000) | (mt[0]! & 0x7fffffff);
      mt[N - 1] = mt[MM - 1]! ^ (y >>> 1) ^ mag(y);
      this.idx = 0;
    }
    let y = mt[this.idx++]!;
    y ^= y >>> 11; y ^= (y << 7) & 0x9d2c5680; y ^= (y << 15) & 0xefc60000; y ^= y >>> 18;
    return y >>> 0;
  }
  /** Uniform in [0, 1) with 53 random bits. */
  random(): number { const a = this.genrand() >>> 5, b = this.genrand() >>> 6; return (a * 67108864 + b) * (1 / 9007199254740992); }
  /** random.expovariate(lambd). */
  expovariate(lambd: number): number { return -Math.log(1 - this.random()) / lambd; }
  /** random.choices(population, weights)[0]. */
  choice<T>(population: readonly T[], weights: readonly number[]): T {
    const cum: number[] = []; let acc = 0;
    for (const w of weights) { acc += w; cum.push(acc); }
    const total = cum[cum.length - 1]! + 0.0;
    const x = this.random() * total;
    let lo = 0, hi = population.length - 1;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (x < cum[mid]!) hi = mid; else lo = mid + 1; }
    return population[lo]!;
  }
}
