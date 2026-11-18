"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight } from "lucide-react";
import dynamic from "next/dynamic";
import { useState } from "react";
import { SignInNotice, State } from "@/components/presentation";
import { useSession } from "@/components/providers";
import { api, ApiError, type HistoryPoint, type NewsItem, type PriceBar, type UniverseRow } from "@/lib/api";
import { dateLabel, rupees } from "@/lib/utils";

const PriceChart = dynamic(() => import("@/components/price-chart"), { ssr: false, loading: () => <State>Loading price chart…</State> });
const HistoryChart = dynamic(() => import("@/components/research-charts").then(module => module.HistoryChart), {
  ssr: false, loading: () => <State>Loading score chart…</State>,
});
const periods = [[90, "3M"], [365, "1Y"], [1095, "3Y"], [3650, "All"]] as const;
const safeUrl = (value?: string | null) => !!value && /^https?:\/\//i.test(value) ? value : null;

export function StockDetail({ ticker }: { ticker: string }) {
  const [days, setDays] = useState<number>(365);
  const encoded = encodeURIComponent(ticker);
  const session = useSession();
  const prices = useQuery({
    queryKey: ["price", ticker, days],
    queryFn: ({ signal }) => api<PriceBar[]>(`/prices/${encoded}?days=${days}`, { signal }),
  });
  const news = useQuery({
    queryKey: ["news", ticker],
    queryFn: ({ signal }) => api<NewsItem[]>(`/news/${encoded}?limit=15`, { signal }),
  });
  const history = useQuery({
    queryKey: ["history", ticker, session.data?.id], enabled: !!session.data,
    queryFn: ({ signal }) => api<HistoryPoint[]>(`/scores/${encoded}`, { signal }),
  });
  const universe = useQuery({ queryKey: ["universe"], queryFn: ({ signal }) => api<UniverseRow[]>("/universe", { signal }) });
  const identity = universe.data?.find(row => row.ticker === ticker);
  const latest = prices.data?.filter(row => row.close != null).at(-1);
  const tab = (value: number, label: string) => <button key={value} aria-pressed={days === value} onClick={() => setDays(value)}>{label}</button>;
  return <div className="stack">
    <div className="metrics">
      <div className="metric"><span>Last close</span><strong>{latest?.close == null ? "—" : rupees.format(latest.close)}</strong></div>
      <div className="metric"><span>Last price date</span><strong>{latest ? dateLabel(latest.date) : "—"}</strong></div>
      <div className="metric"><span>Sector</span><strong>{identity?.sector ?? "—"}</strong></div>
    </div>
    <div className="surface">
      <div className="surface-top"><h2 className="section-title">Price history</h2><div className="tabs" aria-label="Price range">{periods.map(([value, label]) => tab(value, label))}</div></div>
      <div className="chart-pad">
        {prices.isError ? prices.error instanceof ApiError && prices.error.status === 404
          ? <State>No price data is available for this range.</State> : <State error>{prices.error.message}</State>
          : prices.data ? <PriceChart prices={prices.data}/> : <State>Loading prices…</State>}
      </div>
    </div>
    <div className="surface">
      <div className="surface-top"><h2 className="section-title">Agent score history</h2></div>
      {session.isPending ? <State>Checking your session…</State>
        : !session.data ? <SignInNotice next={`/stocks/${encoded}`}>Sign in to view the stored agent scores.</SignInNotice>
        : history.isError ? <State error>{history.error.message}</State>
        : history.data ? <div className="chart-pad"><HistoryChart points={history.data}/></div> : <State>Loading scores…</State>}
    </div>
    <div className="surface">
      <div className="surface-top"><h2 className="section-title">Recent headlines</h2></div>
      {news.isError ? <State error>{news.error.message}</State> : !news.data ? <State>Loading news…</State>
        : !news.data.length ? <State>No headlines are stored for this ticker.</State>
        : <div className="table-scroll" tabIndex={0} role="region" aria-label="Recent headlines">
          <table><thead><tr><th>Date</th><th>Headline</th><th>Source</th><th>Polarity</th></tr></thead>
          <tbody>{news.data.map((item, index) => <tr key={item.published_at + index}>
            <td>{dateLabel(item.published_at.slice(0, 10))}</td>
            <td className="headline">{safeUrl(item.url)
              ? <a href={safeUrl(item.url)!} target="_blank" rel="noopener noreferrer">{item.headline ?? "Read article"} <ArrowUpRight size={13}/></a>
              : item.headline ?? "—"}</td>
            <td>{item.source || "—"}</td><td>{item.polarity?.toFixed(2) ?? "—"}</td>
          </tr>)}</tbody></table>
        </div>}
    </div>
  </div>;
}
