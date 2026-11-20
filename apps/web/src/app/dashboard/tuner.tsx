"use client";

import { useQuery } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { parseAsStringLiteral, useQueryState } from "nuqs";
import { useEffect, useState } from "react";
import { SignInNotice, State } from "@/components/presentation";
import { useSession } from "@/components/providers";
import { agentLabels, agents } from "@/lib/api";
import { UniverseFilters, type UniverseSelection } from "@/components/universe-filters";
import { rankingQuery } from "@/lib/ranking-query";
import { SettingsPanel } from "./ranker-controls";
import { defaults, type Settings } from "./ranker-model";
import { Candidates, Heat } from "./ranker-tables";
import s from "./ranker.module.css";

const Portfolio = dynamic(()=>import("./portfolio").then(m=>m.Portfolio));
const DailyPortfolio = dynamic(()=>import("./daily-portfolio"));
const tabs = [...agents,"combined","daily","portfolio"] as const;
const labels = {...agentLabels,combined:"Combined",daily:"Daily Portfolio",portfolio:"Portfolio & Backtest"};
const summaries = {
  technical:"Ranks stocks on chart health. Stocks failing a long-list filter can still appear as shorts.",
  sentiment:"Ranks stocks on news tone, analyst revisions, sector performance and available positioning data.",
  momentum:"Ranks stocks by the strength of their price trends across several lookbacks.",
  fundamental:"Ranks stocks on value, quality, growth, balance-sheet health and shareholder yield.",
  combined:"The four agents’ weighted scores determine each side of the portfolio.",
};

export function Tuner() {
  const session = useSession();
  const [tab,setTab] = useQueryState("tab",parseAsStringLiteral(tabs).withDefault("technical"));
  const [date,setDate] = useState("");
  const [universe,setUniverse] = useState<UniverseSelection>({index_code:"NIFTY500", cap:"", industry:"", fo_only:false});
  const [config,setConfig] = useState<Settings>(defaults);
  const [debounced,setDebounced] = useState(config);
  useEffect(()=>{const t=window.setTimeout(()=>setDebounced(config),230);return()=>window.clearTimeout(t);},[config]);
  const snapshot = useQuery(rankingQuery(session.data?.id,date,debounced,universe));
  const data = snapshot.data;
  return <div className={s.workspace}><div className={s.inner}>
    <header className={s.header}><div><h1>Four-agent stock ranker</h1>
      <p>Technical, sentiment, momentum and fundamental rankings for the Nifty 500.</p>
      <span className={s.source}><i/>{data?.price_date?"NSE close · "+data.price_date:"NSE India · End of day"}</span></div>
      {session.data && <label className={s.date}>Ranking date<input type="date" aria-label="Ranking date" value={date||data?.asof||""} max={new Date().toLocaleDateString("en-CA")} onChange={e=>setDate(e.target.value)}/></label>}
    </header>
    {session.data && <UniverseFilters data={data} draft={universe} set={patch=>setUniverse(current=>({...current,...patch}))}/>}
    <nav className={s.tabs} aria-label="Ranking workspaces">{tabs.map(name=><button key={name} aria-current={name===tab?"page":undefined}
      onClick={()=>void setTab(name)}>{labels[name]}</button>)}</nav>
    {session.isPending ? <State>Checking your session…</State> : session.isError ? <State error>Session unavailable.</State>
      : !session.data ? <SignInNotice next="/dashboard">Sign in to tune the four agents and compare their portfolios.</SignInNotice>
      : tab==="portfolio" ? <Portfolio selection={universe} config={config} end={date||data?.asof||new Date().toISOString().slice(0,10)} admin={!!session.data.is_admin} user={session.data.id}/>
      : tab==="daily" ? <DailyPortfolio key={session.data.id} user={session.data.id} config={config} selection={universe}
          snapshot={data} updating={snapshot.isFetching || debounced!==config} rankingError={snapshot.error?.message}/>
      : <div className={s.grid}><SettingsPanel tab={tab} config={config} change={setConfig} coverage={data?.coverage}/>
        <section className={s.results} aria-busy={snapshot.isFetching}>
          <p className={s.summary}>{summaries[tab]}</p>
          {snapshot.isError ? <p role="alert" className={s.error}>{snapshot.error.message} <button onClick={()=>void snapshot.refetch()}>Retry</button></p>
            : !data ? <div className={s.card}><p role="status" className={s.hint}>Loading Nifty 500 observations…</p></div>
            : data.universe===0 ? <State>No constituents match these filters on the selected date.</State>
            : <>{tab==="sentiment" && <Heat data={data.heat} boost={config.boost_sectors}/>}
              <div className={tab==="combined"?s.stacked:s.books}>{(["longs","shorts"] as const).map(side=><Candidates key={side} tab={tab} side={side} size={data.settings.size} data={data} settings={data.settings}/>)}</div>
              <p className={s.hint} role="status">{snapshot.isFetching?"Updating rankings…":data.universe+" constituents · "+(tab==="fundamental"?"Raw licensed or unavailable values appear as a dash.":"Only observed signals contribute to a candidate’s rank.")}</p></>}
        </section></div>}
  </div></div>;
}
