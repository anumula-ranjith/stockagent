"use client";

import { useQuery } from "@tanstack/react-query";
import { LatestStockNews } from "@/app/news/company-news";
import { StockActions } from "@/components/stock-actions";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useState } from "react";
import { PageTitle, SignInNotice, State } from "@/components/presentation";
import { useSession } from "@/components/providers";
import { api, ApiError, type HistoryPoint, type PriceBar, type UniverseRow } from "@/lib/api";
import { stockHref, type ChartRules, type Periods } from "@/lib/stock-context";
import { screenDescription, type ScreenFilters } from "@/lib/screen-filters";
import type { Settings } from "@/app/dashboard/ranker-model";
import { StockIndicators } from "./stock-indicators";
import { LatestQuote, Derivatives } from "./angel-panels";
import { StockProfile } from "./stock-profile";
import { AgentAnalysis } from "./agent-analysis";
import styles from "./stock-indicators.module.css";
import { dateLabel, rupees } from "@/lib/utils";

const PriceChart = dynamic(() => import("@/components/price-chart"), { ssr: false, loading: () => <State>Loading price chart…</State> });
const HistoryChart = dynamic(() => import("@/components/research-charts").then(module => module.HistoryChart), {
  ssr: false, loading: () => <State>Loading score chart…</State>,
});
const periods = [[90, "3M"], [365, "1Y"], [1095, "3Y"], [3650, "All"]] as const;
export function StockDetail({ ticker, periods: inputs, rules, settings, asof, screen }: {
  ticker: string; periods: Periods; rules: ChartRules; settings?: Settings; asof?: string; screen?: ScreenFilters;
}) {
  const [days, setDays] = useState<number>(365);
  const [chartPeriods, setChartPeriods] = useState(inputs);
  const [chartRules, setChartRules] = useState(rules);
  const [appliedScreen, setAppliedScreen] = useState(screen);
  const [analysisDate, setAnalysisDate] = useState(asof || "");
  const [search, setSearch] = useState("");
  const [searchError, setSearchError] = useState("");
  const encoded = encodeURIComponent(ticker);
  const session = useSession();
  const prices = useQuery({
    queryKey: ["price", ticker, 3650],
    queryFn: ({ signal }) => api<PriceBar[]>(`/prices/${encoded}?days=3650`, { signal }),
  });
  const [source,setSource]=useState("angel");
  const brokerBars=useQuery({queryKey:["angel-candles",ticker],enabled:!!session.data && source==="angel",
    queryFn:({signal})=>api<PriceBar[]>("/market-feed/stock/"+encoded+"/candles",{signal}),staleTime:300000});
  const bars=brokerBars.data??[];
  const end=bars.at(-1);
  const boundary=end ? Date.parse(end.date)-364*86400000 : 0;
  const year=bars.filter(row=>Date.parse(row.date)>boundary);
  let rangeText="Insufficient 52-week history.";
  if(end?.close && bars.length && Date.parse(bars[0].date)<=boundary && year.length>=240){
    const high=Math.max(...year.map(row=>row.high??0)), low=Math.min(...year.map(row=>row.low??Infinity));
    rangeText=`As of ${end.date} · ${(100*(1-end.close/high)).toFixed(2)}% below 52-week high · ${(100*(end.close/low-1)).toFixed(2)}% above 52-week low · Raw daily candles`;
  }
  const history = useQuery({
    queryKey: ["history", ticker, session.data?.id], enabled: !!session.data,
    queryFn: ({ signal }) => api<HistoryPoint[]>(`/scores/${encoded}`, { signal }),
  });
  const universe = useQuery({queryKey:["universe"],
    queryFn:({signal}) => api<UniverseRow[]>("/universe",{signal})});
  const term = search.trim().toLowerCase();
  const matches = term ? (universe.data ?? []).filter(row =>
    row.ticker.toLowerCase().includes(term) || row.symbol?.toLowerCase().includes(term) || row.company_name?.toLowerCase().includes(term)
  ).sort((a,b) => Number(b.ticker.toLowerCase().startsWith(term)) - Number(a.ticker.toLowerCase().startsWith(term))
    || a.ticker.localeCompare(b.ticker)).slice(0,6) : [];
  const href = (symbol: string) => stockHref(symbol,{periods:chartPeriods,rules:chartRules,settings,asof:analysisDate||undefined,screen:appliedScreen});
  const latest = prices.data?.filter(row => row.close != null).at(-1);
  const tab = (value: number, label: string) => <button key={value} aria-pressed={days === value} onClick={() => setDays(value)}>{label}</button>;
  return <div className={`stack ${styles.detail}`}>
    <PageTitle title={ticker} action={<form className={styles.stockSearch} role="search" onSubmit={event=>{
      event.preventDefault();
      if (matches.length) { setSearchError(""); window.open(href(matches[0].ticker), "_blank", "noopener,noreferrer"); }
      else setSearchError(universe.isPending ? "Stock list is loading." : universe.isError ? "Stock search is unavailable. Please refresh and try again." : "No matching company found.");
    }}>
      <label htmlFor="detail-stock-search">Search company</label>
      <div className={styles.stockSearchControls}><input id="detail-stock-search" type="search" value={search}
        onChange={event=>{setSearch(event.target.value);setSearchError("");}} placeholder="Company name or NSE ticker" autoComplete="off"/>
        <button type="submit">View stock</button></div>
      {(searchError || (term && !matches.length)) && <p role="status" className={styles.searchMessage}>{searchError || (universe.isPending ? "Loading companies..." : universe.isError ? "Stock search is unavailable. Please refresh and try again." : "No matching company found.")}</p>}
      {term && matches.length>0 && <ul className={styles.searchMatches} aria-label="Matching stocks">{matches.map(row=><li key={row.ticker}>
        <Link href={href(row.ticker)} target="_blank" rel="noopener noreferrer"><strong>{row.ticker}</strong>{row.company_name && <span>{row.company_name}</span>}
          {row.sector&&<span>{row.sector}</span>}</Link><StockActions ticker={row.ticker}/></li>)}</ul>}
    </form>}>NSE equity research</PageTitle>
    <div className="surface" id="prices">
      <div className="surface-top"><h2 className="section-title">Price history</h2><div className="tabs" aria-label="Price range">{periods.filter(([value])=>source!=="angel" || value!==1095).map(([value, label]) => tab(value, label))}</div></div>
      {session.data && <div className="surface-top"><LatestQuote ticker={ticker}/><label className="field">Candle source<select value={source} onChange={event=>setSource(event.target.value)}><option value="warehouse">Local price history</option><option value="angel">Angel One · 2 years</option></select></label></div>}
      <div className="chart-pad">
        {source==="angel" && session.data ? brokerBars.data?.length ? <><PriceChart prices={brokerBars.data} periods={chartPeriods} rules={chartRules} days={days}/>{end && <div className="metrics">{[["Open",end.open],["High",end.high],["Low",end.low],["Close",end.close],["Volume",end.volume]].map(([label,value])=><div className="metric" key={label}><span>{label}</span><strong>{typeof value==="number"?value.toLocaleString("en-IN"):"—"}</strong></div>)}</div>}<p>{rangeText}</p></> : brokerBars.isPending ? <State>Loading Angel One daily candles…</State> : <><p>Angel One candles unavailable. Showing local history.</p>{prices.data && <PriceChart prices={prices.data} periods={chartPeriods} rules={chartRules} days={days}/>}</> : prices.isError ? prices.error instanceof ApiError && prices.error.status === 404
          ? <State>No price data is available for this range.</State> : <State error>{prices.error.message}</State>
          : prices.data ? <PriceChart prices={prices.data} periods={chartPeriods} rules={chartRules} days={days}/> : <State>Loading prices…</State>}
      </div>
    </div>
    <nav className={styles.nav} aria-label="Stock sections">{[
      ["profile","Overview"], ...(session.data ? [["analysis","Agent readings"],["indicators","Technical indicators"]] : []),
      ["prices","Price chart"],...(session.data?[["derivatives","Derivatives"]]:[]),["history","Score history"],["news","News & announcements"],
    ].map(([id,label])=><a key={id} href={"#"+id}>{label}</a>)}</nav>
    {appliedScreen && <div className="surface surface-top"><div>
      <h2 className="section-title">Applied screener filters</h2><p>{screenDescription(appliedScreen)}</p>
    </div>{session.data && <a className="text-link" href="#indicators">View indicator results</a>}</div>}
    <StockActions ticker={ticker} expanded/>
    {session.data && <Derivatives ticker={ticker}/>}

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
      <div id="indicators"><StockIndicators ticker={ticker} initial={inputs} initialRules={rules} screen={screen}
        onApply={(periods, nextRules, nextScreen)=>{setChartPeriods(periods);setChartRules(nextRules);setAppliedScreen(nextScreen);}}/></div>
    </> : !session.isPending && <SignInNotice next={stockHref(ticker,{periods:inputs,rules,settings,asof,screen})}>View the company profile, four agent readings and technical inputs.</SignInNotice>}
    <div className="surface" id="history">
      <div className="surface-top"><h2 className="section-title">Agent score history</h2></div>
      {session.isPending ? <State>Checking your session…</State>
        : !session.data ? <State>Sign in to view historical scores.</State>
        : history.isError ? <State error>{history.error.message}</State>
        : history.data ? <div className="chart-pad"><HistoryChart points={history.data}/></div> : <State>Loading scores…</State>}
    </div>
    <LatestStockNews symbol={ticker}/>
  </div>;
}
