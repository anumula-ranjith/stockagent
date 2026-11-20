# Browser performance check — 19 November 2026

Tested the signed-in local application through the in-app browser. Times below
measure automated navigation through a visible populated heading/table, including
automation overhead. They are single observations, not percentile guarantees.

| Page | Observed data-ready time |
| --- | ---: |
| Stocks directory | 237 ms |
| Portfolio holdings, before / after quote fix | 7,076 / 467 ms |
| Watchlist table, before / after quote fix | 8,935 / 336 ms |
| Backtest archive empty state | 237 ms |
| Home rankings | 722 ms |
| Dashboard rankings | 231 ms |
| Screener, cached return | 248 ms |
| Screener 10% below high filter | 539 ms |

## Changes

- Bound the India-market calendar date and cutoff in personal quote SQL. Using
  CURRENT_DATE prevented Timescale from excluding old partitions at planning time.
  The measured quote planning time dropped from 10,545.659 ms to 53.217 ms.
- Shared the default ranking query between Home and Dashboard, including its
  response shape, user identity, settings and date.
- Prefetch relevant data on navigation focus, hover and click; keep personal data
  keyed by the authenticated user and preserve mutation invalidation.
- Keep the previous screener table visible during updates, explicitly label it,
  and use its original indicator periods until the new result arrives.
- Reuse EOD stock profiles, evidence, scores and news across navigation for five
  minutes, matching the existing market-data cache policy.

## Functional checks

Opened Home, all six dashboard workspaces, Screener, Stocks, INFY/TCS details,
Portfolio, Watchlists, Backtest, Account, Methodology and Assistant. Verified ticker
search/suggestions, the 10%-below-high screen (116 results), a 5–10% band (62),
F&O-only screening (217), filter reset, and watchlist/portfolio popup opening.
Existing user trades and watchlist entries were not modified in this check.

The frontend production build passed compilation, lint and type validation.
Five quote and portfolio-ledger tests passed, including bound dates, duplicate
source observations, cache reuse and older-listing fallback.

## Remaining limits

- Cold full-history stock loading exceeded one second (12.6 s during a server
  restart/data update); a standalone ten-year price query still spent 2.26 s
  planning. Do not claim that every page and dataset is always under one second.
- A stock-analysis request returned 500 during concurrent server/schema work;
  retry subsequently rendered all four agents successfully.
- Both application processes were replaced externally during the check. The
  final frontend was running `.next-membership-edit`, replacing this check's
  `.next-browser-speed`; further timings need a stable deployment window.
- The account is not an administrator, so starting new backtests was unavailable.
  The tuned report rendered; the separate archive had no available report.
- Assistant requests show the missing OPENAI_API_KEY configuration error.
- Broker sync, password changes and destructive account-data operations were not
  exercised. First API startup also takes longer than steady-state navigation.
