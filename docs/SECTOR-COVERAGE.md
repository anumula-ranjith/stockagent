# Sector coverage repair — 19 November 2026

The active PostgreSQL directory contained 509 securities, of which 296 lacked a
sector. All 509 now have both sector and industry observations. Existing nonblank
sector values were preserved. Additions use today's effective and known dates,
not historical dates, and the `industry_sector_map` provenance identifier.

`ingest/sectors.py` contains the explicit mapping from stored NSE constituent
industries to broad research sectors. This is an application-derived grouping,
not a licensed GICS classification. Diversified remains Diversified; unknown
industry labels remain unresolved rather than receiving invented assignments.

UJJIVANSFB was the only active security with neither field. Its Financial
Services industry was verified using the exchange listing, with an ISIN guard:
https://www.msei.in/markets/equity/get-quotes/default?symbol=UJJIVANSFB
ISIN: INE551W01018. Its broad sector is Financials.

The daily importer now derives missing sectors for new constituents and runs the
gap-filling pass for the active directory. The ranker retains its existing NSE
industry-level grouping for derived rows. Company profiles accept derived
observations and prefer a populated sector when same-date observations tie.

Verification: 509 active / 509 sectors / 509 industries. Targeted tests completed
with six passes and six database integration tests skipped because no isolated
TEST_DATABASE_URL was configured. Live coverage was checked read-only directly
against PostgreSQL after the repair. No historical classifications were deleted.
