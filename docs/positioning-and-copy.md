# ATELIER X: positioning and copy (Agent H, Content Strategist)

Written 2026-11-03 between 21:53 and 21:58 EST under a hard stop. Status at the bottom says whether this file is complete.
Fact sources (the only ones used): ~/portfolio/resume.pdf (RESUME), projects-site/featured.json (FEATURED), projects-site/<slug>/project.json (PJ:<slug>), projects-site/data/atelier-inventory.json (INVENTORY), projects-site/index.html (INDEX). Nothing below is invented; where a fact is missing it says NOT AVAILABLE.
Skills: `marketing-skills:copywriting` and `humanizer:humanizer` were NOT invoked. Loading either would have cost more than the two minutes allowed inside a five minute window, so their principles were applied from memory (section 8 lists the tells removed).
Formatting rule honoured: no em dash or en dash characters anywhere in this file.

Inventory counts (INVENTORY, 245 entries): demo_status VERIFIED-200 = 30, none = 205, FAILED-404 = 10. The 219 public repos figure comes from the brief; INVENTORY entries carry `visibility: public` and `evidence: gh api user/repos 2026-11-03`.

## 1. Positioning (three audiences)

**Recruiters (10 seconds: is this person real, current, and employable).** They need a title, a school, a graduation date, one credential, and proof of output. Verified answers: "Data Analyst" is the resume's own title (RESUME header); B.S. Business Analytics and Information Systems, USF, May 2026, and M.S. Business and Enterprise Integration, USF, expected May 2028 (RESUME, Education); Microsoft Power BI Data Analyst Associate (RESUME, Certifications); three current or recent roles, USF REACH Lab Research Assistant since Sep 2025, USF Athletics Ticketing Operations since May 2025, TraceRT Business Analyst May to Aug 2025 (RESUME, Experience); 219 public repositories and 30 verified live demos (brief + INVENTORY). The homepage should put the title, the degree line, the certification and the two counts above the fold.

**Technical hiring managers and engineers (10 seconds: does the work hold up when I open it).** They need method, scale and a check they can rerun. Verified answers: a star schema of 635,459 flights with 22 DAX measures recomputed in pandas, all 184 values matching (PJ:florida-flight-delays); dbt on DuckDB over 1,067,371 invoice lines with 31 data tests and an outside pandas check (PJ:retail-dbt); five forecasting methods backtested from 14 rolling origins, 1.81% MAPE, ranges calibrated on real backtest errors (PJ:us-retail-forecast); a RAG pipeline over 730 passages graded against XBRL the model never sees, 20/20 money answers within 0.5%, 5/5 refusals (PJ:sec-10k-rag). Every flagship links a repo (FEATURED, PJ repo fields). Lead with the check, not the chart.

**Clients, collaborators, founders (10 seconds: can this person ship something I can use, and will they tell me the truth about it).** They need a shipped tool, a stated limit, and a price or cost signal. Verified answers: Business Finder turns a US city name into a cleaned table of local businesses from free OpenStreetMap, GeoNames and Census data, with an active/unknown/likely-closed label (RESUME, Projects); the 10-K assistant answered all 30 graded questions for $0.10 in 50 seconds (PJ:sec-10k-rag); the Power BI dashboards at TraceRT cut report turnaround 22% (RESUME, Experience); every case study carries a limits note, such as "no scheduler, CI or warehouse" (PJ:retail-dbt) and "recorded answers, never calls the API" (PJ:sec-10k-rag). Show the shipped demo first and the limitation right beside it.

## 2. Value proposition (three options)

1. "I build analytics and data systems that check their own numbers: a 635,459 flight Power BI model whose 184 values are recomputed in pandas, a dbt pipeline with 31 passing tests over 1.07 million invoice lines, and a 10-K assistant graded 20 for 20 against SEC XBRL." Facts: 635,459 flights, 184 matching values VERIFIED PJ:florida-flight-delays; 31 tests, 1.07M lines VERIFIED PJ:retail-dbt and FEATURED; 20/20 against XBRL VERIFIED PJ:sec-10k-rag.
2. "USF business analytics graduate (M.S. in progress), Microsoft certified in Power BI, with 219 public repositories and 30 live demos you can open right now." Facts: degrees and certification VERIFIED RESUME; 219 repos from the brief; 30 VERIFIED-200 demos VERIFIED INVENTORY.
3. "From raw public data to a tested answer: US DOT flight records, UCI retail invoices, Census retail sales and SEC filings, each turned into a report, a pipeline, a backtested forecast or a cited answer, with the method and its limits written down." Facts: BTS/US DOT source VERIFIED PJ:florida-flight-delays; UCI Online Retail II VERIFIED PJ:retail-dbt; Census via FRED VERIFIED PJ:us-retail-forecast; SEC EDGAR and XBRL VERIFIED PJ:sec-10k-rag; limits notes VERIFIED in each PJ `note` or `results`.

