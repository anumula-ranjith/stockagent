"use client";
import {useQuery} from "@tanstack/react-query";
import {api} from "@/lib/api";
import {useMarketPrices} from "@/lib/use-market-prices";
import {inr} from "@/lib/personal-types";

export type Quote = {price:number; time:string|null};
type Greek = {strikePrice:string;optionType:string;delta:string;gamma:string;theta:string;vega:string;impliedVolatility:string};
type Chain = {contract:string|null; expiry:string; oi:number|null; pcr:number|null; buildup:string|null; greeks:Greek[]; unavailable:string[]};

export function LatestQuote({ticker}:{ticker:string}) {
  const feed=useMarketPrices(ticker,ticker,"subscribe");
  const price=feed.quotes[ticker];
  return <p className="subtle">{price && <strong>{inr.format(price.price)} · {price.time} IST · {price.source==="tick"?"Tick":"Snapshot"} </strong>}{feed.status}</p>;
}

export function Derivatives({ticker}:{ticker:string}) {
  const query=useQuery({queryKey:["angel-derivatives",ticker],queryFn:({signal})=>api<Chain>("/market-feed/stock/"+encodeURIComponent(ticker)+"/derivatives",{signal}),staleTime:300000});
  const chain=query.data;
  return <section className="surface" id="derivatives"><div className="surface-top"><h2 className="section-title">Derivatives · {ticker}</h2></div>
    <div className="chart-pad">{query.isPending ? <p>Loading Angel One derivatives…</p> : query.isError ? <p>{query.error.message}</p> : !chain?.contract ? <p>No supported NSE futures contract found.</p> : <>
      <p>{chain.contract} · Expires {chain.expiry}</p>
      <dl className="metrics">{[["Futures open interest",chain.oi?.toLocaleString("en-IN")],["Put/call ratio",chain.pcr],["OI buildup",chain.buildup??"No matching report entry"]].map(([label,value])=><div className="metric" key={label}><dt>{label}</dt><dd>{value??"Unavailable"}</dd></div>)}</dl>
      {!!chain.unavailable.length && <p className="subtle">Unavailable · {chain.unavailable.join(", ")}</p>}
      <details><summary>Option Greeks · {chain.greeks.length} contracts</summary>
        {chain.greeks.length>0 && <div className="table-scroll"><table><thead><tr>{["Strike ₹","Type","Delta","Gamma","Theta","Vega","IV %"].map(x=><th key={x}>{x}</th>)}</tr></thead>
          <tbody>{[...chain.greeks].sort((a,b)=>Number(a.strikePrice)-Number(b.strikePrice)||a.optionType.localeCompare(b.optionType)).map(row=><tr key={row.strikePrice+row.optionType}>{[Number(row.strikePrice),row.optionType,row.delta,row.gamma,row.theta,row.vega,row.impliedVolatility].map((v,i)=><td key={i}>{v??"—"}</td>)}</tr>)}</tbody></table></div>}
      </details></>}</div></section>;
}
