# Verified project inventory, GitHub account mrrishit909

Generated 2026-11-03 ~21:48 EST by the Repository Investigator. Source: `gh api --paginate "user/repos?per_page=100&affiliation=owner"` (VERIFIED, authenticated as mrrishit909). Demo checks: `curl -s -L -o /dev/null --max-time 12 -w %{http_code}` (VERIFIED, 2026-11-03). Private repos: metadata only (name, visibility, pushed_at); no code or README read.

## Summary

| Metric | Count |
|---|---|
| Total repos owned | 245 |
| Public | 219 |
| Private | 26 |
| Kind: original | 236 |
| Kind: supporting/infra (name heuristic, INFERRED) | 9 |
| Kind: fork | 0 |
| Kind: archived | 0 |
| Demo URLs checked | 40 |
| Demo VERIFIED-200 | 30 |
| Demo failed | 10 |
| Standalone-site candidates (public + original + live 200, INFERRED) | 23 |
| Repos with a case-study folder in projects-site | 213 |

Notes: GitHub reports 0 forks and 0 archived repos (VERIFIED). Only 38 public repos have GitHub Pages enabled or a homepage set; most projects are presented through mrrishit909.github.io/projects/<slug>/ case pages instead of standalone Pages (INFERRED from has_pages=false).

## Discovery targets

"What it does" comes from each public repo's GitHub description field (VERIFIED metadata; READMEs not read in this pass for time). Demo status is a curl HTTP code following redirects (VERIFIED 2026-11-03). Private repos: metadata only, portfolio_eligible=false pending owner approval.

| Target | Repo(s) | Status | Demo URL | Demo | What it does (public only) |
|---|---|---|---|---|---|
| Signalroom | signalroom | found, public | https://mrrishit909.github.io/signalroom/ | VERIFIED-200 | Retail BI: 24 months of net revenue as a ribbon that coils into a 12-spoke year-over-year dial. |
| Decision Universe | decision-universe | found, public | https://mrrishit909.github.io/decision-universe/ | VERIFIED-200 | Seeded Monte Carlo, Bayes, forecasts, LP and causal inference, checked against a Python reference in the browser. |
| Predictive ML Lab | predictive-ml-lab | found, public | https://mrrishit909.github.io/predictive-ml-lab/ | VERIFIED-200 | Telecom churn lab: scikit-learn model, FastAPI, React, SHAP explainability. |
| QueryMind Text-to-SQL | querymind-text-to-sql | found, public | https://mrrishit909.github.io/querymind-text-to-sql/ | VERIFIED-200 | Natural-language-to-SQL where Claude proposes SQL and a sqlglot AST validator plus read-only DB enforce it. |
| CASCADIA | cascadia (not `cascade`, a separate semiconductor project whose Pages URL is 404) | found, public | https://mrrishit909.github.io/cascadia/ | VERIFIED-200 | DC-OPF visualization of the IEEE case30 grid with a browser LP solve, checked against a Python oracle. |
| The Counterfactual City | counterfactual-city | found, public | https://mrrishit909.github.io/counterfactual-city/ | VERIFIED-200 | Interactive city story on counterfactual outcomes (causal inference, synthetic control). |
| OMNIVERSE | omniverse, omniverse-clean | multiple repos, both private | https://omniverse-console.vercel.app (homepage field of omniverse-clean) | VERIFIED-200 (public URL; repo private) | private, not described |
| DriftSentinel | driftsentinel | found, private | none recorded | none | private, not described. Note: public `sentinel-anomaly-lab` (Pages 200) is a different project (INFERRED from name/description). |
| CRM Lab | crm-lab (private apps), crm-showcases (public) | multiple repos, one product | https://mrrishit909.github.io/crm-showcases/ | VERIFIED-200 | crm-showcases: eleven static showcase sites for eleven original CRM apps; the apps themselves are private and not hosted. |
| ScopeLens | scopelens | found, private | https://scopelens-sample.onrender.com (from owner memory notes, not repo metadata) | VERIFIED-200 on retry (first try 000 at 12s timeout, Render cold start INFERRED; retry 21:50 EST, 60s timeout -> 200) | private, not described |
| Trading Agent / paper trading | trading-bot, trading-bot-live | multiple repos, one product | https://mrrishit909.github.io/trading-bot/ and /trading-bot-live/ | both VERIFIED-200 | Alpaca paper-trading bot: moving-average strategy, risk engine, SQLite decision log, Claude advisor, no real money; -live is a read-only dashboard snapshot. Other trading code (~/trading_bot, ~/trading-robot) is not a separate repo under this account (VERIFIED: no other name match). |
| Quant Foundry | quant-foundry | found, public | https://mrrishit909.github.io/quant-foundry/ | VERIFIED-200 | Walk-forward backtest research lab on synthetic data with sealed holdouts; no live trading. |
| Data Refinery | data-refinery | found, public | https://mrrishit909.github.io/data-refinery/ | VERIFIED-200 | Data pipeline workbench: contracts, drift repair, quarantine, reconciliation, lineage on synthetic batches. |
| Policy Forge | policy-forge | found, public | https://mrrishit909.github.io/policy-forge/ | VERIFIED-200 | Offline cloud-security config review with OPA/Rego findings cited to source lines; synthetic data. |
| Incident Loom | incident-loom | found, public | https://mrrishit909.github.io/incident-loom/ | VERIFIED-200 | Replayable security-log investigation with evidence-linked incident timelines; synthetic data. |
| Minimal Motion Studio | minimal-motion-studio | found, public | https://mrrishit909.github.io/minimal-motion-studio/ | VERIFIED-200 | Brand brief to website: tokens, type/spacing scales, Web Animations motion, dependency-free export. |

