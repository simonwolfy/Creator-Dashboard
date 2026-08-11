# Historical Stream Intelligence

Creator Intelligence can import historical Twitch stream-day mappings and their
category-event evidence through **Import Center**. Supported inputs are CSV, TSV,
XLSX, and XLSM. The recognized types are `twitch_game_history` and
`twitch_game_events`.

Import stream days before event evidence. Unresolved days are retained without a
guessed category. Events that do not match a committed stream day are retained in
the review table instead of being discarded. Re-importing an identical source is
idempotent and reports the rows as unchanged.

Inspect the result under **Twitch Intelligence → Historical data**. The health
summary reports source-backed and unresolved days, single- and multi-game days,
matched evidence, and evidence awaiting review. Daily performance metrics are
associated with a game only for source-backed single-game days. Multi-game daily
metrics are never assigned to one category.

To validate the private Pre-Codex cohort without adding creator data to Git:

```powershell
python tools/verify_historical_pack.py "C:\path\to\extracted-pack"
```

The verifier uses a temporary database and checks the fixed counts, all 25
regression cases, unresolved-game safety, and a second idempotent import.
