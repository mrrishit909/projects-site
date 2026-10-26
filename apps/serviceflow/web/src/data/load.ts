// Loads the published snapshot: manifest.json then every entity file it lists, relative to BASE_URL + "data/".
// On any failure it returns an explicit error; nothing is ever invented. `?dataset=golden` reads data/golden/ (the
// hand-derived fixture) instead.
import type { Manifest, PipelineInputs } from "../domain/types";
import { buildInputs, isManifest, listedFiles } from "./inputs";

export interface Snapshot {
  manifest: Manifest;
  inputs: PipelineInputs;
  /** True when this is the golden fixture, not the published dataset. */
  golden: boolean;
  /** shift_breaks rows (the data-load-only table of recorded breaks); display only. */
  shiftBreaks: { break_id: string; shift_id: string; agent_id: string; starts_at: string; ends_at: string }[];
}
export type LoadResult = { ok: true; snapshot: Snapshot } | { ok: false; error: string };

export function datasetId(): string {
  try { return new URLSearchParams(window.location.search).get("dataset") === "golden" ? "golden" : ""; } catch { return ""; }
}
export const dataUrl = (file: string, dataset = datasetId()): string => `${import.meta.env.BASE_URL}data/${dataset ? `${dataset}/` : ""}${file}`;

async function getJson(url: string, label: string): Promise<unknown> {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${label}: HTTP ${res.status}`);
  try { return await res.json(); } catch { throw new Error(`${label}: response is not valid JSON`); }
}

/** Loads a dataset: the published snapshot (default) or "golden" (the fixture), whatever the address says. */
export async function loadSnapshot(dataset = datasetId()): Promise<LoadResult> {
  try {
    const manifest = await getJson(dataUrl("manifest.json", dataset), "manifest.json");
    if (!isManifest(manifest)) throw new Error("manifest.json: required fields are missing");
    const names = listedFiles(manifest);
    const files = new Map(await Promise.all(names.map(async (n) => [n, await getJson(dataUrl(`${n}.json`, dataset), `${n}.json`)] as const)));
    const inputs = buildInputs(manifest, files);
    const sb = ((files.get("shift_breaks") as { rows?: Snapshot["shiftBreaks"] } | undefined)?.rows) ?? [];
    return { ok: true, snapshot: { manifest, inputs, golden: dataset === "golden", shiftBreaks: sb } };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

/** The Python-produced reference for the three published simulation runs (public/reference/simulation-runs.json). */
export interface ReplicationRef { replications: number; mean_wait_minutes: { n: number; mean: string | null; ci95_half_width: string | null }; censored_tickets_total: number; per_replication_mean_wait_minutes: (string | null)[]; seeds: number[]; replications_without_a_wait: number; label: string; seed: number }
export interface PairedRef { same_demand_paths: boolean; baseline_mean_wait_minutes: ReplicationRef["mean_wait_minutes"]; proposal_mean_wait_minutes: ReplicationRef["mean_wait_minutes"]; difference_mean_wait_minutes: ReplicationRef["mean_wait_minutes"]; paired_replications: number; proposal_better: boolean | null; replications: number; seed: number; seeds: number[]; label: string }
export interface SimReference { produced_by: string; replications?: { count: number; runs: Record<string, ReplicationRef>; paired: { baseline_vs_plus_one_agent: PairedRef; baseline_vs_holdout_intensity: PairedRef } }; runs: { simulation_id: string; seed: number; golden: { waits_minutes: string[]; mean_wait_minutes: string | null; final_completion_minute: string | null; events: { simulation_event_id: string; ticket_id: string; event_type: string; event_at: string }[] }; statistics: Record<string, unknown> }[] }
export async function loadSimReference(): Promise<SimReference> {
  return (await getJson(`${import.meta.env.BASE_URL}reference/simulation-runs.json`, "reference/simulation-runs.json")) as SimReference;
}
