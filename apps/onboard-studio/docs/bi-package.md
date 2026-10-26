# BI package: Power BI semantic model design (P02-ART-06)

**No `.pbix` was produced, opened or tested.** This file is a design: a star schema, relationships, DAX measures and Power Query steps written from the contract (`contracts.md` D-01..D-06) and the
shape of two CSV exports whose SQL was run here (`data/sql/analysis/bi_fact_case.sql`: 733 rows; `bi_fact_step_instance.sql`: 3,665 rows, both executed with `psql -v ON_ERROR_STOP=1`, exit 0). None of the DAX or M below has
been executed; Power BI Desktop is not available in this environment. The "expected" values in section 4 were computed from those exports in Python and SQL, not by Power BI. Verification steps that need Desktop are listed in section 5 as open.
All data is **synthetic** (snapshot `os-20261026-20261026`).

## 1. Star schema

Two fact grains share the dimensions: the **case** (`fact_case`, the SLA and cycle-time grain) and the **step instance** (`fact_step_instance`, the waiting and bottleneck grain). Durations are loaded as **exact integer seconds**, never as rounded hours,
so a measure divides once at the end like the contract (D-01, D-04) and the half-up tie defect (see `technical-case-study.md`) cannot reappear in the model. Open cases and never-started steps carry NULL durations, which becomes BLANK, never 0.

| Table | Grain | Key | Columns (beyond key) | Built from |
|---|---|---|---|---|
| `fact_case` | case (733 rows: 712 completed, 21 open) | `case_id` | `organization_id`, `workflow_version_id`, `status`, `opened_at`, `completed_at`, `opened_date`, `completed_date` (added in M), `sla_minutes`, `handoffs`, `calendar_seconds`, `business_seconds`, `paused_seconds`, `paused_business_seconds`, `active_seconds`, `within_sla`, `has_submission`, `has_rejection`, `first_reviewed`, `first_accepted`, `required_types`, `required_accepted_types` | CSV of `data/sql/analysis/bi_fact_case.sql` (uses the view `os_case_facts` of `00_case_facts.sql`) |
| `fact_step_instance` | step instance (3,665 rows, 3,623 started) | `step_instance_id` | `case_id`, `step_definition_id`, `status`, `version_number`, `ready_at`, `started_at`, `decided_at`, `assignee_id`, `reviewer_id`, `wait_business_seconds`, `started_to_decision_business_seconds`, `started_to_decision_calendar_seconds`, `handoffs` | CSV of `data/sql/analysis/bi_fact_step_instance.sql` |
| `dim_organization` | organization | `organization_id` | `organization_name`, `segment`, `region` | `web/public/data/organizations.json` |
| `dim_workflow_version` | workflow version | `workflow_version_id` | `template_id`, `version_number`, `published_at`, `definition_hash`, `version_label` (`v1`, `v2`) | `workflow_versions.json` |
| `dim_step` | step definition | `step_definition_id` | `workflow_version_id` (no relationship, see below), `step_name`, `role_key`, `sequence`, `required` | `step_definitions.json` |
| `dim_assignee` | person (assignee or reviewer) | `person_id` | `person_kind` (`ops`, `compliance`, `account`, `reviewer`, from the id prefix `ops-`, `cmp-`, `acc-`, `rev-`) | distinct `assignee_id` and `reviewer_id` of `fact_step_instance` |
| `dim_date` (calendar) | day | `date` | `year`, `month`, `month_start`, `period_end_utc` (next day 00:00 as datetime), `is_working_day`, `working_hours` (8 on a working day, 0 on a weekend or holiday) | generated; working hours from `calendar_intervals.json` (`kind`) |
| `Pause Switch` (what-if) | the values 0 and 1 | `Pause Switch` | `Pause Switch Value` measure | `GENERATESERIES(0, 1, 1)` |

## 2. Relationships

