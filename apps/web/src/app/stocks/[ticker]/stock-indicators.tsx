"use client";

import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { State } from "@/components/presentation";
import { CandleField, RangeFields } from "@/components/screen-fields";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { type ChartRules, type Periods } from "@/lib/stock-context";
import { candleLabels, intradayLabel, screenRequest, type ScreenFilters } from "@/lib/screen-filters";
import { dateLabel, rupees } from "@/lib/utils";
import styles from "./stock-indicators.module.css";

type Report = components["schemas"]["StockIndicators"] & {matches_filters:boolean};
const fields: [keyof Periods, string, number, number][] = [
  ["ema_fast", "Fast EMA", 1, 199], ["ema_slow", "Slow EMA", 2, 200],
  ["ema_sessions_ago", "EMA sessions ago", 0, 20], ["macd_fast", "MACD fast", 1, 199],
  ["macd_slow", "MACD slow", 2, 200], ["macd_signal", "Signal period", 1, 100],
  ["macd_sessions_ago", "MACD sessions ago", 0, 20],
];
const money = (n: number | null) => n == null ? "—" : rupees.format(n);
const percent = (n: number | null) => n == null ? "—" : n.toFixed(2) + "%";
function crossover(value: "up" | "down" | "none" | null, date: string | null) {
  if (!value || !date) return "Insufficient history for this crossover.";
  return ({up:"Crossed above", down:"Crossed below", none:"No crossover"}[value]) + " on " + dateLabel(date) + ".";
}
function relation(a: number | null, b: number | null) {
  if (a == null || b == null) return "Insufficient history";
  return a === b ? "Equal" : a > b ? "Above" : "Below";
}

type Filters = {belowHigh: number | null; aboveLow: number | null; rules: ChartRules; screen?: ScreenFilters};
const choices: [ChartRules["ema_rule"], string][] = [["any","Any relationship"],["above","Above"],
  ["below","Below"],["cross_up","Crossed above"],["cross_down","Crossed below"]];
