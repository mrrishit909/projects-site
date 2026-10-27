// @types/node is not a dependency; declare only the Node surface the scripts and e2e specs use.
declare module "node:fs" {
  export function readFileSync(path: string | URL, encoding: "utf8"): string;
  export function writeFileSync(path: string | URL, data: string): void;
  export function mkdirSync(path: string | URL, options?: { recursive?: boolean }): void;
  export function existsSync(path: string | URL): boolean;
}
declare module "node:crypto" {
  export function createHash(alg: string): { update(data: string | Uint8Array): { digest(enc: "hex"): string } };
}
declare const process: { exitCode: number | undefined; env: Record<string, string | undefined> };