| From (many) | To (one) | Cardinality / direction | Active |
|---|---|---|---|
| `fact_case[organization_id]` | `dim_organization[organization_id]` | many-to-one, single | yes |
| `fact_case[workflow_version_id]` | `dim_workflow_version[workflow_version_id]` | many-to-one, single | yes |
| `fact_case[opened_date]` | `dim_date[date]` | many-to-one, single | yes (cases are dated by opening, as the window of the contract: half-open on `opened_at`) |
| `fact_case[completed_date]` | `dim_date[date]` | many-to-one, single | no (`USERELATIONSHIP` for "completed in month") |
| `fact_step_instance[case_id]` | `fact_case[case_id]` | many-to-one, single | yes (so segment, region, version and date slicers reach step facts through the case) |
| `fact_step_instance[step_definition_id]` | `dim_step[step_definition_id]` | many-to-one, single | yes |
| `fact_step_instance[assignee_id]` | `dim_assignee[person_id]` | many-to-one, single | yes (the person holding the step when it started) |
| `fact_step_instance[reviewer_id]` | `dim_assignee[person_id]` | many-to-one, single | no (`USERELATIONSHIP`: the person who decided the step; this is the lens that shows the `rev-004` bottleneck, query 04) |

`dim_step[workflow_version_id]` deliberately has **no** relationship to `dim_workflow_version`: a second path from the version dimension to `fact_step_instance` would be ambiguous with the path through `fact_case`. Steps with the same
`step_name` in v1 and v2 have different ids and aggregate together by name. No many-to-many relationships, no bi-directional filters. `Pause Switch` is disconnected.

## 3. DAX measures

