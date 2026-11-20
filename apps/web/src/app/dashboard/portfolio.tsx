"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { StockTicker } from "@/components/stock-ticker";
import Link from "next/link";
import { parseAsString, useQueryState } from "nuqs";
import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type JobRef, type JobStatus } from "@/lib/api";
import type { UniverseSelection } from "@/components/universe-filters";
import { Control } from "./ranker-controls";
import { type Settings } from "./ranker-model";
import s from "./ranker.module.css";

type Metrics = { annual_return:number; sharpe:number; sortino:number|null; max_drawdown:number; annual_vol:number;
  calmar:number|null; up_days:number; total_return:number };
type Report = Metrics & {benchmark:Metrics; start:string; end:string; beta:number|null; turnover:number; rebalances:number;
  settings:{selection?:UniverseSelection; universe:string; portfolio:string; cost_bps:number; rebalance:string}; equity_curve:{date:string; equity:number; benchmark:number}[];
  holdings_date?:string|null; holdings_last?:{ticker:string;side:"Long"|"Short";weight:number;composite:number|null}[];
  trades_latest?:{date:string;ticker:string;action:"Buy"|"Sell"|"Short"|"Cover";composite:number|null}[]};
const pct = (v:number) => (100*v).toFixed(1)+"%";
const number = (v:number) => v.toFixed(2);
const finish = (value?:string)=>["finished","failed","canceled","stopped"].includes(value??"");

