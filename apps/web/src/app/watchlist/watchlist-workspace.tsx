"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { SignInNotice, State } from "@/components/presentation";
import { useSession } from "@/components/providers";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { csvDownload, inr, type WatchItem, type WatchlistDetail, type WatchlistRow } from "@/lib/personal-types";
import s from "../portfolio/workspace.module.css";

export function WatchlistWorkspace() {
  const session = useSession();
  const client = useQueryClient();
  const [selected, setSelected] = useState("");
  const [name, setName] = useState("");
  const [ticker, setTicker] = useState("");
  const [note, setNote] = useState("");
  const [above, setAbove] = useState("");
  const [below, setBelow] = useState("");
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState("");
  useEffect(()=>{setTicker(new URLSearchParams(location.search).get("add")?.toUpperCase()??"");},[]);
  const lists = useQuery({queryKey:["my-watchlists",session.data?.id],enabled:!!session.data,
    queryFn:({signal})=>api<WatchlistRow[]>("/watchlists",{signal})});
  useEffect(()=>{if(lists.data?.length&&!selected)setSelected(lists.data[0].id);},[lists.data,selected]);
  const detail = useQuery({queryKey:["watchlist-detail",selected,session.data?.id],enabled:!!session.data&&!!selected,
    queryFn:({signal})=>api<WatchlistDetail>(`/watchlists/${selected}`,{signal})});
  const refresh = () => {void client.invalidateQueries({queryKey:["my-watchlists"]});void client.invalidateQueries({queryKey:["watchlist-detail"]});};
  const create = useMutation({mutationFn:()=>api<WatchlistRow>("/watchlists",{method:"POST",body:JSON.stringify({name})}),
    onSuccess:row=>{setSelected(row.id);setName("");refresh();}});
  const save = useMutation({mutationFn:()=>api<WatchItem>(`/watchlists/${selected}/items/${encodeURIComponent(ticker.trim().toUpperCase())}`,
    {method:"PUT",body:JSON.stringify({note:note||null,target_above:above||null,target_below:below||null})}),
    onSuccess:()=>{setTicker("");setNote("");setAbove("");setBelow("");setEditing("");refresh();}});
  const remove = useMutation({mutationFn:(item:string)=>api(`/watchlists/${selected}/items/${encodeURIComponent(item)}`,{method:"DELETE"}),onSuccess:refresh});
  const rename = useMutation({mutationFn:(next:string)=>api(`/watchlists/${selected}`,{method:"PATCH",body:JSON.stringify({name:next})}),onSuccess:refresh});
  const erase = useMutation({mutationFn:()=>api(`/watchlists/${selected}`,{method:"DELETE"}),onSuccess:()=>{setSelected("");refresh();}});
  function edit(item:WatchItem) {setTicker(item.ticker);setNote(item.note??"");setAbove(item.target_above?.toString()??"");setBelow(item.target_below?.toString()??"");setEditing(item.ticker);}
  function submit(event:FormEvent) {event.preventDefault();save.mutate();}
  const items = detail.data?.items.filter(item=>item.ticker.includes(search.trim().toUpperCase())||item.note?.toLowerCase().includes(search.trim().toLowerCase()))??[];
  if(session.isPending)return <State>Checking your account…</State>;
  if(!session.data)return <SignInNotice next="/watchlist">Your watchlists and research notes are private to your account.</SignInNotice>;
  return <div className={s.layout}>
    <aside className={`surface ${s.sidebar}`}><div className="surface-top"><h2 className="section-title">Lists</h2><span className="subtle">{lists.data?.length??0}</span></div>
      <div className={s.sidebarBody}>
        {lists.isError&&<State error>{lists.error.message}</State>}
        <div className={s.list}>{lists.data?.map(row=><button key={row.id} className={selected===row.id?s.selected:""} onClick={()=>{setSelected(row.id);setEditing("");}}>
          <strong>{row.name}</strong><small>{row.item_count} stocks</small></button>)}</div>
        <form className={s.form} onSubmit={event=>{event.preventDefault();create.mutate();}}><h3>New watchlist</h3>
          <label className="field">Name<input required maxLength={80} placeholder="Breakout candidates" value={name} onChange={e=>setName(e.target.value)}/></label>
          <Button disabled={create.isPending} type="submit"><Plus size={16}/>Create list</Button>
          {create.isError&&<p className={s.error} role="alert">{create.error.message}</p>}</form>
      </div></aside>
    <div className={s.main}>
      {!selected?<div className="surface"><State>Create a watchlist to organize the stocks you follow.</State></div>
        :detail.isError?<div className="surface"><State error>{detail.error.message}</State></div>
        :!detail.data?<div className="surface"><State>Loading watchlist…</State></div>:<>
        <div className="surface-top surface"><div><h2 className="section-title">{detail.data.name}</h2><p className="subtle">{detail.data.items.length} {detail.data.items.length===1?"stock":"stocks"} · latest stored NSE closes</p></div>
          <div className={s.actions}><Button variant="ghost" disabled={rename.isPending} onClick={()=>{const next=prompt("Watchlist name",detail.data!.name);if(next?.trim()&&next.trim()!==detail.data!.name)rename.mutate(next.trim());}}>Rename</Button>
            <Button variant="secondary" onClick={()=>csvDownload(`${detail.data!.name.replace(/[^a-z0-9-]/gi,"_")}-watchlist.csv`,
            [["Ticker","Last close","Price date","Change %","Alert above","Alert below","Note"],...detail.data!.items.map(item=>[
              item.ticker,item.close,item.price_date,item.change_pct,item.target_above,item.target_below,item.note])])}><Download size={15}/>Export CSV</Button>
            <Button variant="ghost" disabled={erase.isPending} onClick={()=>{if(confirm(`Delete watchlist “${detail.data!.name}” and its notes?`))erase.mutate();}}>
              <Trash2 size={15}/>Delete list</Button></div></div>
        {rename.isError&&<p className={s.error} role="alert">{rename.error.message}</p>}
        <section className="surface"><div className="surface-top"><h2 className="section-title">{editing?`Edit ${editing}`:"Add a stock"}</h2>
          {editing&&<button className={s.plain} onClick={()=>{setEditing("");setTicker("");setNote("");setAbove("");setBelow("");}}>Cancel edit</button>}</div>
          <form className={s.entryForm} onSubmit={submit}>
            <label className="field">NSE ticker<input required readOnly={!!editing} placeholder="RELIANCE" value={ticker} onChange={e=>setTicker(e.target.value.toUpperCase())}/></label>
            <label className="field">Alert at or above · ₹<input type="number" min="0.0001" step="any" value={above} placeholder="Optional" onChange={e=>setAbove(e.target.value)}/></label>
            <label className="field">Alert at or below · ₹<input type="number" min="0.0001" step="any" value={below} placeholder="Optional" onChange={e=>setBelow(e.target.value)}/></label>
            <label className={`field ${s.note}`}>Research note<input maxLength={500} value={note} placeholder="Why this stock is on your list" onChange={e=>setNote(e.target.value)}/></label>
            <div className={s.submit}><Button disabled={save.isPending} type="submit">{save.isPending?"Saving…":editing?"Update stock":"Add to watchlist"}</Button>
              {save.isError&&<span className={s.error} role="alert">{save.error.message}</span>}</div>
          </form></section>
        <section className="surface"><div className="surface-top"><h2 className="section-title">Stocks to watch</h2>
          <label className="field"><span className="sr-only">Search watchlist</span><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Find a ticker or note"/></label></div>
          <div className="table-scroll"><table><thead><tr><th>Stock</th><th>Last close</th><th>1D move</th><th>Price date</th><th>Levels</th><th>Status</th><th>Research note</th><th/></tr></thead>
            <tbody>{items.map(item=><tr key={item.ticker}><td><Link href={`/stocks/${encodeURIComponent(item.ticker)}`}>{item.ticker}</Link></td>
              <td>{item.close==null?"—":inr.format(item.close)}</td>
              <td className={(item.change_pct??0)>=0?s.up:s.down}>{item.change_pct==null?"—":`${item.change_pct>=0?"+":""}${item.change_pct.toFixed(2)}%`}</td>
              <td>{item.price_date??"—"}</td><td>{item.target_above!=null?`↑ ${inr.format(item.target_above)}`:""} {item.target_below!=null?`↓ ${inr.format(item.target_below)}`:""}</td>
              <td>{item.alert?<span className={item.alert==="above"?s.alertUp:s.alertDown}>{item.alert==="above"?"Above level":"Below level"}</span>:"—"}</td>
              <td className={s.noteCell}>{item.note||"—"}</td><td><div className={s.rowActions}><button className={s.plain} onClick={()=>edit(item)}>Edit</button>
                <button className={s.icon} aria-label={`Remove ${item.ticker} from watchlist`} disabled={remove.isPending}
                  onClick={()=>{if(confirm(`Remove ${item.ticker} from this watchlist?`))remove.mutate(item.ticker);}}><Trash2 size={15}/></button></div></td></tr>)}</tbody></table>
            {!items.length&&<State>{search?"No stocks match your search.":"No stocks yet. Add a ticker above or from its stock page."}</State>}</div>
          {remove.isError&&<p className={s.error} role="alert">{remove.error.message}</p>}</section>
      </>}
      <p className={s.hint}>Price levels are evaluated when this page loads against the latest stored close. They do not send notifications or place orders.</p>
    </div>
  </div>;
}
