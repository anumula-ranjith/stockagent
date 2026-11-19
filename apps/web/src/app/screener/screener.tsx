"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState, type FormEvent } from "react";
import { DataTable } from "@/components/data-table";
import { StockTicker } from "@/components/stock-ticker";
import { CandleField, RangeFields } from "@/components/screen-fields";
import { SignInNotice, State } from "@/components/presentation";
import { useSession } from "@/components/providers";
import { Button } from "@/components/ui/button";
import { AngelMarketStatus } from "@/components/angel-market-status";
import type { components } from "@/lib/api-types";
import styles from "./screener.module.css";
import { stockHref } from "@/lib/stock-context";

import { screenQuery } from "@/lib/screener-query";
import { defaultScreen, intradayLabel, savedScreen, screenStorageKey, type ScreenFilters } from "@/lib/screen-filters";
const capLabels: Record<string, string> = {large: "Large cap", mid: "Mid cap", small: "Small cap"};
type Row = components["schemas"]["ScreenRow"];
const number = new Intl.NumberFormat("en-IN", {maximumFractionDigits: 2});
const day = (iso: string | null) => iso
  ? new Intl.DateTimeFormat("en-IN", {day: "numeric", month: "short", year: "numeric", timeZone: "UTC"}).format(new Date(iso))
  : "Unavailable";

function resultsColumns(screen: ScreenFilters): ColumnDef<Row>[] {
  const values: [keyof Row, string][] = [
    ["close", "Latest price · ₹"], ["below_high_pct", "% below high"], ["below_low_pct", "% below low"],
    ["above_high_pct", "% above high"], ["above_low_pct", "% above low"],
    ["high_52w", "52w high"], ["low_52w", "52w low"],
    ["heikin_ashi_color", "Heikin Ashi candle"], ["heikin_ashi_transition", "Heikin Ashi turn"],
  ];
  return [{accessorKey: "ticker", header: "Ticker", cell: ({row}) =>
    <StockTicker ticker={row.original.ticker} href={stockHref(row.original.ticker, {screen})}/>},
    {accessorKey: "cap", header: "Cap segment", cell: ({row}) => capLabels[row.original.cap ?? ""] ?? "—"},
    {accessorKey: "industry", header: "Industry", cell: ({row}) => row.original.industry ?? "—"},
  ...values.map(([key, header]) => ({accessorKey: key, header, cell: ({row}: {row: {original: Row}}) => {
    const v = row.original[key];
    if (v == null) return <span title="Insufficient price history">—</span>;
    if (v === "red_to_green" || v === "green_to_red") return <span className={v === "red_to_green" ? styles.up : styles.down}>{v === "red_to_green" ? "Red → Green" : "Green → Red"}</span>;
    if (v === "green" || v === "red") return <span className={v === "green" ? styles.up : styles.down}>{v === "green" ? "Green" : "Red"}</span>;
    if (v === "doji") return "Doji";
    return typeof v === "number" ? number.format(v) : "None";
  }}))];
}

export function Screener() {
  const session = useSession();
  if (session.isPending) return <State>Checking session…</State>;
  if (session.error) return <State error>{session.error.message}</State>;
  if (!session.data) return <SignInNotice next="/screener">Sign in to screen the locally stored market data.</SignInNotice>;
  return <AccountScreen key={session.data.id} user={session.data.id}/>;
}

