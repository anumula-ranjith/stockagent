"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { State } from "@/components/presentation";
import { useSession } from "@/components/providers";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { inr, type BrokerSnapshot, type Holding } from "@/lib/personal-types";
import s from "./workspace.module.css";

export function AngelOnePanel({manual}:{manual:Holding[]}) {
  const session=useSession();
  const client=useQueryClient();
  const [apiKey,setApiKey]=useState("");
  const [clientCode,setClientCode]=useState("");
  const [password,setPassword]=useState("");
  const [totp,setTotp]=useState("");
  const saved=useQuery({queryKey:["angel-one-snapshot",session.data?.id],enabled:!!session.data,
    queryFn:({signal})=>api<BrokerSnapshot|null>("/brokers/angel-one/snapshot",{signal})});
  const sync=useMutation({mutationFn:()=>api<BrokerSnapshot>("/brokers/angel-one/sync",{method:"POST",
    body:JSON.stringify({api_key:apiKey,client_code:clientCode,password,totp})}),
    onSuccess:()=>{setApiKey("");setPassword("");setTotp("");void client.invalidateQueries({queryKey:["angel-one-snapshot"]});}});
  const remove=useMutation({mutationFn:()=>api("/brokers/angel-one/snapshot",{method:"DELETE"}),
    onSuccess:()=>void client.invalidateQueries({queryKey:["angel-one-snapshot"]})});
  function submit(event:FormEvent){event.preventDefault();sync.mutate();}
  const snapshot=saved.data;
  return <section className="surface"><div className="surface-top"><div><h2 className="section-title">Angel One · read only</h2>
    <p className="subtle">Compare a broker snapshot with your manual portfolio. No orders are sent.</p></div>
    {snapshot&&<span className="subtle">{snapshot.account_mask} · synced {new Date(snapshot.fetched_at).toLocaleString("en-IN")}</span>}</div>
    <div className={s.brokerBody}>
      <form className={s.brokerForm} onSubmit={submit} autoComplete="off">
        <label className="field">SmartAPI key<input required value={apiKey} onChange={e=>setApiKey(e.target.value)} autoComplete="off"/></label>
        <label className="field">Client code<input required value={clientCode} onChange={e=>setClientCode(e.target.value.toUpperCase())} autoComplete="off"/></label>
        <label className="field">Password or MPIN<input required type="password" value={password} onChange={e=>setPassword(e.target.value)} autoComplete="new-password"/></label>
        <label className="field">Current six-digit TOTP<input required type="text" inputMode="numeric" pattern="[0-9]{6}" maxLength={6}
          value={totp} onChange={e=>setTotp(e.target.value.replace(/\D/g,"").slice(0,6))} autoComplete="one-time-code"/></label>
        <div className={s.submit}><Button disabled={sync.isPending} type="submit">{sync.isPending?"Connecting…":"Sync holdings and today’s trades"}</Button>
          <span className={s.hint}>Credentials are used once and are not saved. Enter a new TOTP for each sync.</span></div>
      </form>
      {sync.isError&&<p className={s.error} role="alert">{sync.error.message}</p>}
      {saved.isError&&<State error>{saved.error.message}</State>}
      {snapshot&&<>
        <div className={s.brokerHeading}><h3>Broker holdings <span className="subtle">{snapshot.holdings.length}</span></h3>
          <Button variant="ghost" disabled={remove.isPending} onClick={()=>{if(confirm("Remove the saved Angel One snapshot?"))remove.mutate();}}>Clear snapshot</Button></div>
        <div className="table-scroll"><table><thead><tr><th>Instrument</th><th>Exchange</th><th>Shares</th><th>Avg price</th><th>Broker LTP</th><th>Broker P&amp;L</th><th>Manual shares</th><th>Difference</th></tr></thead>
          <tbody>{snapshot.holdings.map((row,index)=>{const local=row.ticker?manual.find(item=>item.ticker===row.ticker):null;
            const diff=row.quantity!=null&&local?row.quantity-local.quantity:null;
            return <tr key={row.symbol+index}><td>{row.ticker?<Link href={`/stocks/${encodeURIComponent(row.ticker)}`}>{row.symbol}</Link>:row.symbol}</td>
              <td>{row.exchange}</td><td>{row.quantity??"—"}</td><td>{row.average_price==null?"—":inr.format(row.average_price)}</td>
              <td>{row.broker_ltp==null?"—":inr.format(row.broker_ltp)}</td>
              <td className={(row.broker_pnl??0)>=0?s.up:s.down}>{row.broker_pnl==null?"—":inr.format(row.broker_pnl)}</td>
              <td>{local?.quantity??"—"}</td><td>{diff==null?"—":diff}</td></tr>;})}</tbody></table>
          {!snapshot.holdings.length&&<State>No broker holdings were returned.</State>}</div>
        <h3>Today’s broker trades <span className="subtle">{snapshot.trades.length}</span></h3>
        <div className="table-scroll"><table><thead><tr><th>Instrument</th><th>Side</th><th>Quantity</th><th>Fill price</th><th>Fill time</th><th>Fill ID</th></tr></thead>
          <tbody>{snapshot.trades.map((row,index)=><tr key={row.fill_id+index}><td>{row.symbol}</td><td>{row.side}</td><td>{row.quantity??"—"}</td>
            <td>{row.fill_price==null?"—":inr.format(row.fill_price)}</td><td>{row.fill_time||"—"}</td><td>{row.fill_id||"—"}</td></tr>)}</tbody></table>
          {!snapshot.trades.length&&<State>No trades were returned for the current day.</State>}</div>
      </>}
      <p className={s.hint}>Angel One provides settled holdings and the current day’s trade book. This snapshot is separate from manual cash and FIFO P&amp;L. Brokerage balances and older fills are not inferred.</p>
    </div>
  </section>;
}