function ReplayResults({result}:{result:Report}) {
  const holdings = result.holdings_last ?? [];
  const trades = result.trades_latest ?? [];
  let peak = 0;
  const curve = result.equity_curve.map(point => {
    peak = Math.max(peak, point.equity);
    return {...point, drawdown: peak ? point.equity / peak - 1 : 0};
  });
  const stats: [keyof Metrics,string,(v:number)=>string][] = [
    ["annual_return","CAGR",pct],["sharpe","Sharpe",number],["sortino","Sortino",number],
    ["max_drawdown","Max drawdown",pct],["annual_vol","Volatility",pct],["calmar","Calmar",number],["up_days","Up days",pct],
  ];
  return <>
    <p className={s.hint}>Report filters · {[result.settings.selection?.index_code || "NIFTY500", result.settings.selection?.cap ? result.settings.selection.cap+" cap" : "All sizes", result.settings.selection?.industry || "All industries", result.settings.selection?.fo_only ? "F&O eligible only" : "All F&O statuses"].join(" · ")}</p>
    <p className={s.summary}>Strategy returned <strong>{pct(result.total_return)}</strong> versus {pct(result.benchmark.total_return)} for the equal-weight benchmark from {result.start} to {result.end}.</p>
    <div className={s.metrics}>{stats.map(([key,label,fmt])=><div key={key}><small>{label}</small><strong>{result[key]==null?"—":fmt(result[key])}</strong>
      <small>Benchmark {result.benchmark[key]==null?"—":fmt(result.benchmark[key])}</small></div>)}
      <div><small>Beta / turnover</small><strong>{result.beta==null?"—":number(result.beta)} / {pct(result.turnover)}</strong><small>Per rebalance</small></div></div>
    <section className={s.card}><h2>Growth of ₹1</h2><div className={s.chart} role="img" aria-label="Growth of one rupee for the strategy and equal-weight benchmark">
      <ResponsiveContainer width="100%" height="100%" minWidth={0}><LineChart data={result.equity_curve} margin={{top:10,right:12,left:0,bottom:2}}>
        <CartesianGrid vertical={false} stroke="var(--line)"/><XAxis dataKey="date" minTickGap={70} tick={{fill:"var(--muted)",fontSize:11}}/>
        <YAxis domain={["auto","auto"]} width={54} tickFormatter={v=>"₹"+Number(v).toFixed(2)} tick={{fill:"var(--muted)",fontSize:11}}/>
        <Tooltip contentStyle={{background:"var(--panel)",borderColor:"var(--line)",color:"var(--ink)"}} formatter={v=>Number(v).toFixed(4)}/><Legend align="left" iconType="plainline" wrapperStyle={{fontSize:12}}/>
        <Line dataKey="equity" name="Strategy" stroke="var(--accent)" strokeWidth={2} dot={false} isAnimationActive={false}/>
        <Line dataKey="benchmark" name="Equal-weight benchmark" stroke="var(--bench)" strokeWidth={1.5} dot={false} isAnimationActive={false}/>
      </LineChart></ResponsiveContainer></div></section>
    <section className={s.card}><h2>Drawdown</h2><div className={s.chart} role="img" aria-label="Strategy drawdown from its previous peak">
      <ResponsiveContainer width="100%" height="100%" minWidth={0}><LineChart data={curve} margin={{top:10,right:12,left:0,bottom:2}}>
        <CartesianGrid vertical={false} stroke="var(--line)"/><XAxis dataKey="date" minTickGap={70} tick={{fill:"var(--muted)",fontSize:11}}/>
        <YAxis domain={["auto",0]} width={54} tickFormatter={v=>pct(Number(v))} tick={{fill:"var(--muted)",fontSize:11}}/>
        <Tooltip contentStyle={{background:"var(--panel)",borderColor:"var(--line)",color:"var(--ink)"}} formatter={v=>pct(Number(v))}/>
        <Line dataKey="drawdown" name="Drawdown" stroke="var(--short)" strokeWidth={1.5} dot={false} isAnimationActive={false}/>
      </LineChart></ResponsiveContainer></div></section>
    <div className={s.books}>
      <section className={s.card}><h2>Holdings after last rebalance{result.holdings_date ? ", "+result.holdings_date : ""}</h2>
        <div className={s.scroll}><table><thead><tr><th>#</th><th>Ticker</th><th>Side</th><th>Weight</th><th>Composite</th></tr></thead>
          <tbody>{holdings.map((row,index)=><tr key={row.ticker}><td>{index+1}</td><td><StockTicker ticker={row.ticker}/></td>
            <td className={row.side==="Long"?s.up:s.down}>{row.side}</td><td>{pct(row.weight)}</td><td>{row.composite==null?"—":<span className={s.score}><i><b style={{width:row.composite+"%"}}/></i>{row.composite.toFixed(0)}</span>}</td></tr>)}
          </tbody></table>{!holdings.length&&<p className={s.empty}>Holdings are unavailable for this report.</p>}</div></section>
      <section className={s.card}><h2>Trade log, latest 40</h2>
        <div className={s.scroll}><table><thead><tr><th>Date</th><th>Ticker</th><th>Action</th><th>Composite</th></tr></thead>
          <tbody>{trades.map((row,index)=><tr key={row.date+row.ticker+row.action+index}><td>{row.date}</td><td><StockTicker ticker={row.ticker}/></td>
            <td className={row.action==="Buy"||row.action==="Cover"?s.up:s.down}>{row.action}</td><td>{row.composite==null?"—":row.composite.toFixed(0)}</td></tr>)}</tbody></table>
          {!trades.length&&<p className={s.empty}>Trades are unavailable for this report.</p>}</div></section>
    </div>
    <p className={s.hint}>{result.settings.universe==="current_cohort"?"Current-cohort retrospective · Uses end-date constituents, classifications and revised adjusted prices. Survivorship bias applies.":"Historical membership · Signals use observations known on each rebalance date."} {result.rebalances} rebalances · {result.settings.cost_bps} bps per side.</p>
  </>;
}
export function Portfolio({selection,config,end,admin,user}:{selection:UniverseSelection;config:Settings;end:string;admin:boolean;user:string}) {
  const [job,setJob] = useQueryState("replay",parseAsString);
  const [months,setMonths] = useState(12);
  const [freq,setFreq] = useState("monthly");
  const [portfolio,setPortfolio] = useState("long_short");
  const [universe,setUniverse] = useState("current_cohort");
  const [weighting,setWeighting] = useState("equal");
  const [cost,setCost] = useState(10);
  const latest = useQuery({queryKey:["ranker-report",user],queryFn:({signal})=>api<Report|{note:string}>("/ranker/latest",{signal}),enabled:!job});
  const task = useQuery({queryKey:["ranker-job",user,job],queryFn:({signal})=>api<JobStatus>("/jobs/"+encodeURIComponent(job!),{signal}),
    enabled:!!job, refetchInterval:q=>q.state.error||finish(q.state.data?.status)?false:1800});
  const run = useMutation({mutationFn:()=>api<JobRef>("/ranker/backtest",{method:"POST",body:JSON.stringify({selection,end,months,rebalance:freq,portfolio,universe,weighting,cost_bps:cost,settings:config})}),
    onSuccess:v=>void setJob(v.job_id)});
  const busy = !!job && !task.isError && !finish(task.data?.status);
  const result = job ? task.data?.result as Report|null : latest.data && "benchmark" in latest.data ? latest.data : null;
  return <div className={s.grid}><aside className={s.panel}><h2>Portfolio and backtest</h2>
    <p className={s.hint}>Replay the settings from all four agents on each rebalance date.</p>
    <Control label="Period"><select value={months} onChange={e=>setMonths(Number(e.target.value))}>{[[3,"3 months"],[6,"6 months"],[12,"1 year"],[24,"2 years"],[36,"3 years"]].map(([v,label])=><option key={v} value={v}>{label}</option>)}</select></Control>
    <Control label="Membership"><select value={universe} onChange={e=>setUniverse(e.target.value)}><option value="current_cohort">Current cohort</option><option value="historical">Historical (PIT)</option></select></Control>
    <Control label="Rebalance"><select value={freq} onChange={e=>setFreq(e.target.value)}><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select></Control>
    <Control label="Portfolio"><select value={portfolio} onChange={e=>setPortfolio(e.target.value)}><option value="long_short">Long/short, neutral</option><option value="long_only">Long only</option><option value="130_30">130/30</option></select></Control>
    <Control label="Weighting"><select value={weighting} onChange={e=>setWeighting(e.target.value)}><option value="equal">Equal weight</option><option value="score">Score weight</option><option value="inverse_vol">Inverse volatility</option></select></Control>
    <Control label="Cost per side (bps)"><input type="number" min={0} max={200} value={cost} onChange={e=>setCost(Math.max(0,Math.min(200,Number(e.target.value))))}/></Control>
    <button className={s.primary} onClick={()=>run.mutate()} disabled={!admin||busy||run.isPending}>{busy?"Backtest running…":run.isPending?"Submitting…":"Run backtest"}</button>
    {!admin && <p className={s.hint}>Administrators can start a run.</p>}
    <p className={s.hint}>{universe==="current_cohort"?"Uses end-date constituents, sectors and revised price history. Results include survivorship bias.":"Uses membership and signals known on each ranking date."} Trades at the next close. Shorts accrue 0.5% annual borrow.</p>
    <Link className={s.link} href="/backtest">Backtest archive ↗</Link>
    </aside><section className={s.results} aria-live="polite">
      {run.isError && <p className={s.error}>{run.error.message}</p>}
      {job && <div className={s.status}>Backtest {task.data?.status||"queued"}<button onClick={()=>{void setJob(null);void latest.refetch();}}>Latest completed report</button></div>}
      {busy ? <div className={s.card}><h2>Calculating portfolio returns</h2><p className={s.hint}>The worker is replaying the ranking settings against stored market sessions.</p></div>
        : task.isError || (!job && latest.isError) ? <p className={s.error}>{(task.error ?? latest.error)?.message}</p>
        : job && task.data?.status!=="finished" ? <p className={s.error}>{task.data?.error??"The job ended before producing a report."}</p>
        : result && result.benchmark ? <ReplayResults result={result}/>
        : <div className={s.card}><h2>Portfolio results</h2><p className={s.hint}>{!job && latest.isPending?"Loading the latest report…":"Run a backtest to compare the strategy with its equal-weight benchmark."}</p></div>}
    </section></div>;
}

