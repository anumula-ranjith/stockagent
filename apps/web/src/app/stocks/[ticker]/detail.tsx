"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, BookmarkPlus, BriefcaseBusiness } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { SignInNotice, State } from "@/components/presentation";
import { useSession } from "@/components/providers";
import { api, ApiError, type HistoryPoint, type NewsItem, type PriceBar, type UniverseRow } from "@/lib/api";
import { stockHref, type ChartRules, type Periods } from "@/lib/stock-context";
import type { Settings } from "@/app/dashboard/ranker-model";
import { StockIndicators } from "./stock-indicators";
import { StockProfile } from "./stock-profile";
import { AgentAnalysis } from "./agent-analysis";
import styles from "./stock-indicators.module.css";
import { dateLabel, rupees } from "@/lib/utils";

const PriceChart = dynamic(() => import("@/components/price-chart"), { ssr: false, loading: () => <State>Loading price chart…</State> });
const HistoryChart = dynamic(() => import("@/components/research-charts").then(module => module.HistoryChart), {
  ssr: false, loading: () => <State>Loading score chart…</State>,
});
const periods = [[90, "3M"], [365, "1Y"], [1095, "3Y"], [3650, "All"]] as const;
const safeUrl = (value?: string | null) => !!value && /^https?:\/\//i.test(value) ? value : null;