export function StockIndicators({ticker, initial, initialRules, screen, onApply}: {ticker: string; initial: Periods;
  initialRules: ChartRules; screen?: ScreenFilters; onApply?: (periods: Periods, rules: ChartRules, screen?: ScreenFilters) => void}) {
  const [draft, setDraft] = useState(initial);
  const [applied, apply] = useState(initial);
  const [filters, setFilters] = useState<Filters>({belowHigh:null,aboveLow:null,rules:initialRules,screen});
  const [activeFilters, setActiveFilters] = useState(filters);
  const [error, setError] = useState("");
  const query = useQuery({queryKey:["stock-indicators",ticker,applied,activeFilters],
    queryFn:({signal}) => api<Report>("/screener/stock/" + encodeURIComponent(ticker),
      {method:"POST", signal, body:JSON.stringify({...applied,...activeFilters.rules,
        ...(activeFilters.screen ? {...screenRequest(activeFilters.screen), screen_universe:true}
          : {below_high_pct:activeFilters.belowHigh, above_low_pct:activeFilters.aboveLow})})})});
  const result = query.data;
  const values = result?.values;
  function submit(e: FormEvent) {
    e.preventDefault();
    if (draft.ema_fast >= draft.ema_slow || draft.macd_fast >= draft.macd_slow) {
      setError("Each fast period must be shorter than its slow period."); return;
    }
    setError(""); apply({...draft}); setActiveFilters({...filters}); onApply?.({...draft},filters.rules,filters.screen);
  }
  const changeScreen = (patch: Partial<ScreenFilters>) => setFilters(previous => previous.screen
    ? {...previous, screen: {...previous.screen, ...patch}} : previous);
  return <section className="surface" aria-label="Technical indicator settings and results">
    <div className="surface-top"><h2 className="section-title">Technical indicators</h2>
      {result?.asof && <span className="subtle">Session · {dateLabel(result.asof)}{intradayLabel(result) && " · " + intradayLabel(result)}</span>}</div>
    <div className={styles.body}>
      <form onSubmit={submit}>
        <fieldset className={styles.group}><legend>52-week range</legend><div className={styles.fields}>
          {filters.screen ? <RangeFields screen={filters.screen} change={changeScreen}/> :
            ([["belowHigh","Within % below high",100],["aboveLow","Within % above low",10000]] as const).map(([key,label,max])=>
            <label className="field" key={key}>{label}<input type="number" min="0" max={max} step="any"
              placeholder="Any distance" value={filters[key] ?? ""}
              onChange={e=>setFilters({...filters,[key]:e.target.value===""?null:e.target.valueAsNumber})}/></label>)}</div></fieldset>
        {filters.screen && <fieldset className={styles.group}><legend>Heikin Ashi</legend>
          <CandleField screen={filters.screen} change={changeScreen}/></fieldset>}
        <fieldset className={styles.group}><legend>EMA</legend><div className={styles.fields}>{fields.slice(0,3).map(([key,label,min,max]) =>
          <label key={key} className="field">{label}<input required type="number" min={min} max={max}
            value={Number.isFinite(draft[key]) ? draft[key] : ""}
            onChange={e => setDraft({...draft,[key]:e.target.valueAsNumber})}/></label>)}</div>
          <label className="field">Fast EMA vs slow EMA<select value={filters.rules.ema_rule}
            onChange={e=>setFilters({...filters,rules:{...filters.rules,ema_rule:e.target.value as ChartRules["ema_rule"]}})}>
            {choices.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label></fieldset>
        <fieldset className={styles.group}><legend>MACD</legend><div className={styles.fields}>{fields.slice(3).map(([key,label,min,max]) =>
          <label key={key} className="field">{label}<input required type="number" min={min} max={max}
            value={Number.isFinite(draft[key]) ? draft[key] : ""}
            onChange={e => setDraft({...draft,[key]:e.target.valueAsNumber})}/></label>)}</div>
          <label className="field">MACD vs signal<select value={filters.rules.macd_rule}
            onChange={e=>setFilters({...filters,rules:{...filters.rules,macd_rule:e.target.value as ChartRules["macd_rule"]}})}>
            {choices.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label></fieldset>
        <div className={styles.actions}><span className="subtle">Periods use trading sessions. For a crossover, 0 selects the latest session and 1 selects the previous session.</span>
          <Button type="submit">Apply filters</Button></div>
        {error && <p role="alert">{error}</p>}
      </form>
      {query.isError ? <State error>{query.error.message}</State> : !result ? <State>Calculating indicators…</State>
        : !values ? <State>No daily price observations are available.</State> :
        <><p className={result.matches_filters ? styles.match : styles.noMatch} role="status">
          {result.matches_filters ? "This stock matches your applied filters." : "This stock does not match your applied filters."}</p>
        <div className={styles.readings}>
          <article><h3>EMA trend</h3><strong>{relation(values.ema_fast,values.ema_slow)}</strong>
            <p>EMA {applied.ema_fast} · {money(values.ema_fast)}<br/>EMA {applied.ema_slow} · {money(values.ema_slow)}</p>
            <small>{crossover(values.ema_cross,result.ema_date)}</small></article>
          <article><h3>MACD vs signal</h3><strong>{relation(values.macd,values.macd_signal)}</strong>
            <p>MACD · {money(values.macd)}<br/>Signal · {money(values.macd_signal)}<br/>Histogram · {money(values.macd_hist)}</p>
            <small>{crossover(values.macd_cross,result.macd_date)}</small></article>
          <article><h3>52-week trading range</h3><strong>{money(values.low_52w)} – {money(values.high_52w)}</strong>
            <p>Below high · {percent(values.below_high_pct)}<br/>Above low · {percent(values.above_low_pct)}</p>
            <small>{values.high_52w == null ? "Insufficient adjusted price history for a 52-week range." : "Adjusted intraday range, expressed in current price units."}</small></article>
          {activeFilters.screen && <article><h3>Heikin Ashi</h3><strong>{values.heikin_ashi_color ?? "Unavailable"}</strong>
            <p>{values.heikin_ashi_transition === "none" ? "No color change" : values.heikin_ashi_transition
              ? candleLabels[values.heikin_ashi_transition] : "Previous candle unavailable"}</p>
            <small>Open · {money(values.heikin_ashi_open ?? null)}<br/>Close · {money(values.heikin_ashi_close ?? null)}</small></article>}
        </div></>}
    </div>
  </section>;
}
