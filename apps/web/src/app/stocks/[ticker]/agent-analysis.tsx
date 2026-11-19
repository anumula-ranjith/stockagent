"use client";

import { useQuery } from "@tanstack/react-query";
import { useSession } from "@/components/providers";
import { SignInNotice, State } from "@/components/presentation";
import { agentLabels, api, type Agent } from "@/lib/api";
import type { Settings } from "@/app/dashboard/ranker-model";
import s from "./agent-analysis.module.css";

type Selection = {side:"long"|"short"|null; place:number|null};
type Position = {score:number|null; rank:number|null; peers:number};
type Factor = {
  key:string; label:string; description:string; unit:string; value:number|null; score:number|null;
  direction:string; status:"observed"|"unscoreable"|"missing"|"no_comparable_peers"; restricted:boolean; enabled:boolean;
  share:number; weight:number; peer_observations:number; peer_universe:number; pillar:string|null; contribution:number|null;
};
type AgentResult = Position & {
  agent:Agent; share:number; selection:Selection; observed:number; enabled:number; reading:string;
  passes_long_filters:boolean; composite_contribution:number|null; strongest:string|null; weakest:string|null;
  peer_group:string; vol_adjusted:boolean; bonus:number|null; headlines_7d?:number|null; min_headlines?:number;
  pillars:{key:string;score:number|null;weight:number;share:number}[]; factors:Factor[];
};
type Result = {
  ticker:string; asof:string; price_date:string|null; universe:number; in_universe:boolean; peer_comparison:boolean;
  sector?:string; composite?:Position & {selection:Selection;mode:string;reading:string}; agents?:AgentResult[];
};

const number = new Intl.NumberFormat("en-IN",{maximumFractionDigits:2});
const signed = (n:number) => (n>0?"+":"")+n.toFixed(1);
const score = (n:number|null) => n==null?"—":n.toFixed(1);
const percent = (n:number) => number.format(100*n)+"%";
const title = (key:string) => key.replaceAll("_"," ").replace(/^./,v=>v.toUpperCase());
function rawValue(f:Factor) {
  if (f.restricted) return "Licensed input";
  if (f.value==null) return "—";
  switch(f.unit) {
    case "fraction": return percent(f.value);
    case "fraction_points": return number.format(100*f.value)+" pp";
    case "multiple": return number.format(f.value)+"×";
    case "USD": return "US$"+number.format(f.value);
    case "points": return number.format(f.value)+" pts";
    default: return number.format(f.value);
  }
}
function bookName(book:Selection) {
  return book.side ? title(book.side)+" list · #"+book.place : "Outside selected lists";
}
function statusText(f:Factor) {
  if (!f.enabled) return "Disabled";
  if (f.status==="missing") return f.share>0?"Missing · neutral input":"Missing";
  if (f.status==="unscoreable") return "Outside scoring range";
  if (f.status==="no_comparable_peers") return "No comparable peers";
  return "Scored";
}
function Evidence({factor,positive}:{factor?:Factor;positive:boolean}) {
  return <div className={s.driver}><span>{positive?"Largest lift":"Largest drag"}</span>
    {factor ? <><strong>{factor.label}</strong><b className={positive?s.positive:s.negative}>{signed(factor.contribution!)} pts</b></>
      : <em>No {positive?"positive":"negative"} contribution</em>}</div>;
}
function FactorDetails({result}:{result:AgentResult}) {
  return <details className={s.details}><summary>Factor breakdown <span>{result.factors.length}</span></summary>
    <p className={s.note}>Factor scores use direction-adjusted percentile ranks within {result.peer_group}.
      {result.vol_adjusted?" Momentum ranks use returns divided by 60-session annualised volatility.":""} The point contribution measures each factor’s effect relative to 50.</p>
    {!!result.pillars.length && <div className={s.pillars}>{result.pillars.map(p=><div key={p.key}><span>{title(p.key)}</span>
      <strong>{score(p.score)}</strong><small>{percent(p.share)} of agent</small></div>)}</div>}
    <div className={s.scroll} role="region" aria-label={agentLabels[result.agent]+" factor data"} tabIndex={0}>
      <table><thead><tr><th>Factor</th><th>Raw value</th><th>Peer score</th><th>Peers with data</th><th>Score weight</th><th>Impact</th><th>Status</th></tr></thead>
        <tbody>{result.factors.map(f=><tr key={f.key}>
          <td><details className={s.definition}><summary>{f.label}</summary><p>{f.pillar ? title(f.pillar)+" pillar. ":""}{f.description} {f.direction}</p></details></td>
          <td>{rawValue(f)}</td><td>{score(f.score)}</td><td>{f.peer_observations} / {f.peer_universe}</td><td>{percent(f.share)}</td>
          <td className={f.contribution==null?undefined:f.contribution>0?s.positive:f.contribution<0?s.negative:undefined}>{f.contribution==null?"—":signed(f.contribution)}</td>
          <td>{statusText(f)}</td>
        </tr>)}</tbody></table>
    </div>
    {result.factors.some(f=>f.restricted) && <p className={s.note}>Licensed observations are included in derived scores. Raw values are withheld.</p>}
  </details>;
}
function AgentCard({result,comparison}:{result:AgentResult;comparison:boolean}) {
  return <article className={s.agent}>
    <div className={s.heading}><div><h3>{agentLabels[result.agent]}</h3>
      <span>{result.rank==null?"Unranked":"Rank "+result.rank+" of "+result.peers}</span></div>
      <div className={s.score}><strong>{score(result.score)}</strong><small>/ 100</small></div></div>
    <p className={s.reading}>{result.reading}</p>
    <dl className={s.stats}><div><dt>Scoreable factors</dt><dd>{result.observed} / {result.enabled}</dd></div>
      <div><dt>Composite weight</dt><dd>{percent(result.share)}</dd></div>
      <div><dt>Book status</dt><dd>{comparison?"Outside Nifty 500":bookName(result.selection)}</dd></div></dl>
    <div className={s.drivers}>
      <Evidence factor={result.factors.find(f=>f.key===result.strongest)} positive/>
      <Evidence factor={result.factors.find(f=>f.key===result.weakest)} positive={false}/>
    </div>
    {!result.passes_long_filters && <p className={s.filter}>Long-list filter failed.{result.agent==="sentiment"?" "+(result.headlines_7d==null?"No recorded headlines":number.format(result.headlines_7d)+" headlines")+" in seven days against a minimum of "+result.min_headlines+".":""}</p>}
    <FactorDetails result={result}/>
  </article>;
}

