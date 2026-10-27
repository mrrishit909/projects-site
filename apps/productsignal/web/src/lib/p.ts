// How to print a p-value that the six-place figure cannot carry (D-10, R6-12): "0.000001" is a rounded value, so it is read as "p < 0.000001"
// when the exact value (fixed point, nine places) is below it. The figure itself stays the domain's string.
import { chi2SfDf1 } from "../domain/stats";
import { fracOf, fxQ } from "../domain/num";

export function pReading(statistic: string | null, pValue: string | null): string {
  if (statistic === null || pValue === null) return "n/a";
  const exact = fxQ(chi2SfDf1(fracOf(statistic)), 9);       // chi-square, one degree of freedom (D-10: two arms only)
  return Number(exact) < 0.000001 ? "p < 0.000001" : `p ${pValue}`;
}
