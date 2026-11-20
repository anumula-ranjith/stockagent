"use client";

import { CandlestickSeries, ColorType, createChart, createSeriesMarkers, HistogramSeries, LineSeries,
  type CandlestickData, type HistogramData, type LineData, type SeriesMarker, type UTCTimestamp } from "lightweight-charts";
import { useTheme } from "next-themes";
import { Eye, EyeOff } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { PriceBar } from "@/lib/api";
import type { ChartRules, Periods } from "@/lib/stock-context";
import { dateLabel, rupees } from "@/lib/utils";
import { State } from "./presentation";

type Cross = {time: UTCTimestamp; direction: "up" | "down"};
const defaultVisibility = { fast: true, slow: true, macd: true, signal: true, histogram: true, crossovers: true };
type Visibility = typeof defaultVisibility;
type Indicator = keyof Visibility;
const preferenceKey = "quantora.chart.indicators.v1";
const signedRupees = new Intl.NumberFormat("en-IN", {style: "currency", currency: "INR", signDisplay: "exceptZero"});
const signedPercent = new Intl.NumberFormat("en-IN", {style: "percent", signDisplay: "exceptZero", minimumFractionDigits: 2, maximumFractionDigits: 2});
const shares = new Intl.NumberFormat("en-IN");

function DailyBarReadout({bar, previousClose, currency}: {currency: "INR" | "USD"; bar: PriceBar; previousClose?: number | null}) {
  const priceFormat = currency === "USD" ? new Intl.NumberFormat("en-US", {style:"currency",currency}) : rupees;
  const changeFormat = currency === "USD" ? new Intl.NumberFormat("en-US", {style:"currency",currency,signDisplay:"exceptZero"}) : signedRupees;
  const change = bar.close != null && previousClose != null ? bar.close - previousClose : null;
  const fraction = change != null && previousClose != null && previousClose > 0 ? change / previousClose : null;
  return <div className="daily-bar-readout" role="group" aria-label="Daily candle values">
    <time dateTime={bar.date}>{dateLabel(bar.date)}</time>
    <dl>
      {(["open", "high", "low", "close"] as const).map(key => <div key={key}>
        <dt>{key}</dt><dd>{bar[key] != null ? priceFormat.format(bar[key]) : "—"}</dd>
      </div>)}
      <div title="Change from the previous trading session’s close"><dt>Day change</dt>
        <dd data-direction={change == null || change === 0 ? undefined : change > 0 ? "up" : "down"}>
          {change == null ? "—" : changeFormat.format(change)}{fraction != null && ` (${signedPercent.format(fraction)})`}
        </dd>
      </div>
      <div><dt>Volume</dt><dd>{bar.volume == null ? "—" : shares.format(bar.volume)}</dd></div>
    </dl>
  </div>;
}

function readVisibility(): Visibility {
  const visibility = { ...defaultVisibility };
  try {
    const saved = JSON.parse(localStorage.getItem(preferenceKey) ?? "null");
    for (const key of Object.keys(visibility) as Indicator[]) {
      if (typeof saved?.[key] === "boolean") visibility[key] = saved[key];
    }
  } catch { /* Use the defaults when browser storage is unavailable. */ }
  return visibility;
}

// Match pandas ewm(adjust=False, ignore_na=True, min_periods=span) used by the screener.
function ema(values: (number | null)[], span: number): (number | null)[] {
  const alpha = 2 / (span + 1);
  let current = 0, count = 0;
  return values.map(value => {
    if (value == null || !Number.isFinite(value)) return null;
    current = count ? alpha * value + (1 - alpha) * current : value;
    count++;
    return count >= span ? current : null;
  });
}

function crosses(times: UTCTimestamp[], first: (number | null)[], second: (number | null)[]): Cross[] {
  const result: Cross[] = [];
  for (let i = 1; i < times.length; i++) {
    if (first[i] == null || second[i] == null || first[i - 1] == null || second[i - 1] == null) continue;
    const now = first[i]! - second[i]!, previous = first[i - 1]! - second[i - 1]!;
    if (now > 0 && previous <= 0) result.push({time: times[i], direction: "up"});
    if (now < 0 && previous >= 0) result.push({time: times[i], direction: "down"});
  }
  return result;
}

function markers(events: Cross[], selected: UTCTimestamp | undefined, rule: ChartRules["ema_rule"], label: string): SeriesMarker<UTCTimestamp>[] {
  return events.map(event => {
    const focused = event.time === selected && (rule === "any" || rule === "above" || rule === "below" || rule === `cross_${event.direction}`);
    return {time: event.time, position: event.direction === "up" ? "belowBar" : "aboveBar",
      shape: event.direction === "up" ? "arrowUp" : "arrowDown", color: event.direction === "up" ? "#35b98d" : "#e77970",
      size: focused ? 2 : 1, text: focused ? `${label} ${event.direction === "up" ? "↑" : "↓"} · selected session` : undefined};
  });
}

