"use client";

import { CandlestickSeries, ColorType, createChart, type CandlestickData, type UTCTimestamp } from "lightweight-charts";
import { useTheme } from "next-themes";
import { useEffect, useMemo, useRef } from "react";
import type { PriceBar } from "@/lib/api";
import { State } from "./presentation";

export default function PriceChart({ prices }: { prices: PriceBar[] }) {
  const host = useRef<HTMLDivElement>(null);
  const { resolvedTheme } = useTheme();
  const candles = useMemo(() => {
    const byDate = new Map<number, CandlestickData<UTCTimestamp>>();
    for (const row of prices) {
      if (row.open == null || row.high == null || row.low == null || row.close == null) continue;
      const time = (Date.parse(row.date) / 1000) as UTCTimestamp;
      if (!Number.isFinite(time)) continue;
      byDate.set(time, { time, open: row.open, high: row.high, low: row.low, close: row.close });
    }
    return Array.from(byDate.values()).sort((a, b) => a.time - b.time);
  }, [prices]);
  useEffect(() => {
    if (!host.current || !candles.length) return;
    const css = getComputedStyle(document.documentElement);
    const color = (token: string) => css.getPropertyValue(token).trim();
    const chart = createChart(host.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: color("--panel") }, textColor: color("--muted"), attributionLogo: true },
      grid: { vertLines: { visible: false }, horzLines: { color: color("--line") } },
      timeScale: { borderColor: color("--line") },
      rightPriceScale: { borderColor: color("--line") },
      localization: { priceFormatter: (price: number) => price.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) },
    });
    chart.addSeries(CandlestickSeries, {
      upColor: color("--long"), downColor: color("--short"), borderVisible: false,
      wickUpColor: color("--long"), wickDownColor: color("--short"),
    }).setData(candles);
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [candles, resolvedTheme]);
  return candles.length ? <div className="chart-area" ref={host} role="img" aria-label="TradingView OHLC candlestick chart"/> : <State>No complete price bars are available.</State>;
}