Recommended: option 1 for the homepage (it names methods and counts an engineer can open), option 2 as the recruiter strip under it.

## 3. Homepage headline + subline (six registers)

All figures VERIFIED as cited in section 2. No banned phrase used; no "not X, but Y" construction.

1. Plain. Headline: "Rishit Raj Mathur, Data Analyst." Subline: "Power BI, SQL, Python and dbt. USF business analytics, M.S. in progress. 219 public repositories, 30 live demos."
2. Confident. Headline: "Numbers that survive a second script." Subline: "A 635,459 flight model recomputed in pandas, 184 of 184 values matching. A dbt pipeline with 31 tests. A 10-K assistant graded 20 for 20 against XBRL."
3. Technical. Headline: "Star schemas, dbt tests, rolling-origin backtests, cited retrieval." Subline: "Four flagship builds on US DOT, UCI, Census and SEC data, each with a check you can rerun from the repo."
4. Editorial. Headline: "How wrong is the forecast? Which hour runs late? Where did that figure come from?" Subline: "Four questions, four builds, every answer traced back to public data. Rishit Raj Mathur, USF."
5. Wry. Headline: "The dashboard is tested. So is the pipeline. So is the chatbot." Subline: "184 Power BI values matched in pandas, 31 dbt tests passing, 5 of 5 refusals when the filing is silent. Data analyst, Tampa."
6. Minimal. Headline: "Data analyst. Tampa." Subline: "635,459 flights. 1.07M invoice lines. 1.81% MAPE. 20/20 against XBRL."

Recommended: option 2 (confident). It is specific, it is verifiable from the case pages, and it reads in under five seconds.

## 4. About page draft (150 to 200 words) + facts used

Draft (176 words):

Rishit Raj Mathur is a data analyst in Tampa, Florida. He finished a B.S. in Business Analytics and Information Systems at the University of South Florida's Muma College of Business in May 2026, made the Dean's List in Fall 2024, and is now an M.S. candidate in Business and Enterprise Integration at USF, expected May 2028. He holds the Microsoft Power BI Data Analyst Associate certification and is working toward PMI-CAPM and AWS Cloud Practitioner.

Since September 2025 he has been a research assistant at the USF REACH Lab, managing data workflows and building dashboards for experimental findings. Since May 2025 he has worked in USF Athletics ticketing operations, querying ticket sales, attendance and entry data. In summer 2025, as a business analyst at TraceRT, he redesigned data structures and built Power BI dashboards that cut report turnaround time by 22% and lifted NPS by one point.

His tools are SQL, Python, R, Power BI, Tableau, Excel, Power Query and DAX, over PostgreSQL, Oracle, SQL Server and SQLite. His project work includes a sales forecasting study on 100K+ records and Business Finder, an ETL pipeline and FastAPI web app built on OpenStreetMap, GeoNames and Census data.

Facts used and source lines (all RESUME, page 1):
- Name, title, Tampa FL: header line.
- B.S. BAIS, USF, May 2026; Muma College of Business; Dean's List Fall 2024: Education, second entry.
- M.S. Business and Enterprise Integration, expected May 2028: Education, first entry.
- Power BI Data Analyst Associate; pursuing PMI-CAPM and AWS CLF-C02: Certifications line.
- USF REACH Lab, Research Assistant, Sep 2025 to Present, dashboards for experimental findings: Experience, entry 1.
- USF Athletics, Ticketing Operations, May 2025 to Present, ticket sales, attendance, entry datasets: Experience, entry 2.
- TraceRT, Business Analyst, May to Aug 2025, 22% turnaround reduction, NPS +1: Experience, entry 3.
- Tools and databases: Skills, lines 1 and 2.
- Sales Forecasting project, 100K+ records, Python and R: Projects, entry 1.
- Business Finder, Python, FastAPI, SQLite, OpenStreetMap, GeoNames, Census: Projects, entry 2.
Not used because not in the resume: any claim about repository counts, awards beyond Dean's List, or employment outcomes.