Twelve contract measures (the first block) and hidden helpers. Every ratio uses `DIVIDE(numerator, denominator, BLANK())`, so a zero denominator returns BLANK (the contract's null), never 0 and never an error; ratios are computed from aggregated numerators and denominators,
never averaged over rows (D-04). Hours are `seconds / 3600` formatted `0.0000`; rates `0.000000`. The switch reproduces the two contract states (`pause_eligible`: the SLA rule's pause policy applies, `pause_not_eligible`: it does not), as `Figures!B3` does in the workbook.

```dax
-- helpers (hidden)
Pause Switch Value        = SELECTEDVALUE ( 'Pause Switch'[Pause Switch], 1 )
Within SLA Cases =
    VAR sw = [Pause Switch Value]
    RETURN
        SUMX (
            FILTER ( fact_case, fact_case[status] = "completed" ),
            IF ( MAX ( 0, fact_case[business_seconds] - sw * fact_case[paused_business_seconds] ) <= fact_case[sla_minutes] * 60, 1, 0 )
        )
Active Seconds =
    VAR sw = [Pause Switch Value]
    RETURN
        SUMX (
            FILTER ( fact_case, fact_case[status] = "completed" ),
            MAX ( 0, fact_case[business_seconds] - sw * fact_case[paused_business_seconds] )
        )

-- the twelve contract measures
Completed Cases = CALCULATE ( COUNTROWS ( fact_case ), fact_case[status] = "completed" )
Calendar Cycle Hours =
    DIVIDE ( CALCULATE ( SUM ( fact_case[calendar_seconds] ), fact_case[status] = "completed" ), [Completed Cases] * 3600, BLANK () )
Business Cycle Hours =
    DIVIDE ( CALCULATE ( SUM ( fact_case[business_seconds] ), fact_case[status] = "completed" ), [Completed Cases] * 3600, BLANK () )
Paused Hours =
    DIVIDE ( CALCULATE ( SUM ( fact_case[paused_seconds] ), fact_case[status] = "completed" ) * [Pause Switch Value], [Completed Cases] * 3600, BLANK () )
Active Elapsed Hours = DIVIDE ( [Active Seconds], [Completed Cases] * 3600, BLANK () )
SLA Attainment = DIVIDE ( [Within SLA Cases], [Completed Cases], BLANK () )
Rework Rate =
    DIVIDE (
        CALCULATE ( COUNTROWS ( fact_case ), fact_case[has_rejection] = 1 ),
        CALCULATE ( COUNTROWS ( fact_case ), fact_case[has_submission] = 1 ),
        BLANK ()
    )
First Pass Rate = DIVIDE ( SUM ( fact_case[first_accepted] ), SUM ( fact_case[first_reviewed] ), BLANK () )
Document Completeness = DIVIDE ( SUM ( fact_case[required_accepted_types] ), SUM ( fact_case[required_types] ), BLANK () )
Handoffs per Case =
    DIVIDE ( CALCULATE ( SUM ( fact_case[handoffs] ), fact_case[status] = "completed" ), [Completed Cases], BLANK () )
Step Waiting Hours =
    DIVIDE (
        SUM ( fact_step_instance[wait_business_seconds] ),
        COUNTROWS ( FILTER ( fact_step_instance, NOT ISBLANK ( fact_step_instance[wait_business_seconds] ) ) ) * 3600,
        BLANK ()
    )
Open Backlog =
    VAR cutoff = MAX ( dim_date[period_end_utc] )
    RETURN
        COUNTROWS (
            FILTER (
                CALCULATETABLE ( fact_case, REMOVEFILTERS ( dim_date ) ),
                fact_case[opened_at] <= cutoff && ( ISBLANK ( fact_case[completed_at] ) || fact_case[completed_at] > cutoff )
            )
        )

-- optional, hidden
Reviewer Step Waiting Hours =
    CALCULATE ( [Step Waiting Hours], USERELATIONSHIP ( fact_step_instance[reviewer_id], dim_assignee[person_id] ) )
```

Notes on the choices:
* **`<> BLANK()` is avoided on purpose.** In DAX `0 = BLANK()` is true, so a filter `wait_business_seconds <> BLANK()` would drop steps that started the instant they were ready (0 seconds); `NOT ISBLANK(...)` keeps them, as the contract's "null when never started" requires.
* **`Open Backlog`** reads the cutoff from the date selection (`period_end_utc` of the last selected day), which for a month slicer is the first instant of the next month, the cutoff of query 07. Without a date selection it is the end of the date table, so it counts the cases still open at the end of the data.
* **`Handoffs per Case`** divides by completed cases (as query 02 does); the contract's `handoff_count` is the plain `SUM(fact_case[handoffs])` over all cases (739 in the snapshot), which is a card, not a ratio.
* **Case-level floor.** `MAX(0, business - sw * paused_business)` is applied per case inside `SUMX`, as D-06 floors active hours at 0 per case; a ratio of column sums would not do that.
* The switch is all-or-nothing (the two contract states); per-reason eligibility is whatever the SQL export put into `paused_business_seconds`, i.e. the SLA rule's own `pause_policy`.

## 4. Power Query (M) steps

```m
// fact_case
let
    Source   = Csv.Document(File.Contents("bi_fact_case.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers  = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed    = Table.TransformColumnTypes(Headers, {
                 {"opened_date", type date}, {"sla_minutes", Int64.Type}, {"handoffs", Int64.Type},
                 {"calendar_seconds", Int64.Type}, {"business_seconds", Int64.Type}, {"paused_seconds", Int64.Type},
                 {"paused_business_seconds", Int64.Type}, {"active_seconds", Int64.Type}, {"within_sla", Int64.Type},
                 {"has_submission", Int64.Type}, {"has_rejection", Int64.Type}, {"first_reviewed", Int64.Type},
                 {"first_accepted", Int64.Type}, {"required_types", Int64.Type}, {"required_accepted_types", Int64.Type}}, "en-US"),
    // ISO-8601 with Z -> a UTC datetime (no local-time shift); empty text -> null
    OpenedAt = Table.TransformColumns(Typed, {{"opened_at", each DateTimeZone.RemoveZone(DateTimeZone.SwitchZone(DateTimeZone.FromText(_), 0)), type datetime}}),
    DoneAt   = Table.TransformColumns(OpenedAt, {{"completed_at", each if _ = null or _ = "" then null else DateTimeZone.RemoveZone(DateTimeZone.SwitchZone(DateTimeZone.FromText(_), 0)), type nullable datetime}}),
    DoneDate = Table.AddColumn(DoneAt, "completed_date", each if [completed_at] = null then null else DateTime.Date([completed_at]), type nullable date)
in
    DoneDate

// fact_step_instance: same pattern; ready_at, started_at, decided_at are nullable datetimes; *_seconds are Int64 (null stays null)

// dim_organization (and likewise dim_workflow_version, dim_step) from the published JSON: { "entity": ..., "dataset_version": ..., "rows": [ ... ] }
let
    Source = Json.Document(File.Contents("organizations.json")),
    Rows   = Table.FromRecords(Source[rows]),
    Typed  = Table.TransformColumnTypes(Rows, {{"organization_id", type text}, {"segment", type text}, {"region", type text}})
in
    Typed

// dim_assignee
let
    A = Table.SelectColumns(fact_step_instance, {"assignee_id"}),  B = Table.SelectColumns(fact_step_instance, {"reviewer_id"}),
    People = Table.Distinct(Table.RenameColumns(Table.Combine({A, Table.RenameColumns(B, {{"reviewer_id", "assignee_id"}})}), {{"assignee_id", "person_id"}})),
    NoNulls = Table.SelectRows(People, each [person_id] <> null),
    Kind   = Table.AddColumn(NoNulls, "person_kind", each
                 if Text.StartsWith([person_id], "rev-") then "reviewer" else if Text.StartsWith([person_id], "cmp-") then "compliance"
                 else if Text.StartsWith([person_id], "acc-") then "account" else "ops", type text)
in
    Kind

// dim_date: one row per day of the data range; working hours from the calendar's working and holiday intervals
let
    Days = List.Dates(#date(2025, 4, 1), Duration.Days(#date(2026, 10, 1) - #date(2025, 4, 1)) + 1, #duration(1, 0, 0, 0)),
    T    = Table.FromList(Days, Splitter.SplitByNothing(), {"date"}, null, ExtraValues.Error),
    Typed = Table.TransformColumnTypes(T, {{"date", type date}}),
    Mon  = Table.AddColumn(Typed, "month_start", each Date.StartOfMonth([date]), type date),
    End  = Table.AddColumn(Mon, "period_end_utc", each DateTime.From(Date.AddDays([date], 1)), type datetime)
    // is_working_day / working_hours: merge with the per-day sum of kind = "working" intervals from calendar_intervals.json, minus holidays
in
    End
```
The M above is a design: it has not been run. Open the exports with `UTF-8` encoding, set the data-source privacy level to Organizational or Ignore for a local-files-only model, and keep `Detect data types` off so the typed steps above are authoritative.

## 5. Expected values to check in Desktop (computed outside Power BI)

From the two CSV exports (Python exact rationals) and the analysis queries; all-time, no slicer, `Pause Switch` = 1. They are the targets the model must hit; **none has been confirmed in Power BI**.

| Measure | Expected | Source |
|---|---|---|
| Completed Cases | 712 | `01` TOTAL, `bi_fact_case.sql` |
| Calendar Cycle Hours | 79.9529 | `01` TOTAL |
| Business Cycle Hours | 18.5028 | `01` TOTAL |
| Paused Hours | 35.4966 | `06` lens `region`, region ALL |
| Active Elapsed Hours | 7.9020 (with `Pause Switch` = 0: 18.5028) | `01` TOTAL; business = active when nothing is deducted |
| SLA Attainment | 0.533708 (380 of 712) | `03` ALL / ALL |
| Rework Rate | 0.186047 | `05` ALL |
| First Pass Rate | 0.930983 | `05` ALL |
| Document Completeness | 0.997153 (all 733 cases; 1 for completed cases) | domain `document_completeness`, export |
| Handoffs per Case | 1.0211 (1.021067 over the 712 completed; 739 handoffs over all cases) | export |
| Step Waiting Hours | 0.5344 (3,623 started steps); `approve_account` 1.0491; with the reviewer relationship `rev-004` 1.7855 | export; `04` |
| Open Backlog | 21 with no date slicer; 17 at the 2026-08 month-end; month slicer values equal `07` | `07` |

## 6. Remaining Desktop verification (open)
1. Load the two CSVs and the JSON dimensions; confirm no query error, no rows lost (733 and 3,665) and that `completed_at` is null for exactly 21 rows.
2. Confirm the eight relationships (six active, two inactive) and that the model shows no ambiguity warning.
3. Create the measures and tick every row of section 5, including `Pause Switch` = 0 and a month slicer on `Open Backlog` against `07`.
4. Check blank behaviour: select an organization with no completed case and confirm the ratios show blank, not 0.
5. Check `Reviewer Step Waiting Hours` by `dim_assignee[person_id]` shows `rev-004` about 3.3 times `rev-005` (query 04).
6. Confirm a refresh from changed CSVs works and that the report opens without gateway or credential prompts (local files only).
7. Save as `.pbix`, record its sha256 and the Desktop version here. Until then this package is a design.
