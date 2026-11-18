# Probe scripts

Phase 1 lives here. For each source, write `probe_<source>.py` that:

1. Loads credentials from `.env`.
2. Calls the intended endpoint for one known ticker and one date.
3. Prints the raw response to stdout.
4. Saves the raw JSON (gzipped) to `tests/fixtures/<source>_<endpoint>.json(.gz)`.
5. Records the confirmed endpoint, field names and entitlement status in
   `docs/DATA_NOTES.md`.

Nothing in `src/stock_agents/ingest/` should be written before its probe fixture
exists and is reviewed.
