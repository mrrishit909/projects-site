// The counts the site quotes about its own checking (evidence and case-study routes). One place, so the two routes cannot disagree.
// Each is the "passed" figure of the command named beside it, from the final run recorded in docs/contracts.md D-09.
export const TEST_COUNTS = {
  pytest: 342,     // python -m pytest -q -ra (domain, API, PostgreSQL, generator)
  reference: 1823, // python -I tests/reference_check.py (stdlib reference of the golden fixture)
  golden: 3197,     // npm run golden
  review: 95,     // npm run review
  e2e: 90,        // npm run e2e (Playwright)
} as const;