export function StockDetail({ ticker, periods: inputs, rules, settings, asof }: { ticker: string; periods: Periods; rules: ChartRules; settings?: Settings; asof?: string }) {
  const [days, setDays] = useState<number>(365);
  const [chartPeriods, setChartPeriods] = useState(inputs);
  const [chartRules, setChartRules] = useState(rules);
  const [analysisDate, setAnalysisDate] = useState(asof || "");
  const [search, setSearch] = useState("");
  const [searchError, setSearchError] = useState("");
  const router = useRouter();
  const encoded = encodeURIComponent(ticker);
  const session = useSession();
  const prices = useQuery({
    queryKey: ["price", ticker, 3650],
    queryFn: ({ signal }) => api<PriceBar[]>(`/prices/${encoded}?days=3650`, { signal }),
  });
  const news = useQuery({
    queryKey: ["news", ticker],
    queryFn: ({ signal }) => api<NewsItem[]>(`/news/${encoded}?limit=15`, { signal }),
  });
  const history = useQuery({
    queryKey: ["history", ticker, session.data?.id], enabled: !!session.data,
    queryFn: ({ signal }) => api<HistoryPoint[]>(`/scores/${encoded}`, { signal }),
  });
  const universe = useQuery({queryKey:["universe"],
    queryFn:({signal}) => api<UniverseRow[]>("/universe",{signal})});
  const term = search.trim().toLowerCase();
  const matches = term ? (universe.data ?? []).filter(row =>
    row.ticker.toLowerCase().includes(term) || row.symbol?.toLowerCase().includes(term)
  ).sort((a,b) => Number(b.ticker.toLowerCase().startsWith(term)) - Number(a.ticker.toLowerCase().startsWith(term))
    || a.ticker.localeCompare(b.ticker)).slice(0,6) : [];
  const href = (symbol: string) => stockHref(symbol,{periods:chartPeriods,rules:chartRules,settings,asof:analysisDate||undefined});
  const latest = prices.data?.filter(row => row.close != null).at(-1);
  const tab = (value: number, label: string) => <button key={value} aria-pressed={days === value} onClick={() => setDays(value)}>{label}</button>;
  return <div className={`stack ${styles.detail}`}>
    <form className={styles.stockSearch} role="search" onSubmit={event=>{
      event.preventDefault();
      if (matches.length) { setSearchError(""); router.push(href(matches[0].ticker)); }
      else setSearchError(universe.isPending ? "Stock list is loading." : "No matching ticker found.");
    }}>
      <label htmlFor="detail-stock-search">Search another stock</label>
      <div className={styles.stockSearchControls}><input id="detail-stock-search" type="search" value={search}
        onChange={event=>{setSearch(event.target.value);setSearchError("");}} placeholder="Search NSE ticker or symbol" autoComplete="off"/>
        <button type="submit">View stock</button></div>
      {searchError&&<p role="status" className={styles.searchMessage}>{searchError}</p>}
      {term && matches.length>0 && <ul className={styles.searchMatches} aria-label="Matching stocks">{matches.map(row=><li key={row.ticker}>
        <Link href={href(row.ticker)}><strong>{row.ticker}</strong>{row.symbol&&row.symbol!==row.ticker&&<span>{row.symbol}</span>}
          {row.sector&&<span>{row.sector}</span>}</Link></li>)}</ul>}
    </form>
    <nav className={styles.nav} aria-label="Stock sections">{[
      ["profile","Overview"], ...(session.data ? [["analysis","Agent readings"],["indicators","Technical indicators"]] : []),
      ["prices","Price chart"],["history","Score history"],["news","Headlines"],
    ].map(([id,label])=><a key={id} href={"#"+id}>{label}</a>)}</nav>
    {session.data && <div className="stock-personal-actions"><Link className="button button-secondary" href={`/watchlist?add=${encodeURIComponent(ticker)}`}><BookmarkPlus size={16}/>Add to watchlist</Link>
      <Link className="button button-secondary" href={`/portfolio?ticker=${encodeURIComponent(ticker)}`}><BriefcaseBusiness size={16}/>Record a trade</Link></div>}
    {session.data ? <div id="profile"><StockProfile ticker={ticker}/></div> : <div className="metrics" id="profile">
      <div className="metric"><span>Last close</span><strong>{latest?.close == null ? "—" : rupees.format(latest.close)}</strong></div>
      <div className="metric"><span>Last price date</span><strong>{latest ? dateLabel(latest.date) : "—"}</strong></div>
      <div className="metric"><span>Sector</span><strong>{universe.data?.find(row=>row.ticker===ticker)?.sector ?? "—"}</strong></div>
    </div>}
    {session.data ? <>
      <div className="surface-top" id="analysis"><span>{settings ? "Custom dashboard weights and rules" : "Default dashboard weights and rules"}</span>
        <label className="field">Ranking date<input type="date" value={analysisDate}
          max={new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Kolkata"}).format(new Date())}
          onChange={e=>setAnalysisDate(e.target.value)}/></label></div>
      <AgentAnalysis ticker={ticker} settings={settings} asof={analysisDate || undefined}/>
      <div id="indicators"><StockIndicators ticker={ticker} initial={inputs} initialRules={rules}
        onApply={(periods, nextRules)=>{setChartPeriods(periods);setChartRules(nextRules);}}/></div>
    </> : !session.isPending && <SignInNotice next={stockHref(ticker,{periods:inputs,rules,settings,asof})}>View the company profile, four agent readings and technical inputs.</SignInNotice>}
    <div className="surface" id="prices">
      <div className="surface-top"><h2 className="section-title">Price history</h2><div className="tabs" aria-label="Price range">{periods.map(([value, label]) => tab(value, label))}</div></div>
      <div className="chart-pad">
        {prices.isError ? prices.error instanceof ApiError && prices.error.status === 404
          ? <State>No price data is available for this range.</State> : <State error>{prices.error.message}</State>
          : prices.data ? <PriceChart prices={prices.data} periods={chartPeriods} rules={chartRules} days={days}/> : <State>Loading prices…</State>}
      </div>
    </div>
    <div className="surface" id="history">
      <div className="surface-top"><h2 className="section-title">Agent score history</h2></div>
      {session.isPending ? <State>Checking your session…</State>
        : !session.data ? <State>Sign in to view historical scores.</State>
        : history.isError ? <State error>{history.error.message}</State>
        : history.data ? <div className="chart-pad"><HistoryChart points={history.data}/></div> : <State>Loading scores…</State>}
    </div>
    <div className="surface" id="news">
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