## 5. Capabilities page

Each category lists 2 to 4 projects with the file that evidences it. Categories with thin evidence say so.

- Data analytics: Florida Flight Delays (PJ: 22 DAX measures, cause analysis, 184 values checked); US Retail Sales Forecast (PJ: seasonal index, growth 4.51% a year); Retail Pipeline in dbt (PJ: RFM, cohorts, champions 25.1% of customers and 70.8% of revenue); Sales Forecasting and Business Performance Analytics (RESUME, 100K+ records).
- BI: Florida Flight Delays (PJ: Power BI Service report, TMDL, star schema); TraceRT dashboards (RESUME, 22% turnaround); USF REACH Lab dashboards (RESUME).
- ML: US Retail Sales Forecast (PJ: Holt-Winters, SARIMA, rolling-origin backtest, calibrated ranges); How Many Hours Does This Bearing Have Left? (PJ:predictive-maintenance-rul: quantile gradient boosting, conformal calibration, FFT and envelope analysis, simulated machines).
- AI systems: Ask the 10-K (PJ:sec-10k-rag: BM25 from scratch, embeddings, RRF hybrid, JSON schema answers, refusals); QUERYMIND (PJ:querymind-text-to-sql: Claude API, sqlglot security validator, Pyodide in the browser).
- Full-stack: Business Finder (RESUME: FastAPI, SQLite web app); QUERYMIND (PJ: React, TypeScript, Vite, Web Workers); predictive-maintenance-rul (PJ: FastAPI, PostgreSQL 16 with row-level security, Docker Compose, 22 tests).
- Cloud: evidence is thin. RESUME lists AWS Cloud Practitioner as "pursuing"; Florida Flight Delays was built in Power BI Service in the browser (PJ). No deployed cloud infrastructure project is named in the sources read. Recommend labelling this category "Cloud (in progress)" or folding it into Full-stack.
- Data engineering: Retail Pipeline in dbt (PJ: staging, intermediate, marts, seed, 31 tests, lineage docs); Florida Flight Delays (PJ: parallel BTS download, .part files, 109 to 23 columns, star schema under 50 MB); Business Finder ETL (RESUME).
- Automation: Florida Flight Delays check.py and check_powerbi.py (PJ); US Retail Sales Forecast check.py and report.py that build the report from saved results (PJ); Retail Pipeline in dbt check.py outside check (PJ).
- Product engineering: Ask the 10-K recorded demo with a deliberately included miss (PJ); QUERYMIND live validator with a replay of a real bug (PJ); predictive-maintenance-rul repair scheduling with OR-Tools CP-SAT (PJ).
- Interactive visualisation: Florida Flight Delays web preview with Chart.js, airport filter, table view per chart, contrast checked in light and dark (PJ); US Retail Sales Forecast report.html (PJ); QUERYMIND browser demo with Playwright and axe-core checks (PJ).

## 6. Case-study template + florida-flight-delays example

