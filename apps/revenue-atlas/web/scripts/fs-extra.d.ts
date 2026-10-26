// Extra Node surface used by scripts/golden-to-snapshot.ts and e2e (no @types/node dependency).
declare module "node:fs" {
  export function writeFileSync(path: string | URL, data: string): void;
  export function mkdirSync(path: string | URL, opts?: { recursive?: boolean }): void;
}
declare module "node:fs" { export function existsSync(path: string): boolean; }
