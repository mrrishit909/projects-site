// The golden fixture as a lab: its dataset (recomputed from inputs.json) and the experiments run through the domain on copies of its inputs.
import { useEffect, useState } from "react";
import type { Dataset } from "../data/analyse";
import { loadDataset } from "../data/load";
import { loadGolden } from "../data/golden";
import { goldenExperiments, type Experiment } from "../domain/sim";

export type GoldenLab = { status: "loading" } | { status: "error"; error: string } | { status: "ready"; ds: Dataset; experiments: Experiment[]; hashes: Record<string, string>; texts: Record<string, string> };
export function useGoldenLab(): GoldenLab {
  const [s, setS] = useState<GoldenLab>({ status: "loading" });
  useEffect(() => {
    let live = true;
    void (async () => {
      const r = await loadDataset("golden");
      if (!r.ok) { if (live) setS({ status: "error", error: r.error }); return; }
      const g = await loadGolden();
      const experiments = goldenExperiments(g.inputs);
      if (live) setS({ status: "ready", ds: r.dataset, experiments, hashes: g.hashes, texts: g.texts });
    })().catch((e: unknown) => { if (live) setS({ status: "error", error: e instanceof Error ? e.message : String(e) }); });
    return () => { live = false; };
  }, []);
  return s;
}