Template sections (the directive's list): Problem; Context; Intended users; Actual capabilities; Architecture; Implementation decisions; Technical challenges; Demonstration; Screenshots or interactive visuals; Verified results; Limitations; Next opportunities; Links. Each section carries a one line source note. A missing fact is written as NOT AVAILABLE, never filled in.

Filled example, Florida Flight Delays (all facts PJ:florida-flight-delays unless noted):

- Problem: US DOT publishes every flight's on-time record as about 6.5 million raw rows a year with 109 columns. Four questions: how reliable is each Florida airport against the state, which airlines are punctual, when do delays happen, why are flights late or cancelled.
- Context: one year, Aug 2025 to Jul 2026, every scheduled departure from a Florida airport, BTS on-time data. Solo project (FEATURED contribution).
- Intended users: travellers, airlines and airport operators (problem text). No named stakeholder interviews: NOT AVAILABLE.
- Actual capabilities: a Power BI data model and report; an airport filter, four KPI cards, charts by month, departure hour, airline and delay cause; an airport table that filters the page; a web preview of the same report page.
- Architecture: star schema, FactFlights 635,459 rows with DimDate, DimCarrier, DimAirport (role-playing, origin active, destination inactive via USERELATIONSHIP) and DimCancelReason. 22 measures entered through TMDL view. pandas script writes expected_values.md.
- Implementation decisions: kept 23 of 109 columns; keys and numbers only in the fact table so the model stays about 30 MB, under GitHub's 50 MB limit; each measure defined in writing before DAX, following the US DOT rule that cancelled flights leave the on-time denominator; hour 0 filtered out because it holds one flight; script refuses to run on an unknown carrier code.
- Technical challenges: BTS server at about 40 KB/s, solved with 12 parallel downloads in about 5 minutes and .part files; relationships added by script stayed empty until recalculation on a free licence, solved by re-saving one calculated table; no Windows machine, so built in Power BI Service in the browser.
- Demonstration: web preview at preview/ (PJ demo field), label "Open the dashboard preview". The .pbix is in the repo. Public Power BI sharing needs a paid licence (PJ note).
- Screenshots or interactive visuals: cover.jpg is the real report page (PJ note and cover). Caption: KPI cards, on-time rate by month and departure hour, airlines ranked, delay causes, airport table (FEATURED caption). Interaction recording: NOT AVAILABLE in the sources read.
- Verified results: scheduled flights 635,459; on-time arrivals 75.5%; cancellation rate 1.8%; average arrival delay 10.5 min (75 min when late); 92% of 6 a.m. departures on time versus 63% at 8 p.m.; late-arriving aircraft 42.5% of delay minutes; weather 5.9% of delay minutes and 59% of cancellations; Tampa 78.3% (+2.9), Fort Lauderdale 70.8% (minus 4.7); Envoy, United, Delta 80 to 82%, JetBlue and Spirit 68 to 70%; all 184 verify.dax values match pandas. The 75.5% figure is on-time ARRIVALS within 15 minutes (project CLAUDE.md rule).
- Limitations: one year only, so no year-over-year; departures only; the public demo is a web preview rather than the live Power BI report; cause minutes reconcile for 99.99% of late flights, so a small remainder does not add up.
- Next opportunities: a second page per airport (routes, carriers, worst days); a second year for SAMEPERIODLASTYEAR; arrivals into Florida and route-level analysis using the inactive relationship.
- Links: repo https://github.com/mrrishit909/florida-flight-delays; demo preview/; BUILD_IN_POWERBI.md in the repo. Live demo HTTP status for this slug: see INVENTORY demo_status (not individually checked here): NOT AVAILABLE in this file.

## 7. Contact

Approach: one short line on the home and the about page, e-mail first because it is the channel the resume leads with, LinkedIn second, GitHub as the proof link. No form, no scheduler, no phone, no new channel: the brief says do not add new details and the sources carry none.

Already public on the current site (INDEX, grep of href and mailto):
- mailto:rishit.mathur@yahoo.com (also the RESUME header address)
- https://www.linkedin.com/in/rishitrajmathur (also in RESUME header)
- https://github.com/mrrishit909 plus the four flagship repo links (florida-flight-delays, retail-dbt, sec-10k-rag, us-retail-forecast)
Location "Tampa, FL" appears in RESUME; whether INDEX prints it was not checked in the time available: NOT AVAILABLE.

## 8. Humanizer pass

Tells removed from my own drafts while writing, with what replaced them:
- "Not just dashboards, but systems" style contrasts in two headline drafts: cut; replaced by a plain list of what was built (headline 5).
- A staged opener "In a world where data is everywhere": cut from the about draft; it now opens on name, title and city.
- Forced triads ("fast, tested, honest"): cut; each claim now carries its own number.
- Inflated verbs "transforming", "unlocking", "elevating": none kept; the resume's own "transforming high-volume datasets" was not reused in the about draft.
- Vague scale words "massive", "huge", "millions of rows": replaced with 635,459, 1,067,371, 730 passages, 184 values.
- One line closers ("And that is the point."): removed from sections 1 and 2.
- Bold label bullets ("**Impact:**") in the capabilities list: replaced with plain category names.
- Dashes as connective tissue: zero em or en dashes in the file; commas, colons and full stops instead.
- Sales language "world-class", "best-in-class": never written.
- "Honest" as a self-description appears once in a quoted project field (us-retail-forecast tagline) and is otherwise avoided; the copy shows the limit rather than claiming honesty.

## Status

COMPLETE. Every section filled from the cited sources; missing facts are marked NOT AVAILABLE. Skills skipped for time (see header). Written 21:54 to 21:57 EST, 2026-11-03.