Target tally: 16 of 16 found (11 public single-repo, 2 private single-repo [DriftSentinel, ScopeLens], 3 multi-repo groups [OMNIVERSE (both private), CRM Lab, Trading]). 15 of 16 targets have at least one demo URL returning 200 (16 URLs: 14 public Pages + omniverse-console.vercel.app + scopelens-sample.onrender.com). DriftSentinel has no recorded demo.
Quant Foundry, Data Refinery, Policy Forge, Incident Loom and Minimal Motion Studio form one program, "five GitHub-native projects" (INFERRED from owner memory notes); they are separate repos and separate products.


## Full list

| Repo | Vis | Kind | Lang | Pushed | Demo | Group | Candidate | Case study |
|---|---|---|---|---|---|---|---|---|
| [abyssal-deep-ocean](https://github.com/mrrishit909/abyssal-deep-ocean) | public | original | TypeScript | 2026-10-07 | none |  |  | yes |
| [adaptive-tutor-engine](https://github.com/mrrishit909/adaptive-tutor-engine) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [aether-airport-recovery](https://github.com/mrrishit909/aether-airport-recovery) | public | original | TypeScript | 2026-10-07 | none |  |  | yes |
| [air-quality-aqi](https://github.com/mrrishit909/air-quality-aqi) | public | original | Python | 2026-10-03 | none |  |  | yes |
| [airbnb-price-drivers](https://github.com/mrrishit909/airbnb-price-drivers) | public | original | Python | 2026-10-03 | none |  |  | yes |
| [aircraft-health-ops](https://github.com/mrrishit909/aircraft-health-ops) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [airport-ops-intelligence](https://github.com/mrrishit909/airport-ops-intelligence) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [alchemia-material-library](https://github.com/mrrishit909/alchemia-material-library) | public | original | TypeScript | 2026-10-07 | none |  |  | yes |
| [ames-housing](https://github.com/mrrishit909/ames-housing) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [arbor-urban-canopy](https://github.com/mrrishit909/arbor-urban-canopy) | public | original | TypeScript | 2026-10-08 | none |  |  | yes |
| [archaeology-discovery](https://github.com/mrrishit909/archaeology-discovery) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [atlas-development-intel](https://github.com/mrrishit909/atlas-development-intel) | public | original | TypeScript | 2026-10-07 | none |  |  | yes |
| [atlas-human-mobility](https://github.com/mrrishit909/atlas-human-mobility) | public | original | HTML | 2026-10-15 | VERIFIED-200 |  | yes | yes |
| [attack-path-platform](https://github.com/mrrishit909/attack-path-platform) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [aurelia](https://github.com/mrrishit909/aurelia) | public | original | TypeScript | 2026-10-08 | FAILED-404 |  |  | yes |
| [bengaluru-restaurants](https://github.com/mrrishit909/bengaluru-restaurants) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [bitcoin-market-share](https://github.com/mrrishit909/bitcoin-market-share) | public | original | Python | 2026-10-03 | none |  |  | yes |
| [building-energy-optimizer](https://github.com/mrrishit909/building-energy-optimizer) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [business-finder](https://github.com/mrrishit909/business-finder) | public | original | Python | 2026-09-30 | none |  |  | yes |
| [ca-fast-food-wage](https://github.com/mrrishit909/ca-fast-food-wage) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [car-insurance-claims](https://github.com/mrrishit909/car-insurance-claims) | public | original | Python | 2026-10-03 | none |  |  | yes |
| [car-prices](https://github.com/mrrishit909/car-prices) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [cascade](https://github.com/mrrishit909/cascade) | public | original | TypeScript | 2026-10-08 | FAILED-404 |  |  | yes |
| [cascadia](https://github.com/mrrishit909/cascadia) | public | original | HTML | 2026-10-11 | VERIFIED-200 | CASCADIA | yes | yes |
| [cat-risk-modeler](https://github.com/mrrishit909/cat-risk-modeler) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [chicago-bike-share](https://github.com/mrrishit909/chicago-bike-share) | public | original | HTML | 2026-10-01 | none |  |  | yes |
| [chicago-crime-r](https://github.com/mrrishit909/chicago-crime-r) | public | original | R | 2026-10-02 | none |  |  | yes |
| [chronos-time-machine](https://github.com/mrrishit909/chronos-time-machine) | public | original | TypeScript | 2026-10-07 | none |  |  | yes |
| [citadel](https://github.com/mrrishit909/citadel) | public | original | TypeScript | 2026-10-08 | FAILED-404 |  |  | yes |
| [citibike-demand](https://github.com/mrrishit909/citibike-demand) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [city-capital-planner](https://github.com/mrrishit909/city-capital-planner) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [claims-intelligence](https://github.com/mrrishit909/claims-intelligence) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [climate-signal-observatory](https://github.com/mrrishit909/climate-signal-observatory) | public | original | HTML | 2026-10-15 | VERIFIED-200 |  | yes | yes |
| [climate-warming-signal](https://github.com/mrrishit909/climate-warming-signal) | public | original | Python | 2026-10-03 | none |  |  | yes |
| [clinical-trial-sas](https://github.com/mrrishit909/clinical-trial-sas) | public | original | Python | 2026-10-02 | none |  |  | yes |
| [cloud-finops-optimizer](https://github.com/mrrishit909/cloud-finops-optimizer) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [college-scorecard-warehouse](https://github.com/mrrishit909/college-scorecard-warehouse) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [commodity-intelligence](https://github.com/mrrishit909/commodity-intelligence) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [complaint-sorter](https://github.com/mrrishit909/complaint-sorter) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [construction-risk](https://github.com/mrrishit909/construction-risk) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [contract-rfp-automator](https://github.com/mrrishit909/contract-rfp-automator) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [counterfactual-city](https://github.com/mrrishit909/counterfactual-city) | public | original | HTML | 2026-10-11 | VERIFIED-200 | COUNTERFACTUAL CITY | yes | yes |
| [county-health-r](https://github.com/mrrishit909/county-health-r) | public | original | R | 2026-10-02 | none |  |  | yes |
| [court-analytics](https://github.com/mrrishit909/court-analytics) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [covid-excess-deaths](https://github.com/mrrishit909/covid-excess-deaths) | public | original | Python | 2026-10-03 | none |  |  | yes |
| [covid-first-100-days](https://github.com/mrrishit909/covid-first-100-days) | public | original | R | 2026-10-03 | none |  |  | yes |
| [credit-approvals](https://github.com/mrrishit909/credit-approvals) | public | original | Python | 2026-10-03 | none |  |  | yes |
| [crm-showcases](https://github.com/mrrishit909/crm-showcases) | public | original | TypeScript | 2026-10-17 | VERIFIED-200 | CRM LAB | yes |  |
| [crypto-forecasting](https://github.com/mrrishit909/crypto-forecasting) | public | original | Python | 2026-10-03 | none |  |  | yes |
| [csv-quality-checker](https://github.com/mrrishit909/csv-quality-checker) | public | original | Java | 2026-10-01 | none |  |  | yes |
| [customer-clv](https://github.com/mrrishit909/customer-clv) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [data-refinery](https://github.com/mrrishit909/data-refinery) | public | original | Python | 2026-10-22 | VERIFIED-200 | FIVE GITHUB-NATIVE (Data Refinery) | yes | yes |
| [data-reliability-control-plane](https://github.com/mrrishit909/data-reliability-control-plane) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [datacenter-cooling-optimizer](https://github.com/mrrishit909/datacenter-cooling-optimizer) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [decision-universe](https://github.com/mrrishit909/decision-universe) | public | original | TypeScript | 2026-10-15 | VERIFIED-200 | DECISION UNIVERSE | yes | yes |
| [delay-graph](https://github.com/mrrishit909/delay-graph) | public | original | Python | 2026-10-02 | none |  |  | yes |
| [dev-survey-data-roles](https://github.com/mrrishit909/dev-survey-data-roles) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [digital-divide](https://github.com/mrrishit909/digital-divide) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [disaster-response-coordinator](https://github.com/mrrishit909/disaster-response-coordinator) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [drug-discovery-workspace](https://github.com/mrrishit909/drug-discovery-workspace) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [drug-events-mongo-postgres](https://github.com/mrrishit909/drug-events-mongo-postgres) | public | original | Python | 2026-10-02 | none |  |  | yes |
| [dst-crashes-stats](https://github.com/mrrishit909/dst-crashes-stats) | public | original | Python | 2026-10-02 | none |  |  | yes |
| [echo-music-graph](https://github.com/mrrishit909/echo-music-graph) | public | original | TypeScript | 2026-10-07 | none |  |  | yes |
| [economic-atlas](https://github.com/mrrishit909/economic-atlas) | public | original | HTML | 2026-10-15 | VERIFIED-200 |  | yes | yes |
| [ed-patient-flow](https://github.com/mrrishit909/ed-patient-flow) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [eidolon](https://github.com/mrrishit909/eidolon) | public | original | TypeScript | 2026-10-08 | FAILED-404 |  |  | yes |
| [election-ops-planner](https://github.com/mrrishit909/election-ops-planner) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [email-ab-test](https://github.com/mrrishit909/email-ab-test) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [ember](https://github.com/mrrishit909/ember) | public | original | TypeScript | 2026-10-08 | FAILED-404 |  |  | yes |
| [enterprise-knowledge-graph](https://github.com/mrrishit909/enterprise-knowledge-graph) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [enterprise-simulation-lab](https://github.com/mrrishit909/enterprise-simulation-lab) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [er-wait-requirements](https://github.com/mrrishit909/er-wait-requirements) | public | original | Python | 2026-10-02 | none |  |  | yes |
| [excel-model](https://github.com/mrrishit909/excel-model) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [faa-aircraft-db](https://github.com/mrrishit909/faa-aircraft-db) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [fab-yield-intelligence](https://github.com/mrrishit909/fab-yield-intelligence) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [farm-crop-intelligence](https://github.com/mrrishit909/farm-crop-intelligence) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [fast-food-stocks](https://github.com/mrrishit909/fast-food-stocks) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [fda-recalls-cleaning](https://github.com/mrrishit909/fda-recalls-cleaning) | public | original | Python | 2026-10-02 | none |  |  | yes |
| [federal-contracts-cleaning](https://github.com/mrrishit909/federal-contracts-cleaning) | public | original | Python | 2026-10-02 | none |  |  | yes |
| [film-production-planner](https://github.com/mrrishit909/film-production-planner) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [film-reception-wikipedia](https://github.com/mrrishit909/film-reception-wikipedia) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [fisheries-watch](https://github.com/mrrishit909/fisheries-watch) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [flight-delay-model](https://github.com/mrrishit909/flight-delay-model) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [florida-flight-delays](https://github.com/mrrishit909/florida-flight-delays) | public | original | Python | 2026-09-30 | none |  |  | yes |
| [food-inspections](https://github.com/mrrishit909/food-inspections) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [food-price-forecast](https://github.com/mrrishit909/food-price-forecast) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [food-waste-exchange](https://github.com/mrrishit909/food-waste-exchange) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [forge-twin-builder](https://github.com/mrrishit909/forge-twin-builder) | public | original | TypeScript | 2026-10-07 | none |  |  | yes |
| [fraud-model-monitoring](https://github.com/mrrishit909/fraud-model-monitoring) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [fuel-economy](https://github.com/mrrishit909/fuel-economy) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [furniture-office-sales](https://github.com/mrrishit909/furniture-office-sales) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [genesis-evolution-explorer](https://github.com/mrrishit909/genesis-evolution-explorer) | public | original | TypeScript | 2026-10-07 | none |  |  | yes |
| [gold-price-drivers](https://github.com/mrrishit909/gold-price-drivers) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [grocery-perishables-optimizer](https://github.com/mrrishit909/grocery-perishables-optimizer) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [healthscape](https://github.com/mrrishit909/healthscape) | public | original | Python | 2026-10-15 | VERIFIED-200 |  | yes | yes |
| [helix-research-workspace](https://github.com/mrrishit909/helix-research-workspace) | public | original | TypeScript | 2026-10-07 | none |  |  | yes |
| [hn-front-page](https://github.com/mrrishit909/hn-front-page) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [hospital-warehouse](https://github.com/mrrishit909/hospital-warehouse) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [hr-analytics](https://github.com/mrrishit909/hr-analytics) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [incident-loom](https://github.com/mrrishit909/incident-loom) | public | original | Python | 2026-10-22 | VERIFIED-200 | FIVE GITHUB-NATIVE (Incident Loom) | yes | yes |
| [india-elections](https://github.com/mrrishit909/india-elections) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [international-debt](https://github.com/mrrishit909/international-debt) | public | original | Python | 2026-10-03 | none |  |  | yes |
| [iowa-liquor-forecast](https://github.com/mrrishit909/iowa-liquor-forecast) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [iowa-product-lifecycle](https://github.com/mrrishit909/iowa-product-lifecycle) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [ipl-cricket](https://github.com/mrrishit909/ipl-cricket) | public | original | Python | 2026-10-03 | none |  |  | yes |
| [iris-fisher](https://github.com/mrrishit909/iris-fisher) | public | original | Python | 2026-10-03 | none |  |  | yes |
| [ISM_6390_WEEK_5_MATURITY_ASSESSMENT-](https://github.com/mrrishit909/ISM_6390_WEEK_5_MATURITY_ASSESSMENT-) | public | supporting | HTML | 2026-09-28 | VERIFIED-200 |  |  |  |
| [jira-feature-votes](https://github.com/mrrishit909/jira-feature-votes) | public | original | Python | 2026-10-02 | none |  |  | yes |
| [jira-flow-analytics](https://github.com/mrrishit909/jira-flow-analytics) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [kidney-stones-simpson](https://github.com/mrrishit909/kidney-stones-simpson) | public | original | Python | 2026-10-03 | none |  |  | yes |
| [kintsugi-lifecycle-passport](https://github.com/mrrishit909/kintsugi-lifecycle-passport) | public | original | TypeScript | 2026-10-07 | none |  |  | yes |
| [la-crime](https://github.com/mrrishit909/la-crime) | public | original | Python | 2026-10-03 | none |  |  | yes |
| [life-search-engine](https://github.com/mrrishit909/life-search-engine) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [literature-discovery-engine](https://github.com/mrrishit909/literature-discovery-engine) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [lucent](https://github.com/mrrishit909/lucent) | public | original | TypeScript | 2026-10-08 | FAILED-404 |  |  | yes |
| [m5-demand-spark](https://github.com/mrrishit909/m5-demand-spark) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [m5-sales-sql](https://github.com/mrrishit909/m5-sales-sql) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [ma-integration-intelligence](https://github.com/mrrishit909/ma-integration-intelligence) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [mine-ore-optimizer](https://github.com/mrrishit909/mine-ore-optimizer) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [minimal-motion-studio](https://github.com/mrrishit909/minimal-motion-studio) | public | original | TypeScript | 2026-10-22 | VERIFIED-200 | FIVE GITHUB-NATIVE (Minimal Motion Studio) | yes | yes |
| [mnist-digits](https://github.com/mrrishit909/mnist-digits) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [moby-dick-words](https://github.com/mrrishit909/moby-dick-words) | public | original | Python | 2026-10-03 | none |  |  | yes |
| [mortgage-denials](https://github.com/mrrishit909/mortgage-denials) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [movie-recommender](https://github.com/mrrishit909/movie-recommender) | public | original | Python | 2026-10-03 | none |  |  | yes |
| [mrrishit909.github.io](https://github.com/mrrishit909/mrrishit909.github.io) | public | supporting | HTML | 2026-10-03 | VERIFIED-200 |  |  |  |
| [music-rights-ledger](https://github.com/mrrishit909/music-rights-ledger) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [mycelia-soil-intelligence](https://github.com/mrrishit909/mycelia-soil-intelligence) | public | original | TypeScript | 2026-10-07 | none |  |  | yes |
| [nebula-exoplanet-lab](https://github.com/mrrishit909/nebula-exoplanet-lab) | public | original | TypeScript | 2026-10-07 | none |  |  | yes |
| [netflix-office](https://github.com/mrrishit909/netflix-office) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [nexus-infrastructure-map](https://github.com/mrrishit909/nexus-infrastructure-map) | public | original | TypeScript | 2026-10-07 | none |  |  | yes |
| [nhanes-sas](https://github.com/mrrishit909/nhanes-sas) | public | original | Python | 2026-10-02 | none |  |  | yes |
| [nobel-prizes](https://github.com/mrrishit909/nobel-prizes) | public | original | Python | 2026-10-03 | none |  |  | yes |
| [nyc-airbnb-cleaning](https://github.com/mrrishit909/nyc-airbnb-cleaning) | public | original | Python | 2026-10-03 | none |  |  | yes |
| [nyc-building-energy](https://github.com/mrrishit909/nyc-building-energy) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [nyc-sat-scores](https://github.com/mrrishit909/nyc-sat-scores) | public | original | Python | 2026-10-03 | none |  |  | yes |
| [nyc-taxi-anomalies](https://github.com/mrrishit909/nyc-taxi-anomalies) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [online-shoppers-purchase](https://github.com/mrrishit909/online-shoppers-purchase) | public | original | Python | 2026-10-03 | none |  |  | yes |
| [open-prices](https://github.com/mrrishit909/open-prices) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [orbital-space-traffic](https://github.com/mrrishit909/orbital-space-traffic) | public | original | TypeScript | 2026-10-07 | VERIFIED-200 |  | yes | yes |
| [parking-tickets-db](https://github.com/mrrishit909/parking-tickets-db) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [patent-landscape-engine](https://github.com/mrrishit909/patent-landscape-engine) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [phantom](https://github.com/mrrishit909/phantom) | public | original | TypeScript | 2026-10-08 | FAILED-404 |  |  | yes |
| [polaris-ice-expedition](https://github.com/mrrishit909/polaris-ice-expedition) | public | original | TypeScript | 2026-10-07 | none |  |  | yes |
| [policy-forge](https://github.com/mrrishit909/policy-forge) | public | original | Python | 2026-11-02 | VERIFIED-200 | FIVE GITHUB-NATIVE (Policy Forge) | yes | yes |
| [poll-accuracy](https://github.com/mrrishit909/poll-accuracy) | public | original | Python | 2026-10-02 | none |  |  | yes |
| [port-control-tower](https://github.com/mrrishit909/port-control-tower) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [predictive-maintenance-rul](https://github.com/mrrishit909/predictive-maintenance-rul) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [predictive-ml-lab](https://github.com/mrrishit909/predictive-ml-lab) | public | original | TypeScript | 2026-10-08 | VERIFIED-200 | PREDICTIVE ML LAB | yes | yes |
| [prior-auth-platform](https://github.com/mrrishit909/prior-auth-platform) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [process-mining](https://github.com/mrrishit909/process-mining) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [product-recall-traceability](https://github.com/mrrishit909/product-recall-traceability) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [projects](https://github.com/mrrishit909/projects) | public | supporting | HTML | 2026-11-03 | VERIFIED-200 |  |  |  |
| [projects-site](https://github.com/mrrishit909/projects-site) | public | supporting | HTML | 2026-11-03 | VERIFIED-200 |  |  |  |
| [pulse-economic-activity](https://github.com/mrrishit909/pulse-economic-activity) | public | original | TypeScript | 2026-10-07 | none |  |  | yes |
| [pulse-energy-grid](https://github.com/mrrishit909/pulse-energy-grid) | public | original | TypeScript | 2026-10-15 | VERIFIED-200 |  | yes | yes |
| [quant-foundry](https://github.com/mrrishit909/quant-foundry) | public | original | Python | 2026-11-02 | VERIFIED-200 | FIVE GITHUB-NATIVE (Quant Foundry) | yes | yes |
| [quantum-circuit-lab](https://github.com/mrrishit909/quantum-circuit-lab) | public | original | TypeScript | 2026-10-07 | none |  |  | yes |
| [querymind-text-to-sql](https://github.com/mrrishit909/querymind-text-to-sql) | public | original | JavaScript | 2026-10-08 | VERIFIED-200 | QUERYMIND | yes | yes |
| [recon-engine](https://github.com/mrrishit909/recon-engine) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [renewable-grid-twin](https://github.com/mrrishit909/renewable-grid-twin) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [requiem-heritage-archive](https://github.com/mrrishit909/requiem-heritage-archive) | public | original | TypeScript | 2026-10-07 | none |  |  | yes |
| [restaurant-ops-intelligence](https://github.com/mrrishit909/restaurant-ops-intelligence) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [retail-dbt](https://github.com/mrrishit909/retail-dbt) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [retail-intelligence-studio](https://github.com/mrrishit909/retail-intelligence-studio) | public | original | TypeScript | 2026-10-15 | VERIFIED-200 |  | yes | yes |
| [review-sentiment](https://github.com/mrrishit909/review-sentiment) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [rift](https://github.com/mrrishit909/rift) | public | original | TypeScript | 2026-10-08 | FAILED-404 |  |  | yes |
| [route-optimizer](https://github.com/mrrishit909/route-optimizer) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [satellite-fleet-ops](https://github.com/mrrishit909/satellite-fleet-ops) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [scope3-carbon-accounting](https://github.com/mrrishit909/scope3-carbon-accounting) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [sec-10k-rag](https://github.com/mrrishit909/sec-10k-rag) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [sentinel-anomaly-lab](https://github.com/mrrishit909/sentinel-anomaly-lab) | public | original | HTML | 2026-10-15 | VERIFIED-200 |  | yes | yes |
| [sentinel-incident-command](https://github.com/mrrishit909/sentinel-incident-command) | public | original | TypeScript | 2026-10-07 | none |  |  | yes |
| [session-recommender](https://github.com/mrrishit909/session-recommender) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [sf311-requirements](https://github.com/mrrishit909/sf311-requirements) | public | original | Python | 2026-10-02 | none |  |  | yes |
| [signalroom](https://github.com/mrrishit909/signalroom) | public | original | TypeScript | 2026-10-08 | VERIFIED-200 | SIGNALROOM | yes | yes |
| [soccer-goals-test](https://github.com/mrrishit909/soccer-goals-test) | public | original | Python | 2026-10-03 | none |  |  | yes |
| [sonora-venue-acoustics](https://github.com/mrrishit909/sonora-venue-acoustics) | public | original | TypeScript | 2026-10-07 | none |  |  | yes |
| [spend-intelligence](https://github.com/mrrishit909/spend-intelligence) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [sports-opponent-intelligence](https://github.com/mrrishit909/sports-opponent-intelligence) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [spotify-tracks](https://github.com/mrrishit909/spotify-tracks) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [stock-time-series](https://github.com/mrrishit909/stock-time-series) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [super-bowl-ads](https://github.com/mrrishit909/super-bowl-ads) | public | original | R | 2026-10-04 | none |  |  | yes |
| [supply-chain-orchestra](https://github.com/mrrishit909/supply-chain-orchestra) | public | original | TypeScript | 2026-10-15 | VERIFIED-200 |  | yes | yes |
| [supply-chain-twin](https://github.com/mrrishit909/supply-chain-twin) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [synapse-agent-builder](https://github.com/mrrishit909/synapse-agent-builder) | public | original | TypeScript | 2026-10-06 | none |  |  | yes |
| [synapse-tribunal](https://github.com/mrrishit909/synapse-tribunal) | public | original | TypeScript | 2026-10-11 | VERIFIED-200 |  | yes | yes |
| [synthetic-data-generator](https://github.com/mrrishit909/synthetic-data-generator) | public | original | HTML | 2026-10-04 | none |  |  | yes |
| [taxi-spark](https://github.com/mrrishit909/taxi-spark) | public | original | Python | 2026-10-02 | none |  |  | yes |
| [telecom-self-healing](https://github.com/mrrishit909/telecom-self-healing) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [terra-climate-twin](https://github.com/mrrishit909/terra-climate-twin) | public | original | TypeScript | 2026-10-06 | none |  |  | yes |
| [tessera](https://github.com/mrrishit909/tessera) | public | original | TypeScript | 2026-10-08 | FAILED-404 |  |  | yes |
| [texas-bar-sales](https://github.com/mrrishit909/texas-bar-sales) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [tfl-journeys](https://github.com/mrrishit909/tfl-journeys) | public | original | Python | 2026-10-03 | none |  |  | yes |
| [titanic-survival](https://github.com/mrrishit909/titanic-survival) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [trading-bot](https://github.com/mrrishit909/trading-bot) | public | original | Python | 2026-10-08 | VERIFIED-200 | TRADING | yes | yes |
| [trading-bot-live](https://github.com/mrrishit909/trading-bot-live) | public | supporting | HTML | 2026-10-20 | VERIFIED-200 | TRADING |  |  |
| [traffic-mortality-states](https://github.com/mrrishit909/traffic-mortality-states) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [traffic-signal-twin](https://github.com/mrrishit909/traffic-signal-twin) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [trial-site-optimizer](https://github.com/mrrishit909/trial-site-optimizer) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [twitter-network](https://github.com/mrrishit909/twitter-network) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [uber-nyc-pickups](https://github.com/mrrishit909/uber-nyc-pickups) | public | original | Python | 2026-10-03 | none |  |  | yes |
| [unicorn-companies](https://github.com/mrrishit909/unicorn-companies) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [us-jobs-dashboard](https://github.com/mrrishit909/us-jobs-dashboard) | public | original | HTML | 2026-10-01 | none |  |  | yes |
| [us-retail-forecast](https://github.com/mrrishit909/us-retail-forecast) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [vantage](https://github.com/mrrishit909/vantage) | public | original | TypeScript | 2026-10-08 | FAILED-404 |  |  | yes |
| [virtual-power-plant](https://github.com/mrrishit909/virtual-power-plant) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [vision-quality-inspection](https://github.com/mrrishit909/vision-quality-inspection) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [vitra-watch-atelier](https://github.com/mrrishit909/vitra-watch-atelier) | public | original | TypeScript | 2026-10-07 | none |  |  | yes |
| [voyage-fuel-optimizer](https://github.com/mrrishit909/voyage-fuel-optimizer) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [warehouse-robot-orchestration](https://github.com/mrrishit909/warehouse-robot-orchestration) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [waste-recycling-ops](https://github.com/mrrishit909/waste-recycling-ops) | public | original | Python | 2026-10-06 | none |  |  | yes |
| [water-leak-intelligence](https://github.com/mrrishit909/water-leak-intelligence) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [weather-forecast-skill](https://github.com/mrrishit909/weather-forecast-skill) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [wiki-stream-spark](https://github.com/mrrishit909/wiki-stream-spark) | public | original | Python | 2026-10-02 | none |  |  | yes |
| [wikipedia-attention](https://github.com/mrrishit909/wikipedia-attention) | public | original | Python | 2026-10-04 | none |  |  | yes |
| [wildlife-conservation-network](https://github.com/mrrishit909/wildlife-conservation-network) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [workforce-scheduler](https://github.com/mrrishit909/workforce-scheduler) | public | original | Python | 2026-10-05 | none |  |  | yes |
| [world-happiness](https://github.com/mrrishit909/world-happiness) | public | original | Python | 2026-10-01 | none |  |  | yes |
| [world-population](https://github.com/mrrishit909/world-population) | public | original | Python | 2026-10-03 | none |  |  | yes |

## Classification notes and limits

- Kind "supporting" (INFERRED, explicit name list): mrrishit909.github.io and projects (portfolio hosts), projects-site and portfolio-concepts (portfolio source), creative-engineering and business-operations-lab-20 (program/infra repos), trading-bot-live (dashboard snapshot of trading-bot), ISM_6390_* (USF class team work; owner notes say the team uses a teammate's HTML, so not counted as a solo standalone candidate). Everything else is "original" by default: GitHub reports 0 forks and 0 archived.
- Standalone-site candidate = public + original + a demo URL that returned 200 (INFERRED rule, not a quality judgment). The 10 Pages URLs returning 404 (cascade, eidolon, ember, aurelia, lucent, tessera, vantage, phantom, rift, citadel) have Pages enabled but nothing served at the root; they need a fix before they can be candidates.
- 181 public repos have no Pages and no homepage, and 24 private repos have no public URL on record; none of these were curled. Their demos, if any, live on case pages under mrrishit909.github.io/projects/ and were NOT checked in this pass.
- Not done for time (hard stop 21:56 EST): no README reads (descriptions come from GitHub metadata), no product grouping beyond the discovery targets, no check of /projects/<slug>/ case-page links.
- Private repo metadata recorded beyond name/visibility/pushed_at: the GitHub homepage field of omniverse-clean (a public URL, needed for the OMNIVERSE demo check). JSON adds three fields beyond the spec: standalone_reason, has_case_study, featured.

## Private repositories

26 private repository rows were removed from this list on 2026-11-03 (security review finding). Only the discovery targets the owner named in the directive (OMNIVERSE, DriftSentinel, ScopeLens, CRM Lab apps) are mentioned above, without descriptions. The full private list is not stored in this repository.
