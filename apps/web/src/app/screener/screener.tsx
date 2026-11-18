"use client";

import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { DataTable } from "@/components/data-table";
import { SignInNotice, State } from "@/components/presentation";
import { useSession } from "@/components/providers";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";
import styles from "./screener.module.css";

const defaults = {
  below_high_pct: null as number | null, above_low_pct: null as number | null,
  ema_fast: 9, ema_slow: 21, ema_rule: "any", ema_sessions_ago: 0,
  macd_fast: 12, macd_slow: 26, macd_signal: 9, macd_rule: "any", macd_sessions_ago: 0,
};
type Filter = typeof defaults;
type Row = components["schemas"]["ScreenRow"];
type Result = components["schemas"]["ScreenResult"];
const number = new Intl.NumberFormat("en-IN", {maximumFractionDigits: 2});
const day = (iso: string | null) => iso
  ? new Intl.DateTimeFormat("en-IN", {day: "numeric", month: "short", year: "numeric", timeZone: "UTC"}).format(new Date(iso))
  : "Unavailable";
function resultsColumns(q: Filter): ColumnDef<Row>[] {
  const values: [keyof Row, string][] = [
    ["close", "Close · ₹"], ["below_high_pct", "% below high"], ["above_low_pct", "% above low"],
    ["high_52w", "52w high"], ["low_52w", "52w low"], ["ema_fast", "EMA " + q.ema_fast],
    ["ema_slow", "EMA " + q.ema_slow], ["ema_cross", "EMA cross"], ["macd", "MACD"],
    ["macd_signal", "Signal"], ["macd_hist", "Histogram"], ["macd_cross", "MACD cross"],
  ];
  return [{accessorKey: "ticker", header: "Ticker", cell: ({row}) =>
    <Link className="text-link" href={"/stocks/" + encodeURIComponent(row.original.ticker)}>{row.original.ticker}</Link>},
  ...values.map(([key, header]) => ({accessorKey: key, header, cell: ({row}: {row: {original: Row}}) => {
    const v = row.original[key];
    if (v == null) return <span title="Insufficient price history">—</span>;
    if (v === "up" || v === "down") return <span className={v === "up" ? styles.up : styles.down}>{v === "up" ? "↑ Bullish" : "↓ Bearish"}</span>;
    return typeof v === "number" ? number.format(v) : "None";
  }}))];
}

function Indicator({name, q, set}: {
  name: "ema" | "macd"; q: Filter; set: (patch: Partial<Filter>) => void;
}) {
  const rule = q[`${name}_rule`];
  return <fieldset><legend>{name.toUpperCase()}</legend>
    <div className={styles.periods}>{(name === "ema" ? ["fast","slow"] as const : ["fast","slow","signal"] as const).map(part => {
      const key = `${name}_${part}` as "ema_fast" | "ema_slow" | "macd_fast" | "macd_slow" | "macd_signal";
      return <label className="field" key={part}>{part}<input type="number" required min={part === "slow" ? 2 : 1}
        max={part === "signal" ? 100 : part === "slow" ? 200 : 199}
        value={Number.isFinite(q[key]) ? q[key] : ""} onChange={e => set({[key]: e.target.valueAsNumber})}/></label>;
    })}</div>
    <label className="field">{name === "ema" ? "Fast EMA vs slow EMA" : "MACD vs signal line"}
      <select value={rule} onChange={e => set({[`${name}_rule`]: e.target.value})}>
        <option value="any">Any relationship</option><option value="above">Above</option><option value="below">Below</option>
        <option value="cross_up">Crossed above</option><option value="cross_down">Crossed below</option>
      </select>
    </label>
    <label className="field">Trading sessions ago<input type="number" min="0" max="20" required
      value={Number.isFinite(q[`${name}_sessions_ago`]) ? q[`${name}_sessions_ago`] : ""}
      onChange={e => set({[`${name}_sessions_ago`]: e.target.valueAsNumber})}/></label>
  </fieldset>;
}