export default function PriceChart({prices, periods, rules, days, currency = "INR"}: {
  prices: PriceBar[]; periods: Periods; rules: ChartRules; days: number; currency?: "INR" | "USD";
}) {
  const host = useRef<HTMLDivElement>(null);
  const [hoverTime, setHoverTime] = useState<UTCTimestamp | null>(null);
  const [visible, setVisible] = useState(readVisibility);
  const applyVisibility = useRef<((value: Visibility) => void) | null>(null);
  const {resolvedTheme} = useTheme();
  const data = useMemo(() => {
    const sessions = Array.from(new Map(prices.map(row => [row.date, row] as const)).values())
      .sort((a, b) => a.date.localeCompare(b.date));
    const previousCloses = new Map(sessions.map((row, i) => [row.date, sessions[i - 1]?.close]));
    const rows = sessions.filter(row => row.open != null && row.high != null && row.low != null && row.close != null);
    const times = rows.map(row => (Date.parse(row.date) / 1000) as UTCTimestamp);
    let priceBasis = 1;
    const adjusted = rows.map(row => {
      if (row.adj_close != null && row.close && row.close > 0) priceBasis = row.adj_close / row.close;
      return row.adj_close ?? (row.source === "angel_one" ? row.close! * priceBasis : null);
    });
    const fast = ema(adjusted, periods.ema_fast), slow = ema(adjusted, periods.ema_slow);
    const macdFast = ema(adjusted, periods.macd_fast), macdSlow = ema(adjusted, periods.macd_slow);
    const macd = macdFast.map((value, i) => value == null || macdSlow[i] == null ? null : value - macdSlow[i]!);
    const signal = ema(macd, periods.macd_signal);
    const cutoff = days === 3650 ? 0 : (times.at(-1) ?? 0) - days * 86400;
    const candles: CandlestickData<UTCTimestamp>[] = [];
    const bars = new Map<UTCTimestamp, PriceBar>();
    const fastLine: LineData<UTCTimestamp>[] = [], slowLine: LineData<UTCTimestamp>[] = [];
    const macdLine: LineData<UTCTimestamp>[] = [], signalLine: LineData<UTCTimestamp>[] = [];
    const histogram: HistogramData<UTCTimestamp>[] = [];
    for (let i = 0; i < rows.length; i++) {
      const row = rows[i], time = times[i];
      if (!Number.isFinite(time) || time < cutoff) continue;
      candles.push({time, open: row.open!, high: row.high!, low: row.low!, close: row.close!});
      bars.set(time, row);
      // Indicators use adjusted closes, displayed in each bar's traded-price units.
      const basisClose = adjusted[i];
      const scale = basisClose && basisClose > 0 ? row.close! / basisClose : null;
      if (scale == null) continue;
      if (fast[i] != null) fastLine.push({time, value: fast[i]! * scale});
      if (slow[i] != null) slowLine.push({time, value: slow[i]! * scale});
      if (macd[i] != null) macdLine.push({time, value: macd[i]! * scale});
      if (signal[i] != null) signalLine.push({time, value: signal[i]! * scale});
      if (macd[i] != null && signal[i] != null) {
        const value = (macd[i]! - signal[i]!) * scale;
        histogram.push({time, value, color: value >= 0 ? "#35b98d88" : "#e7797088"});
      }
    }
    return {candles, bars, previousCloses, fastLine, slowLine, macdLine, signalLine, histogram,
      emaMarkers: markers(crosses(times, fast, slow).filter(event => event.time >= cutoff), times.at(-1 - periods.ema_sessions_ago), rules.ema_rule, "EMA"),
      macdMarkers: markers(crosses(times, macd, signal).filter(event => event.time >= cutoff), times.at(-1 - periods.macd_sessions_ago), rules.macd_rule, "MACD")};
  }, [prices, periods, rules, days]);

  useEffect(() => {
    if (!host.current || !data.candles.length) return;
    const css = getComputedStyle(document.documentElement);
    const color = (token: string) => css.getPropertyValue(token).trim();
    const chart = createChart(host.current, {autoSize: true,
      layout: {background: {type: ColorType.Solid, color: color("--panel")}, textColor: color("--muted"), attributionLogo: true},
      grid: {vertLines: {visible: false}, horzLines: {color: color("--line")}},
      timeScale: {borderColor: color("--line")}, rightPriceScale: {borderColor: color("--line")},
      localization: {priceFormatter: (price: number) => price.toLocaleString(currency === "USD" ? "en-US" : "en-IN", {minimumFractionDigits: 2, maximumFractionDigits: 2})}});
    const price = chart.addSeries(CandlestickSeries, {upColor: color("--long"), downColor: color("--short"), borderVisible: false,
      wickUpColor: color("--long"), wickDownColor: color("--short")});
    price.setData(data.candles);
    setHoverTime(null);
    chart.subscribeCrosshairMove(({time}) => setHoverTime(typeof time === "number" ? time : null));
    const fast = chart.addSeries(LineSeries, {color: "#e6b660", lineWidth: 2, priceLineVisible: false});
    const slow = chart.addSeries(LineSeries, {color: "#8aa9ef", lineWidth: 2, priceLineVisible: false});
    fast.setData(data.fastLine);
    slow.setData(data.slowLine);
    const emaMarkers = createSeriesMarkers(price, []);

    function addMacdPane() {
      const histogram = chart.addSeries(HistogramSeries, {priceLineVisible: false, lastValueVisible: false}, 1);
      const macd = chart.addSeries(LineSeries, {color: "#ddaa64", lineWidth: 2, priceLineVisible: false}, 1);
      const signal = chart.addSeries(LineSeries, {color: "#a889df", lineWidth: 2, priceLineVisible: false}, 1);
      histogram.setData(data.histogram);
      macd.setData(data.macdLine);
      signal.setData(data.signalLine);
      chart.panes()[1].setHeight(160);
      return { histogram, macd, signal, markers: createSeriesMarkers(macd, []) };
    }
    let lower: ReturnType<typeof addMacdPane> | undefined;
    applyVisibility.current = value => {
      fast.applyOptions({visible: value.fast});
      slow.applyOptions({visible: value.slow});
      emaMarkers.setMarkers(value.crossovers && value.fast && value.slow ? data.emaMarkers : []);
      if (value.macd || value.signal || value.histogram) {
        lower ??= addMacdPane();
        lower.macd.applyOptions({visible: value.macd});
        lower.signal.applyOptions({visible: value.signal});
        lower.histogram.applyOptions({visible: value.histogram});
        lower.markers.setMarkers(value.crossovers && value.macd && value.signal ? data.macdMarkers : []);
      } else if (lower) {
        lower.markers.detach();
        chart.removeSeries(lower.macd);
        chart.removeSeries(lower.signal);
        chart.removeSeries(lower.histogram);
        lower = undefined;
      }
    };
    chart.timeScale().fitContent();
    return () => { applyVisibility.current = null; chart.remove(); };
  }, [data, resolvedTheme, currency]);

  useEffect(() => { applyVisibility.current?.(visible); }, [visible, data, resolvedTheme]);
  useEffect(() => {
    try { localStorage.setItem(preferenceKey, JSON.stringify(visible)); } catch { /* Storage is optional. */ }
  }, [visible]);

  const controls: [Indicator, string, string?][] = [
    ["fast", `EMA ${periods.ema_fast}`, "ema-fast"], ["slow", `EMA ${periods.ema_slow}`, "ema-slow"],
    ["macd", `MACD ${periods.macd_fast}/${periods.macd_slow}`, "macd-line"],
    ["signal", `Signal ${periods.macd_signal}`, "signal-line"], ["histogram", "Histogram", "histogram"],
    ["crossovers", "Crossovers"],
  ];
  const active = controls.filter(([key]) => visible[key] && (key !== "crossovers"
    || (visible.fast && visible.slow) || (visible.macd && visible.signal)));
  const latest = data.candles.at(-1);
  const bar = (hoverTime != null && data.bars.get(hoverTime)) || (latest && data.bars.get(latest.time));
  return bar ? <div className="indicator-chart-wrap">
    <DailyBarReadout currency={currency} bar={bar} previousClose={data.previousCloses.get(bar.date)}/>
    <div className="indicator-legend" role="group" aria-label="Chart indicator visibility">
      {controls.map(([key, label, swatch]) => {
        const Icon = visible[key] ? Eye : EyeOff;
        return <button key={key} type="button" aria-pressed={visible[key]} title={`${visible[key] ? "Hide" : "Show"} ${label}`}
          onClick={() => setVisible(previous => ({...previous, [key]: !previous[key]}))}>
          {swatch && <span aria-hidden="true" className={`swatch ${swatch}`}/>}
          {label}<Icon size={14} aria-hidden="true"/>
        </button>;
      })}
    </div>
    <div className="chart-area indicator-chart" ref={host} role="img"
      aria-label={["Price candlesticks", ...active.map(([, label]) => label)].join(", ")}/>
    {(active.some(([key]) => key === "crossovers") || visible.histogram) && <div className="indicator-legend">
      {active.some(([key]) => key === "crossovers") && <span>↑ bullish crossover · ↓ bearish crossover</span>}
      {visible.histogram && <span className="legend-note">Histogram = MACD − signal</span>}
    </div>}
  </div> : <State>No complete price bars are available.</State>;
}
