// @types/node is not a dependency; declare only the Node surface golden-check.ts uses.
declare module "node:fs" {
  export function readFileSync(path: string | URL, encoding: "utf8"): string;
}
declare const process: { exitCode: number | undefined };