export function Screener() {
  const session = useSession();
  const [draft, setDraft] = useState(defaults);
  const [applied, apply] = useState(defaults);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const query = useQuery({queryKey: ["nifty-screen", session.data?.id, applied], enabled: !!session.data,
    queryFn: ({signal}) => api<Result>("/screener/run", {method: "POST", body: JSON.stringify(applied), signal})});
  function submit(e: FormEvent) {
    e.preventDefault();
    if (draft.ema_fast >= draft.ema_slow || draft.macd_fast >= draft.macd_slow) {
      setError("Choose a fast period shorter than the slow period for both indicators."); return;
    }
    setError("");
    if (JSON.stringify(applied) === JSON.stringify(draft)) void query.refetch();
    else apply({...draft});
  }
  const set = (patch: Partial<Filter>) => setDraft(prev => ({...prev, ...patch}));
  const data = query.data;
  const rows = data?.rows.filter(r => r.ticker.toLowerCase().includes(search.trim().toLowerCase())) ?? [];
  if (session.isPending) return <State>Checking session…</State>;
  if (session.error) return <State error>{session.error.message}</State>;
  if (!session.data) return <SignInNotice next="/screener">Sign in to screen the locally stored market data.</SignInNotice>;
  return <div className={styles.layout}>
    <form onSubmit={submit} className={styles.filter}>
      <h2>Screen filters</h2>
      <fieldset><legend>52-week range</legend>
        {([["below_high_pct","Within % below high"],["above_low_pct","Within % above low"]] as const).map(([key,label]) =>
          <label className="field" key={key}>{label}<input type="number" min="0" max={key === "below_high_pct" ? 100 : 10000}
            step="any" placeholder="Any distance" value={draft[key] ?? ""} onChange={e => set({[key]: e.target.value === "" ? null : e.target.valueAsNumber})}/></label>)}
      </fieldset>
      <Indicator name="ema" q={draft} set={set}/><Indicator name="macd" q={draft} set={set}/>
      <p className={styles.note}>0 selects the latest stored session. 1 selects the preceding trading session.</p>
      {error && <p role="alert">{error}</p>}
      <div className={styles.actions}><Button type="submit" disabled={query.isFetching}>Run screen</Button>
        <Button type="button" variant="ghost" onClick={() => {setDraft(defaults); apply(defaults); setError(""); setSearch("");}}>Reset</Button></div>
    </form>
    <section className={styles.results} aria-label="Screen results">
      {query.isError ? <State error>{query.error.message}</State> : !data ? <State>Reading Nifty price history…</State> : <>
        <div className={styles.stats}>
          <div><span>Latest price session</span><strong>{day(data.asof)}</strong></div>
          <div><span>Current constituents</span><strong>{data.members}</strong></div>
          <div><span>Adjusted closes</span><strong>{data.priced}</strong></div>
          <div><span>52-week range coverage</span><strong>{data.range_coverage}</strong></div>
        </div>
        <div className="surface">
          <div className={styles.resultHead}><div><h2>{data.rows.length} matching stocks</h2>
            <p>EMA event · {day(data.ema_date)} &nbsp; / &nbsp; MACD event · {day(data.macd_date)}</p></div>
            <label className="field">Find a result<input type="search" value={search} placeholder="Ticker" onChange={e => setSearch(e.target.value)}/></label></div>
          <DataTable columns={resultsColumns(applied)} data={rows} label="Nifty screener results" empty="No constituents match these filters."/>
        </div>
        <p className={styles.note}>Range filters use observed adjusted highs and lows over 52 calendar weeks. A listing must span the window and cover at least 95% of observed sessions. All selected filters must match. A dash means history is unavailable. Indicator values use the latest close. Crossovers use the selected session.</p>
      </>}
    </section>
  </div>;
}
