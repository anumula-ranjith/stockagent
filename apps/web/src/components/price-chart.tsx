"use client";

import { CandlestickSeries, ColorType, createChart, createSeriesMarkers, HistogramSeries, LineSeries,
  type CandlestickData, type HistogramData, type LineData, type SeriesMarker, type UTCTimestamp } from "lightweight-charts";
import { useTheme } from "next-themes";
import { useEffect, useMemo, useRef } from "react";
import type { PriceBar } from "@/lib/api";
import type { ChartRules, Periods } from "@/lib/stock-context";
import { State } from "./presentation";

type Cross = {time: UTCTimestamp; direction: "up" | "down"};

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

export default function PriceChart({prices, periods, rules, days}: {
  prices: PriceBar[]; periods: Periods; rules: ChartRules; days: number;
}) {
  const host = useRef<HTMLDivElement>(null);
  const {resolvedTheme} = useTheme();
  const data = useMemo(() => {
    const rows = Array.from(new Map(prices.filter(row => row.open != null && row.high != null && row.low != null && row.close != null)
      .map(row => [row.date, row] as const)).values()).sort((a, b) => a.date.localeCompare(b.date));
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
    const fastLine: LineData<UTCTimestamp>[] = [], slowLine: LineData<UTCTimestamp>[] = [];
    const macdLine: LineData<UTCTimestamp>[] = [], signalLine: LineData<UTCTimestamp>[] = [];
    const histogram: HistogramData<UTCTimestamp>[] = [];
    for (let i = 0; i < rows.length; i++) {
      const row = rows[i], time = times[i];
      if (!Number.isFinite(time) || time < cutoff) continue;
      candles.push({time, open: row.open!, high: row.high!, low: row.low!, close: row.close!});
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
    return {candles, fastLine, slowLine, macdLine, signalLine, histogram,
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
      localization: {priceFormatter: (price: number) => price.toLocaleString("en-IN", {minimumFractionDigits: 2, maximumFractionDigits: 2})}});
    const price = chart.addSeries(CandlestickSeries, {upColor: color("--long"), downColor: color("--short"), borderVisible: false,
      wickUpColor: color("--long"), wickDownColor: color("--short")});
    price.setData(data.candles);
    chart.addSeries(LineSeries, {color: "#e6b660", lineWidth: 2, priceLineVisible: false}).setData(data.fastLine);
    chart.addSeries(LineSeries, {color: "#8aa9ef", lineWidth: 2, priceLineVisible: false}).setData(data.slowLine);
    createSeriesMarkers(price, data.emaMarkers);
    chart.addSeries(HistogramSeries, {priceLineVisible: false, lastValueVisible: false}, 1).setData(data.histogram);
    const macd = chart.addSeries(LineSeries, {color: "#ddaa64", lineWidth: 2, priceLineVisible: false}, 1);
    macd.setData(data.macdLine);
    chart.addSeries(LineSeries, {color: "#a889df", lineWidth: 2, priceLineVisible: false}, 1).setData(data.signalLine);
    createSeriesMarkers(macd, data.macdMarkers);
    chart.panes()[1]?.setHeight(160);
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data, resolvedTheme]);

  return data.candles.length ? <div className="indicator-chart-wrap">
    <div className="indicator-legend"><span className="swatch ema-fast"/>EMA {periods.ema_fast}<span className="swatch ema-slow"/>EMA {periods.ema_slow}
      <span className="legend-note">↑ bullish crossover · ↓ bearish crossover</span></div>
    <div className="chart-area indicator-chart" ref={host} role="img"
      aria-label={`Price candlesticks with EMA ${periods.ema_fast} and ${periods.ema_slow} crossovers; MACD ${periods.macd_fast}, ${periods.macd_slow}, ${periods.macd_signal} below with crossover markers`}/>
    <div className="indicator-legend"><span className="swatch macd-line"/>MACD {periods.macd_fast}/{periods.macd_slow}
      <span className="swatch signal-line"/>Signal {periods.macd_signal}<span className="legend-note">Histogram = MACD − signal</span></div>
  </div> : <State>No complete price bars are available.</State>;
}
