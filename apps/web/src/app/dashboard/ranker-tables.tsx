"use client";

import Link from "next/link";
import { agentLabels, agents, type Agent } from "@/lib/api";
import { columns, display, type Snapshot, type Tab } from "./ranker-model";
import s from "./ranker.module.css";

export function Heat({data,boost}:{data:Snapshot["heat"];boost:boolean}) {
  const width = Math.max(.001,...data.map(item=>Math.abs(item.value)));
  return <section className={s.card}><h2>Sector heat, 20-day return</h2>
    {data.length ? <div className={s.heat}>{data.map(({sector,value},i)=><div key={sector} className={s.heatRow}>
      <span>{sector}{boost && i<3?" ★":""}</span><span className={s.heatTrack}><i style={{left:value>=0?"50%":(50-50*Math.abs(value)/width)+"%",width:50*Math.abs(value)/width+"%",background:value>=0?"var(--rk-up)":"var(--rk-down)"}}/></span>
      <strong className={value>=0?s.up:s.down}>{display(value,"percent")}</strong></div>)}</div>
      : <p className={s.empty}>No sector-classified stocks have a 20-session return on this date.</p>}
    {boost && data.length>0 && <p className={s.hint}>★ The three strongest sectors receive a 10-point sentiment boost.</p>}
  </section>;
}
function Bars({values,short}:{values:Record<string,number>;short:boolean}) {
  return <span className={s.bars} aria-hidden="true">{agents.map(a=><i key={a}
    style={{height:values[a]==null?1:Math.max(2,values[a]*.23),background:short?"var(--rk-down)":"var(--rk-up)"}}/>)}</span>;
}
export function Candidates({tab,data,side,size}:{tab:Exclude<Tab,"portfolio">;data:Snapshot;side:"longs"|"shorts";size:number}) {
  const short = side==="shorts";
  const combined = tab==="combined";
  const names = data.books[tab][side];
  const fields = combined ? agents.map((a):[string,string]=>[a,agentLabels[a].slice(0,a==="technical"?4:3)]) : columns[tab as Agent];
  return <section className={s.card}><h2><i className={s.dot} style={{background:short?"var(--rk-down)":"var(--rk-up)"}}/>
    {short?"Short":"Long"} {combined?"list":"candidates, "+(short?"bottom ":"top ")+size}</h2>
    <div className={s.scroll} tabIndex={0} aria-label={(short?"Short":"Long")+" candidates"}><table className={combined?s.combined:undefined}>
      <thead><tr><th>#</th><th>Ticker</th><th>Sector</th>{fields.map(([key,label])=><th key={key}>{label}</th>)}{combined && <><th>Agents</th><th>Composite</th></>}</tr></thead>
      <tbody>{names.map((ticker,index)=>{
        const row = data.rows[ticker];
        return <tr key={ticker}><td>{index+1}</td><td><Link href={"/stocks/"+encodeURIComponent(ticker)}>{ticker}</Link></td>
          <td className={s.sector} title={row.sector}>{row.sector}</td>{fields.map(([key,,kind])=>{
            const val = row.values[key];
            return <td key={key} className={kind==="percent" && val!=null ? val<0?s.down:s.up:undefined}>{display(val,kind)}</td>;
          })}{combined && <><td><Bars values={row.values} short={short}/></td><td><span className={s.score}><i><b style={{width:row.values.composite+"%"}}/></i>{display(row.values.composite)}</span></td></>}
        </tr>;
      })}</tbody>
    </table></div>
    {!names.length && <p className={s.empty}>No {short?"short":"long"} candidates meet these settings with the available data.</p>}
  </section>;
}
