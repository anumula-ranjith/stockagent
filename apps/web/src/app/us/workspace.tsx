"use client";
import {useState} from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import {useQuery,useMutation,useQueryClient} from "@tanstack/react-query";
import {useSession} from "@/components/providers";
import {SignInNotice,State} from "@/components/presentation";
import {api,type PriceBar} from "@/lib/api";
import {standardPeriods,standardRules} from "@/lib/stock-context";
import {useUsTrades} from "./use-us-trades";

const Chart=dynamic(()=>import("@/components/price-chart"),{ssr:false});
const usd=new Intl.NumberFormat("en-US",{style:"currency",currency:"USD"});
const et=new Intl.DateTimeFormat("en-US",{timeZone:"America/New_York",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",second:"2-digit",timeZoneName:"short"});
const fmt=(n:number|null|undefined,digits=2)=>n==null?"—":n.toLocaleString("en-US",{maximumFractionDigits:digits});
type Listing={ticker:string;name:string;kind:string;exchange:string;date:string;close:number;volume:number|null;cap:number|null;intraday:number|null;below:number|null;above:number|null};
type Article={url:string;title:string;date:string};
type Contract={symbol:string;strike:number;side:string;oi:number|null;oi_date:string|null;iv:number|null;greeks:Record<string,number>};
type Follow={saved:string[];toggle:(symbol:string)=>void;busy:boolean};
const labels:Record<string,string>={dashboard:"US market overview",stocks:"US stocks",screener:"US stock screener",watchlist:"My US watchlist",news:"US market news"};
function FollowButton({ticker,follow}:{ticker:string;follow:Follow}){
  const followed=follow.saved.includes(ticker);
  return <button className="button button-secondary" aria-pressed={followed} aria-label={(followed?"Remove ":"Watch ")+ticker} disabled={follow.busy}
    onClick={()=>follow.toggle(ticker)}>{followed?"Watching":"+ Watch"}</button>;
}
function News({ticker}:{ticker?:string}){
  const q=useQuery({queryKey:["us-news",ticker],queryFn:({signal})=>api<Article[]>(ticker?"/us/stock/"+ticker+"/news":"/us/news",{signal}),staleTime:600000});
  return <section className="surface"><div className="surface-top"><h2 className="section-title">{ticker?ticker+" headlines":"S&P 500 ETF headlines"}</h2><small>EODHD · {ticker??"SPY"}</small></div>
    {q.isError?<State error>{q.error.message}</State>:!q.data?<State>Loading headlines…</State>:!q.data.length?<State>No recent headlines.</State>:
      <ul className="us-news">{q.data.map((item,i)=><li key={item.url+i}><small>{et.format(new Date(item.date))}</small><a href={item.url} target="_blank" rel="noopener noreferrer">{item.title}</a></li>)}</ul>}</section>;
}
function Options({ticker}:{ticker:string}){
  const [opened,setOpened]=useState(false);
  const q=useQuery({queryKey:["us-options",ticker],enabled:opened,queryFn:({signal})=>api<{expiry:string|null;rows:Contract[]}>("/us/stock/"+ticker+"/options",{signal}),staleTime:600000});
  const rows=q.data?.rows??[];
  const oiDates=new Set(rows.map(r=>r.oi_date));
  const comparable=rows.length>0 && rows.every(r=>r.oi!=null) && oiDates.size===1 && !oiDates.has(null);
  const interest=(side:string)=>rows.reduce((total,r)=>total+(r.side===side?(r.oi??0):0),0);
  const calls=interest("call");
  return <section className="surface"><div className="surface-top"><h2 className="section-title">Options chain</h2><button className="button button-secondary" onClick={()=>setOpened(!opened)}>{opened?"Hide contracts":"View contracts"}</button></div>
    {opened && (q.isError?<State error>{q.error.message}</State>:!q.data?<State>Loading contracts…</State>:!rows.length?<State>No listed options in the next 60 days.</State>:<>
      <div className="surface-top"><span>Expiry {q.data.expiry} · {rows.length} contracts</span><small>Indicative feed · Put/call OI ratio {comparable&&calls?fmt(interest("put")/calls):"—"}</small></div>
      <div className="table-scroll"><table><thead><tr>{["Strike","Type","Open interest","OI date","IV %","Delta","Gamma","Theta","Vega"].map(x=><th key={x}>{x}</th>)}</tr></thead>
      <tbody>{rows.map(r=><tr key={r.symbol}><td>{usd.format(r.strike)}</td><td>{r.side}</td><td>{fmt(r.oi,0)}</td><td>{r.oi_date??"—"}</td><td>{fmt(r.iv==null?null:100*r.iv)}</td>{["delta","gamma","theta","vega"].map(k=><td key={k}>{fmt(r.greeks[k],4)}</td>)}</tr>)}</tbody></table></div></>)}</section>;
}
function Stock({ticker,row,follow}:{ticker:string;row?:Listing;follow:Follow}){
  const [days,setDays]=useState(365);
  const [periods,setPeriods]=useState(standardPeriods);
  const q=useQuery({queryKey:["us-bars",ticker],queryFn:({signal})=>api<PriceBar[]>("/us/stock/"+ticker+"/candles",{signal}),staleTime:900000});
  const live=useUsTrades([ticker],true);
  const trade=live.prices[ticker];
  const last=q.data?.at(-1);
  return <><div><p className="eyebrow">{row?.exchange??"US equity"} · USD</p><h1>{ticker}</h1><p>{row?.name}</p></div>
    <section className="surface"><div className="surface-top"><div><h2 className="section-title">Price history</h2><small>EODHD daily candles · {last?.date??"Loading"}</small></div>
      <div className="us-tabs">{[[90,"3M"],[365,"1Y"],[1096,"3Y"]].map(([n,l])=><button key={n} aria-pressed={days===n} onClick={()=>setDays(Number(n))}>{l}</button>)}</div></div>
      <div className="chart-pad">{q.isError?<State error>{q.error.message}</State>:q.data?<Chart currency="USD" prices={q.data} periods={periods} rules={standardRules} days={days}/>:<State>Loading US daily candles…</State>}</div>
      <div className="us-toolbar">{(["ema_fast","ema_slow","macd_fast","macd_slow","macd_signal"] as const).map(k=><label key={k} className="field">{k.replace("_"," ").toUpperCase()}<input type="number" min={1} max={250} value={periods[k]} onChange={e=>{const n=e.target.valueAsNumber;if(Number.isInteger(n)&&n>=1&&n<=250)setPeriods({...periods,[k]:n});}}/></label>)}</div>
    </section>
    <div className="surface surface-top"><div><h2 className="section-title">Latest IEX trade · {trade?usd.format(trade.price):"—"}</h2><small>{trade?et.format(new Date(trade.time))+" · ":""}{live.mode}</small></div><FollowButton ticker={ticker} follow={follow}/></div>
    <div className="metrics">{[["Last close",last?.close==null?"—":usd.format(last.close)],["Volume",fmt(last?.volume,0)],["Below 250-session high",row?.below==null?"—":fmt(row.below)+"%"],["Above 250-session low",row?.above==null?"—":fmt(row.above)+"%"]].map(([k,v])=><div className="metric" key={k}><span>{k}</span><strong>{v}</strong></div>)}</div>
    <Options ticker={ticker}/><News ticker={ticker}/></>;
}
function Directory({rows,page,follow}:{rows:Listing[];page:string;follow:Follow}){
  const [search,setSearch]=useState(""),[exchange,setExchange]=useState(""),[kind,setKind]=useState(""),[high,setHigh]=useState(""),[low,setLow]=useState(""),[offset,setOffset]=useState(0);
  const watch=page==="watchlist",screen=page==="screener",home=page==="dashboard";
  const term=search.trim().toUpperCase();
  const asof=rows.reduce((d,r)=>r.date>d?r.date:d,"");
  const universe=home?rows.filter(r=>r.date===asof&&r.kind==="Common Stock"):rows;
  const matching=universe.filter(r=>(!watch||follow.saved.includes(r.ticker))&&(!exchange||r.exchange===exchange)&&(!kind||r.kind===kind)&&
    (!term||r.ticker.includes(term)||r.name.toUpperCase().includes(term))&&(!screen||((!high||(r.below!=null&&r.below<=Number(high)))&&(!low||(r.above!=null&&r.above<=Number(low))))));
  const visible=matching.slice(offset,offset+(home?12:25));
  const live=useUsTrades(visible.map(r=>r.ticker),watch&&visible.length>0);
  return <>{home&&<div className="us-quotes">{["SPY","QQQ","DIA","IWM"].map(t=>rows.find(r=>r.ticker===t)).filter((r):r is Listing=>!!r).map(r=><Link className="surface" key={r.ticker} href={"/us/stocks/"+r.ticker}><small>{r.name}</small><b>{r.ticker}</b><strong>{usd.format(r.close)}</strong><small>Close · {r.date}</small></Link>)}</div>}
    <section className="surface"><div className="surface-top"><h2 className="section-title">{home?"Largest companies by market cap":watch?"Saved stocks":screen?"Screen results":"Stock directory"}</h2><small>{matching.length.toLocaleString()} listings · {watch?live.mode:"EODHD · USD"}</small></div>
    {!home&&<div className="us-toolbar" onChange={()=>setOffset(0)}><label className="field">Search<input type="search" placeholder="Ticker or company" value={search} onChange={e=>setSearch(e.target.value)}/></label>
      <label className="field">Exchange<select value={exchange} onChange={e=>setExchange(e.target.value)}><option value="">All exchanges</option>{Array.from(new Set(rows.map(r=>r.exchange))).sort().map(x=><option key={x}>{x}</option>)}</select></label>
      <label className="field">Instrument<select value={kind} onChange={e=>setKind(e.target.value)}><option value="">Stocks and ETFs</option><option>Common Stock</option><option>ETF</option></select></label>
      {screen&&<>{[["Max % below 250-session high",high,setHigh],["Max % above 250-session low",low,setLow]].map(([label,val,set])=><label className="field" key={String(label)}>{String(label)}<input type="number" min={0} step="any" value={String(val)} placeholder="Any" onChange={e=>(set as typeof setHigh)(e.target.value)}/></label>)}</>}
    </div>}
    <div className="table-scroll"><table><thead><tr>{["Ticker","Company","Exchange",...(watch?["Latest IEX trade"]:[]),"Close","Session","Open to close","Volume","Market cap",...(screen?["Below high","Above low"]:[]),"Watch"].map(x=><th key={x}>{x}</th>)}</tr></thead>
    <tbody>{visible.map(r=><tr key={r.ticker}><td><Link className="text-link" href={"/us/stocks/"+r.ticker}>{r.ticker}</Link></td><td>{r.name}</td><td>{r.exchange}</td>
    {watch&&<td>{live.prices[r.ticker]?<>{usd.format(live.prices[r.ticker].price)}<br/><small>{et.format(new Date(live.prices[r.ticker].time))}</small></>:"—"}</td>}
    <td>{usd.format(r.close)}</td><td>{r.date}</td><td>{r.intraday==null?"—":fmt(r.intraday)+"%"}</td><td>{fmt(r.volume,0)}</td><td>{r.cap==null?"—":"$"+Intl.NumberFormat("en-US",{notation:"compact"}).format(r.cap)}</td>
    {screen&&<><td>{fmt(r.below)}%</td><td>{fmt(r.above)}%</td></>}<td><FollowButton ticker={r.ticker} follow={follow}/></td></tr>)}</tbody></table></div>
    {!visible.length&&<State>{watch&&!follow.saved.length?"Use + Watch beside a US ticker to add it here.":"No matching listings."}</State>}
    {!home&&<div className="surface-top"><button disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-25))}>Previous</button><small>{matching.length?offset+1:0}–{Math.min(offset+25,matching.length)} of {matching.length}</small><button disabled={offset+25>=matching.length} onClick={()=>setOffset(offset+25)}>Next</button></div>}</section>
    {home&&<News/>}</>;
}
export function UsWorkspace({page,ticker}:{page:string;ticker?:string}){
  const session=useSession(),client=useQueryClient(),id=session.data?.id;
  const market=useQuery({queryKey:["us-market",id],enabled:!!id&&page!=="news",queryFn:({signal})=>api<Listing[]>("/us/market",{signal}),staleTime:1800000});
  const saved=useQuery({queryKey:["us-watch",id],enabled:!!id,queryFn:({signal})=>api<string[]>("/us/watchlist",{signal})});
  const change=useMutation({mutationFn:(t:string)=>api("/us/watchlist/"+t,{method:saved.data?.includes(t)?"DELETE":"PUT"}),onSuccess:()=>client.invalidateQueries({queryKey:["us-watch",id]})});
  const follow={saved:saved.data??[],toggle:change.mutate,busy:change.isPending||!saved.data};
  const path=ticker?"/us/stocks/"+ticker:page==="dashboard"?"/us":"/us/"+page;
  return <div className="shell workspace us-board">{!ticker&&<div><p className="eyebrow">United States · Equities</p><h1>{labels[page]}</h1></div>}
  {session.isPending?<State>Checking account…</State>:!id?<SignInNotice next={path}>Sign in to view US market data.</SignInNotice>:<>
  {(change.isError||saved.isError)&&<State error>{change.error?.message??saved.error?.message}</State>}
  {ticker?<Stock key={ticker} ticker={ticker} row={market.data?.find(r=>r.ticker===ticker)} follow={follow}/>:page==="news"?<News/>:
  market.isError?<State error>{market.error.message}</State>:!market.data?<State>Loading US listings and end-of-day prices…</State>:<Directory key={page} rows={market.data} page={page} follow={follow}/>}</>}</div>;
}
