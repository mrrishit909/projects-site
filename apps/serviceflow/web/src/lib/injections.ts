// The injection manifest (the generator's list of planted defects): fetched once, never required for a figure.
import { useEffect, useState } from "react";

export interface Injection { id: string; entity: string; record_ids: string[]; description: string; expected_handling?: string; test?: string }
export type Injections = { status: "loading" } | { status: "error"; error: string } | { status: "ready"; injections: Injection[]; relationships: string[] };
let cached: Promise<{ injections: Injection[]; relationships: string[] }> | null = null;
const fetchOnce = (): Promise<{ injections: Injection[]; relationships: string[] }> =>
  (cached ??= fetch(`${import.meta.env.BASE_URL}data/injection-manifest.json`, { headers: { Accept: "application/json" } })
    .then((r) => { if (!r.ok) throw new Error(`injection-manifest.json: HTTP ${r.status}`); return r.json() as Promise<{ injections?: Injection[]; designed_relationships?: string[] }>; })
    .then((j) => ({ injections: j.injections ?? [], relationships: j.designed_relationships ?? [] })));

export function useInjections(): Injections {
  const [s, setS] = useState<Injections>({ status: "loading" });
  useEffect(() => {
    let live = true;
    fetchOnce().then((j) => { if (live) setS({ status: "ready", ...j }); }).catch((e: unknown) => { cached = null; if (live) setS({ status: "error", error: e instanceof Error ? e.message : String(e) }); });
    return () => { live = false; };
  }, []);
  return s;
}
