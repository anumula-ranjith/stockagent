"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { StockTicker } from "@/components/stock-ticker";
import type { UniverseSelection } from "@/components/universe-filters";
import { api } from "@/lib/api";
import { dateLabel, rupees } from "@/lib/utils";
import { Control } from "./ranker-controls";
import type { Settings, Snapshot } from "./ranker-model";
import s from "./ranker.module.css";

type Config = { settings: Settings; selection: UniverseSelection };
type Batch = {signal_date:string; origin:string; selection:UniverseSelection; longs:number; shorts:number};
type History = {schedule:Config|null; days:Batch[]};
type Position = {ticker:string; side:"Long"|"Short"; entry:number|null; mark:number|null; basis:string; return_value:number|null};
type Report = {entry_date:string|null; mark_date:string|null; priced:number; basket_return:number|null; positions:Position[]};
const endpoint = "/ranker/daily-picks";
const pct = (n:number|null) => n==null ? "—" : (n>0?"+":"")+(n*100).toFixed(2)+"%";
const price = (n:number|null) => n==null ? "—" : rupees.format(n);
function filters(v:UniverseSelection) {
  return [v.index_code, v.cap && v.cap+" cap", v.industry, v.fo_only && "F&O only"].filter(Boolean).join(" · ");
}

function Results({batch,user}:{batch:Batch;user:string}) {
  const [draft,setDraft] = useState("");
  const [through,setThrough] = useState("");
  const report = useQuery({queryKey:["daily-performance",user,batch.signal_date,through],
    queryFn:({signal})=>api<Report>(endpoint+"/"+batch.signal_date+(through?"?through="+through:""),{signal}),
    refetchInterval:through?false:60_000});
  const data = report.data;
  return <section className={s.card}><h2>Performance since the next close</h2>
    <div className={s.panel}>
      <p>{dateLabel(batch.signal_date)} · {filters(batch.selection)} · {batch.origin==="manual"?"Manually added":"Automatically added"}</p>
      <form onSubmit={e=>{e.preventDefault();if(draft===through) void report.refetch();else setThrough(draft);}}>
        <Control label="Test through"><input type="date" min={batch.signal_date} max={new Date().toLocaleDateString("en-CA")}
          value={draft} onChange={e=>setDraft(e.target.value)}/></Control>
        <button className={s.primary} disabled={report.isFetching}>Run backtest</button>
      </form>
      {report.isError ? <p role="alert" className={s.error}>{report.error.message}</p> : !data ? <p role="status">Loading closing prices…</p> :
        <><p>Entry close <strong>{data.entry_date?dateLabel(data.entry_date):"Pending"}</strong> · Valuation close <strong>{data.mark_date?dateLabel(data.mark_date):"Pending"}</strong></p>
          <p>Equal-weight return <strong>{pct(data.basket_return)}</strong> · {data.priced}/{data.positions.length} priced · {data.positions.filter(p=>(p.return_value??0)>0).length} profitable</p>
          {!data.entry_date && <p className={s.hint}>Returns appear when the next trading session’s closing prices arrive.</p>}
        </>}
    </div>
    {data && <div className={s.scroll}><table><thead><tr>{["Ticker","Side","Entry close","Valuation close","Price basis","Return"].map(h=><th key={h}>{h}</th>)}</tr></thead>
      <tbody>{data.positions.map(p=><tr key={p.ticker}><td><StockTicker ticker={p.ticker}/></td><td>{p.side}</td><td>{price(p.entry)}</td>
        <td>{price(p.mark)}</td><td>{p.basis}</td><td className={p.return_value==null || p.return_value===0?undefined:p.return_value>0?s.up:s.down}>{pct(p.return_value)}</td></tr>)}</tbody></table></div>}
    <p className={s.empty}>Each pick has equal starting weight. Falling prices benefit shorts. Returns exclude costs and borrow fees. Adjusted prices are used when available at both closes. Raw-close returns can reflect corporate actions.</p>
  </section>;
}