export function AgentAnalysis({ticker,settings,asof}:{ticker:string;settings?:Settings;asof?:string}) {
  const session = useSession();
  const path = "/ranker/stock/"+encodeURIComponent(ticker)+(asof?"?asof="+encodeURIComponent(asof):"");
  const report = useQuery({queryKey:["stock-agent-analysis",session.data?.id,ticker,settings??null,asof??null],enabled:!!session.data,
    queryFn:({signal})=>api<Result>(path,{method:"POST",body:JSON.stringify(settings??{}),signal})});
  const data = report.data;
  return <section className={s.section} aria-label="Four-agent analysis">
    <div className={s.intro}><h2>Four-agent analysis</h2>
      {data && <span>Ranking date {data.asof}{data.price_date?" · Market close "+data.price_date:""}</span>}</div>
    {session.isPending ? <State>Checking your session…</State> : session.isError ? <State error>Session unavailable.</State>
      : !session.data ? <SignInNotice next={"/stocks/"+encodeURIComponent(ticker)}>Sign in to view the four-agent analysis.</SignInNotice>
      : report.isError ? <State error>{report.error.message} <button className="text-link" onClick={()=>void report.refetch()}>Retry</button></State>
      : !data ? <State>Calculating agent evidence…</State>
      : !data.in_universe && !data.peer_comparison ? <State>{data.universe ? "No eligible directory or membership record was found for "+ticker+" on this date." : "Nifty 500 membership is unavailable for this date."}</State>
      : data.composite && <><div className={s.composite}><div className={s.compositeScore}><span>{data.peer_comparison?"Comparison score":"Composite score"}</span><strong>{score(data.composite.score)}<small> / 100</small></strong></div>
        <div className={s.verdict}><strong>{data.peer_comparison?"Outside the Nifty 500 portfolio":bookName(data.composite.selection)}</strong><span>
          {data.composite.rank==null?"Unranked":"Rank "+data.composite.rank+" of "+data.composite.peers} · {title(data.composite.mode)} · {data.sector}</span><p>{data.composite.reading}</p></div></div>
        {data.peer_comparison && <p className={s.note}>Comparison ranks place {ticker} alongside the {data.universe} recorded Nifty constituents. Only constituents are eligible for the candidate books.</p>}
        <div className={s.agents}>{data.agents?.map(a=><AgentCard key={a.agent} result={a} comparison={data.peer_comparison}/>)}</div></>}
  </section>;
}