function AccountScreen({user}: {user: string}) {
  const [applied, apply] = useState(() => savedScreen(user));
  const [draft, setDraft] = useState(applied);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const query = useQuery({...screenQuery(user, applied), placeholderData: keepPreviousData,
    refetchInterval: 120_000, refetchOnWindowFocus: "always"});
  function save(next: ScreenFilters) {
    setSearch("");
    if (JSON.stringify(applied) === JSON.stringify(next)) void query.refetch();
    else apply(next);
    try {
      window.localStorage.setItem(screenStorageKey(user), JSON.stringify(next));
      setStatus("Filters saved in this browser.");
    } catch { setStatus("Filters applied for this visit. Browser storage is unavailable."); }
  }
  function submit(e: FormEvent) {
    e.preventDefault();
    save(draft);
  }
  const set = (patch: Partial<ScreenFilters>) => {
    setStatus("");
    setDraft(prev => ({...prev, ...patch}));
  };
  const data = query.data;
  const rows = data?.rows.filter(r => r.ticker.toLowerCase().includes(search.trim().toLowerCase())) ?? [];
  return <div className={styles.layout}>
    <AngelMarketStatus user={user}/>
    <section className={styles.universe} aria-label="Universe filters">
      <label className="field">Nifty index
        <select value={draft.index_code} onChange={e => set({index_code: e.target.value})}>
          {Object.entries(data?.index_options ?? {NIFTY500: "Nifty 500", [draft.index_code]: draft.index_code}).map(([code, label]) =>
            <option key={code} value={code}>{label}</option>)}
        </select>
      </label>
      <label className="field">Market-cap segment
        <select value={draft.cap} onChange={e => set({cap: e.target.value as ScreenFilters["cap"]})}>
          <option value="">All sizes</option>
          <option value="large">Large cap · Nifty 100</option>
          <option value="mid">Mid cap · Midcap 150</option>
          <option value="small">Small cap · Smallcap 250</option>
        </select>
      </label>
      <label className="field">Industry
        <select value={draft.industry} onChange={e => set({industry: e.target.value})}>
          <option value="">All industries</option>
          {(data?.industries ?? (draft.industry ? [draft.industry] : [])).map(value => <option key={value}>{value}</option>)}
        </select>
      </label>
      <label className={styles.eligible}><input type="checkbox" checked={draft.fo_only}
        onChange={e => set({fo_only: e.target.checked})}/>F&amp;O eligible only</label>
    </section>
    <form onSubmit={submit} className={styles.filter}>
      <h2>Screen filters</h2>
      <fieldset><legend>52-week range</legend>
        <RangeFields screen={draft} change={set}/>
      </fieldset>
      <fieldset><legend>Heikin Ashi</legend>
        <CandleField screen={draft} change={set}/>
        <p className={styles.note}>Compares the latest stored daily candle with the previous trading session. Doji candles do not count as a color change.</p>
      </fieldset>
      <div className={styles.actions}><Button type="submit">Save and apply</Button>
        <Button type="button" variant="ghost" onClick={() => {setDraft(defaultScreen); save(defaultScreen);}}>Reset</Button></div>
      {status && <p role="status" className={styles.note}>{status}</p>}
    </form>
    <section className={styles.results} aria-label="Screen results" aria-busy={query.isFetching}>
      {query.isFetching && data && <p role="status">{query.isPlaceholderData
        ? "Updating results… Showing the previous screen until the new results arrive." : "Refreshing prices…"}</p>}
      {query.isError ? <State error>{query.error.message}</State> : !data ? <State>Screening the selected universe…</State> : <>
        <div className={styles.stats}>
          <div><span>Latest price session</span><strong>{day(data.asof)}</strong>{data.priced > 0 && <span>{intradayLabel(data) ?? "Daily close"}</span>}</div>
          <div><span>Selected constituents</span><strong>{data.members}</strong></div>
          <div><span>Priced stocks</span><strong>{data.priced}</strong></div>
          <div><span>52-week range coverage</span><strong>{data.range_coverage}</strong></div>
        </div>
        <div className="surface">
          <div className={styles.resultHead}><div><h2>{data.rows.length} matching stocks</h2>
            <p>Daily Heikin Ashi · {day(data.asof)}</p></div>
            <label className="field">Find a result<input type="search" value={search} placeholder="Ticker" onChange={e => setSearch(e.target.value)}/></label></div>
          <DataTable columns={resultsColumns(data.filters)} data={rows} label="Nifty screener results" empty="No constituents match these filters."/>
        </div>
        <p className={styles.note}>The latest price is compared with adjusted highs and lows from the preceding 52 calendar weeks, excluding the latest session so new highs and lows can match. A listing must span the window and cover at least 95% of observed sessions. Heikin Ashi uses daily OHLC prices. A dash means history is unavailable.</p>
      </>}
    </section>
  </div>;
}
