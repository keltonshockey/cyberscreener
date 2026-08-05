# research/

Scratch space for the rebuild's analysis lanes (R2 IC harness, R3 Lane 1 PIT
program, R4 cohort D). Nothing in here is imported by the running application,
and nothing in here may change the data the application collects.

## The three rules

**1. All reads go through `connect_ro`.**

```python
from db.ro import connect_ro          # api/db/ro.py

conn = connect_ro("/app/data/cyberscreener.db")
rows = conn.execute("SELECT ticker, lt_score FROM scores WHERE scan_id = ?", (n,)).fetchall()
```

`connect_ro` opens the database with a `file:...?mode=ro` URI, so a stray
`INSERT`/`UPDATE`/`DELETE` fails at the sqlite layer instead of mutating the
production store. Do not call `sqlite3.connect` directly in this directory.

**2. All outputs go to `research/out/` or to explicit new files.**

`research/out/` is gitignored — it is for generated artifacts (parquet, CSV,
plots, fitted models). Never write back into `cyberscreener.db`, never write
into `api/`, and never overwrite an input. New durable outputs get their own new
path; nothing here edits a file another process owns.

**3. Nothing in `research/` imports write paths from `api/db/models.py`.**

`db.models` carries `save_scan`, `log_play`, `close_play`, and the migration
entry points. Importing it from research code puts a write path one typo away
from the collected data. This rule is enforced by
`api/tests/test_data_preservation.py::test_research_dir_forbids_write_imports`.

## Why these rules exist

`REBUILD_PLAN_2026-08-04.md` section 0 makes data preservation the prime
directive: the collector is not the failure, and every dataset it has gathered —
315K+ score rows, 3M+ signals, the cohort C journal — is irreplaceable forward
evidence. The rebuild is additive-only by construction: new code reads
read-only and writes to new files in new directories.

Related enforcement: the schema-preservation tripwire and the static
destructive-statement guard, both in `api/tests/test_data_preservation.py`.
