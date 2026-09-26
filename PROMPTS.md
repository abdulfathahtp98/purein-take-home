# AI prompts and how I used them

AI tools were used throughout, as the brief allows. Every result below was
checked by running the scripts and tests against a real PostgreSQL database
on my machine.

## 1. First draft

The first draft of this repository (migrations, loader, daily sales report,
data-quality report, tests, README) was generated with an AI assistant in an
earlier session. I did not keep a copy of those prompts, so they are not
reproduced here.

## 2. Review before submission

**Prompt:** I gave the assistant the task description and the full
repository, and asked it to review the work before I submitted.

**What came back:** it re-checked every README finding against
`messages.json` directly, and found three problems in the first draft:

- Finding #3 was misdiagnosed. Transaction numbers are per-pump counters,
  not "reused across days", so the correct key is
  `(PtsId, Pump, Transaction)`.
- The unregistered-controller query double-counted (3 sales x 4 readings
  = 12 rows), so the report said 12 and 12 instead of 3 and 4.
- UTC timestamps were written as naive values into a `TIMESTAMPTZ` column,
  so results depended on the database session's timezone.

It also surfaced findings #5-#8: the tank-reading schedule proving Station
D's clock is UTC, the 17-44x gap between tank drops and recorded sales, the
missing Gasoline 95 probe, and the water-height jumps.

## 3. Applying the fixes

**Prompt:** "yes please" -- accepting the assistant's offer to patch the
loader, the data-quality report, the tests and the README.

**What came back:** migration `0007_add_natural_keys.sql`, timezone-aware
UTC conversion and exact-decimal amounts in the loader, a rewritten
`data_quality_report.py` with one query per finding, three new tests, and
the updated README.

## 4. Running it locally

I installed PostgreSQL on Windows, ran every script, and pasted the output back
for the assistant to check against the expected numbers.

This run is where the timezone bug showed up for real: my local server uses
`Asia/Riyadh`, and the first draft's daily report put sales from before
03:00 onto the previous day, producing four spurious 13 Sept rows. After the
fix, the report matched the independently calculated totals exactly, the
loader inserted 151 sales and 52 readings (0 on a second run), and all 6
tests passed.