export default function DailyPortfolio({user,config,selection,snapshot,updating,rankingError}:{
  user:string;config:Settings;selection:UniverseSelection;snapshot?:Snapshot;updating:boolean;rankingError?:string;
}) {
  const cache = useQueryClient();
  const key = ["daily-picks",user];
  const [selected,setSelected] = useState("");
  const [message,setMessage] = useState("");
  const history = useQuery({queryKey:key,queryFn:({signal})=>api<History>(endpoint,{signal}),refetchInterval:60_000});
  const days = history.data?.days ?? [];
  const batch = days.find(d=>d.signal_date===selected) ?? days[0];
  const book = snapshot?.books.combined;
  const count = book ? book.longs.length+book.shorts.length : 0;
  const saved = days.some(d=>d.signal_date===snapshot?.asof);
  const schedule = history.data?.schedule;
  const action = useMutation({
    mutationFn: async (kind:"save"|"enable"|"disable")=>{
      if(kind==="save" && snapshot) {
        const result = await api<{added:boolean;signal_date:string}>(endpoint,{method:"POST",
          body:JSON.stringify({signal_date:snapshot.asof,selection,settings:config,book})});
        setSelected(result.signal_date);
        return result.added?"Added all picks for "+result.signal_date+".":"This session is already in your portfolio.";
      }
      await api(endpoint+"/schedule",kind==="disable"?{method:"DELETE"}:{method:"PUT",body:JSON.stringify({settings:config,selection})});
      return kind==="disable"?"Automatic saves paused.":"Automatic saves enabled with the current rankings settings.";
    },
    onMutate:()=>setMessage(""),
    onSuccess:async note=>{setMessage(note);await cache.invalidateQueries({queryKey:key});},
  });
  return <div className={s.grid}><aside className={s.panel}><h2>Daily paper portfolio</h2>
    {rankingError && <p className={s.error} role="alert">{rankingError}</p>}
    <p>{snapshot ? dateLabel(snapshot.asof)+" · "+filters(selection) : "Loading Combined rankings…"}</p>
    <p>{book ? book.longs.length+" long · "+book.shorts.length+" short" : ""}</p>
    <button className={s.primary} disabled={!count||saved||updating||!!rankingError||action.isPending||!history.data||snapshot?.price_date!==snapshot?.asof}
      onClick={()=>action.mutate("save")}>{saved?"Already added for this date":"Add all "+(count||"")+" picks to portfolio"}</button>
    {snapshot && snapshot.price_date!==snapshot.asof && <p className={s.hint}>Choose a ranking date with a recorded trading close.</p>}
    <h2>After-close saves</h2>
    <p>{schedule?"On · "+filters(schedule.selection):"Off"} · 6:30 pm IST</p>
    <p className={s.hint}>Save one Combined basket per trading date. The first save keeps that day’s picks.</p>
    <button className={s.primary} disabled={!history.data||action.isPending||updating} onClick={()=>action.mutate("enable")}>
      {schedule?"Use current settings for future saves":"Enable daily saves"}</button>
    {schedule && <button className={s.link} disabled={action.isPending} onClick={()=>action.mutate("disable")}>Pause daily saves</button>}
    {action.isError && <p role="alert" className={s.error}>{action.error.message}</p>}
    {message && <p role="status">{message}</p>}
  </aside><div className={s.results}>
    {history.isError ? <p role="alert" className={s.error}>{history.error.message}</p> : !history.data ? <p>Loading daily portfolio…</p> :
      batch ? <><Control label="Saved ranking date"><select value={batch.signal_date} onChange={e=>setSelected(e.target.value)}>
        {days.map(d=><option key={d.signal_date} value={d.signal_date}>{dateLabel(d.signal_date)} · {d.longs} long / {d.shorts} short</option>)}
      </select></Control><Results key={batch.signal_date} batch={batch} user={user}/></> :
      <section className={s.card}><h2>No saved baskets yet</h2><p className={s.empty}>Add the current Combined picks or enable daily saves to start tracking performance.</p></section>}
  </div></div>;
}
