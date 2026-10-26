// The as-of date and the fixture state a view is computed at, read from the address and checked against the data.
import { useMemo } from "react";
import { manifestAsOf, manifestWindowStart } from "../data/inputs";
import { dayEnd, dayOf, dayStr, parseTs, tryParseDay } from "../domain/time";
import type { Manifest, StateSpec } from "../domain/types";
import type { Window } from "../domain/metrics";
import type { Ready } from "./atlas";
import type { ViewState } from "./filters";

export interface Scenario {
  /** The as-of instant (23:59:59 UTC of the chosen day) and its day number and text. */
  asOf: number; day: number; text: string;
  /** The first and last selectable day. */
  min: string; max: string; minDay: number; maxDay: number;
  /** [first observed day, open end]. */
  window: Window;
  stateName: string; state: StateSpec | null; stateNames: string[];
  /** Problems with the address, shown to the reader; the default is used instead. */
  notices: string[];
}

export function useScenarioOf(s: Ready, view: ViewState): Scenario {
  const m = s.snapshot.manifest;
  return useMemo(() => scenarioOf(m, view.asOf, view.state), [m, view.asOf, view.state]);
}

function scenarioOf(m: Manifest, asOfParam: string, stateParam: string): Scenario {
  const maxMs = parseTs(manifestAsOf(m));
  const startIso = manifestWindowStart(m);
  const startMs = startIso ? parseTs(startIso) : parseTs(manifestAsOf(m));
  const minDay = dayOf(startMs), maxDay = dayOf(maxMs);
  const notices: string[] = [];
  let day = maxDay;
  if (asOfParam) {
    const d = tryParseDay(asOfParam);
    if (d === null) notices.push(`as_of=${asOfParam} is not a date (YYYY-MM-DD); showing ${dayStr(maxDay)}.`);
    else if (d < minDay || d > maxDay) notices.push(`as_of=${asOfParam} is outside the data (${dayStr(minDay)} to ${dayStr(maxDay)}); showing ${dayStr(maxDay)}.`);
    else day = d;
  }
  const names = Object.keys(m.states ?? {});
  let stateName = "", state: StateSpec | null = null;
  if (stateParam) {
    if (names.includes(stateParam)) { stateName = stateParam; state = m.states![stateParam]!; }
    else notices.push(names.length ? `state=${stateParam} is not a fixture state (${names.join(", ")}); showing the accepted population.` : `state=${stateParam} applies to the golden fixture only (?dataset=golden); showing the accepted population.`);
  }
  return { asOf: day === maxDay ? maxMs : dayEnd(day), day, text: dayStr(day), min: dayStr(minDay), max: dayStr(maxDay), minDay, maxDay, window: [startMs, null], stateName, state, stateNames: names, notices };
}
