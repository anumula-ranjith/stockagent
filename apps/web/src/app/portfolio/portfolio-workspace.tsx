"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Plus, Trash2 } from "lucide-react";
import { parseAsString, useQueryState } from "nuqs";
import { useEffect, useState, type FormEvent } from "react";
import { SignInNotice, State } from "@/components/presentation";
import { StockTicker } from "@/components/stock-ticker";
import { TickerPicker } from "@/components/ticker-picker";
import { useSession } from "@/components/providers";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { csvDownload, inr, signed, type PortfolioDetail, type PortfolioRow } from "@/lib/personal-types";
import s from "./workspace.module.css";
import { AngelOnePanel } from "./angel-one";

const today = () => new Date().toLocaleDateString("en-CA", {timeZone:"Asia/Kolkata"});
const pct = (n:number) => `${n.toFixed(1)}%`;
const amount = (value:number|null) => value == null ? "—" : inr.format(value);

export function PortfolioWorkspace() {
  const session = useSession();
  const client = useQueryClient();
  const [selected, setSelected] = useState("");
  const [name, setName] = useState("");
  const [cash, setCash] = useState("");
  const [openingDate, setOpeningDate] = useState(today);
  const [kind, setKind] = useState<"deposit"|"withdrawal"|"buy"|"sell">("buy");
  const [ticker, setTicker] = useState("");
  const [linkedTicker] = useQueryState("ticker", parseAsString);
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");
  const [fees, setFees] = useState("0");
  const [tradeAmount, setTradeAmount] = useState("");
  const [tradeDate, setTradeDate] = useState(today);
  const [note, setNote] = useState("");
  useEffect(() => { if (linkedTicker) setTicker(linkedTicker.toUpperCase()); }, [linkedTicker]);
  const accounts = useQuery({queryKey:["my-portfolios",session.data?.id],enabled:!!session.data,
    queryFn:({signal})=>api<PortfolioRow[]>("/portfolios",{signal})});
  useEffect(() => { if (accounts.data?.length && !selected) setSelected(accounts.data[0].id); }, [accounts.data,selected]);
  const detail = useQuery({queryKey:["portfolio-detail",selected,session.data?.id],enabled:!!session.data&&!!selected,
    queryFn:({signal})=>api<PortfolioDetail>(`/portfolios/${selected}`,{signal})});
  const refresh = () => {void client.invalidateQueries({queryKey:["my-portfolios"]}); void client.invalidateQueries({queryKey:["portfolio-detail"]});};
  const create = useMutation({mutationFn:()=>api<PortfolioRow>("/portfolios",{method:"POST",body:JSON.stringify({name,initial_cash:cash||"0",initial_date:openingDate})}),
    onSuccess:row=>{setName("");setCash("");setSelected(row.id);refresh();}});
  const add = useMutation({mutationFn:()=>api(`/portfolios/${selected}/entries`,{method:"POST",body:JSON.stringify({
    kind,trade_date:tradeDate,ticker:kind==="buy"||kind==="sell"?ticker.trim().toUpperCase():null,
    quantity:kind==="buy"||kind==="sell"?quantity:null,price:kind==="buy"||kind==="sell"?price:null,
    fees:kind==="buy"||kind==="sell"?fees:"0",amount:kind==="deposit"||kind==="withdrawal"?tradeAmount:null,
    note:note||null})}),onSuccess:()=>{setQuantity("");setPrice("");setFees("0");setTradeAmount("");setNote("");refresh();}});
  const remove = useMutation({mutationFn:(id:string)=>api(`/portfolios/${selected}/entries/${id}`,{method:"DELETE"}),onSuccess:refresh});
  const rename = useMutation({mutationFn:(next:string)=>api(`/portfolios/${selected}`,{method:"PATCH",body:JSON.stringify({name:next})}),onSuccess:refresh});
  const erase = useMutation({mutationFn:()=>api(`/portfolios/${selected}`,{method:"DELETE"}),onSuccess:()=>{setSelected("");refresh();}});
  function submitCreate(event:FormEvent) { event.preventDefault(); create.mutate(); }
  function submitTrade(event:FormEvent) { event.preventDefault(); add.mutate(); }
  const report = detail.data;
  if (session.isPending) return <State>Checking your account…</State>;
  if (!session.data) return <SignInNotice next="/portfolio">Your portfolios are private to your account.</SignInNotice>;
  return <div className={s.layout}>
    <aside className={`surface ${s.sidebar}`}>
      <div className="surface-top"><h2 className="section-title">Portfolios</h2><span className="subtle">{accounts.data?.length??0}</span></div>
      <div className={s.sidebarBody}>
        {accounts.isError && <State error>{accounts.error.message}</State>}
        <div className={s.list}>{accounts.data?.map(row=><button key={row.id} className={selected===row.id?s.selected:""}
          onClick={()=>setSelected(row.id)}><strong>{row.name}</strong><small>{row.entry_count} entries</small></button>)}</div>
        <form className={s.form} onSubmit={submitCreate}><h3>New portfolio</h3>
          <label className="field">Name<input required maxLength={80} placeholder="Long-term investments" value={name} onChange={e=>setName(e.target.value)}/></label>
          <label className="field">Opening cash · ₹<input type="number" min="0" step="0.01" placeholder="Optional" value={cash} onChange={e=>setCash(e.target.value)}/></label>
          <label className="field">Opening date<input type="date" max={today()} value={openingDate} onChange={e=>setOpeningDate(e.target.value)}/></label>
          <Button disabled={create.isPending} type="submit"><Plus size={16}/>Create portfolio</Button>
          {create.isError && <p className={s.error} role="alert">{create.error.message}</p>}
        </form>
      </div>
    </aside>
    <div className={s.main}>
      {!selected ? <div className="surface"><State>Create a portfolio to start recording trades and cash movements.</State></div>
        : detail.isError ? <div className="surface"><State error>{detail.error.message}</State></div>
        : !report ? <div className="surface"><State>Loading portfolio…</State></div> : <>
        <div className="surface-top surface"><div><h2 className="section-title">{report.name}</h2><p className="subtle">Manual INR portfolio · prices from local end-of-day data</p></div>
          <div className={s.actions}><Button variant="ghost" disabled={rename.isPending} onClick={()=>{const next=prompt("Portfolio name",report.name);if(next?.trim()&&next.trim()!==report.name)rename.mutate(next.trim());}}>Rename</Button>
            <Button variant="secondary" onClick={()=>csvDownload(`${report.name.replace(/[^a-z0-9-]/gi,"_")}-transactions.csv`,
            [["Date","Type","Ticker","Quantity","Price","Fees","Amount","Note"],...report.entries.map(row=>[row.trade_date,row.kind,row.ticker,row.quantity,row.price,row.fees,row.amount,row.note])])}>
            <Download size={15}/>Export CSV</Button>
            {!report.entries.length && <Button variant="ghost" disabled={erase.isPending} onClick={()=>{
              if (confirm(`Delete empty portfolio “${report.name}”?`)) erase.mutate();}}><Trash2 size={15}/>Delete</Button>}</div></div>
        <div className={s.metrics}>
          <div><small>Total equity</small><strong>{inr.format(report.total_equity)}</strong><span>Cash + priced holdings</span></div>
          <div><small>Invested market value</small><strong>{inr.format(report.market_value)}</strong><span>{report.holdings.length} open positions</span></div>
          <div><small>Available cash</small><strong>{inr.format(report.cash)}</strong><span>After all entries</span></div>
          <div><small>Total P&amp;L</small><strong className={report.total_pnl>=0?s.up:s.down}>{signed(report.total_pnl)}</strong><span>Equity − net contributions</span></div>
          <div><small>Realized P&amp;L</small><strong className={report.realized_pnl>=0?s.up:s.down}>{signed(report.realized_pnl)}</strong><span>FIFO cost basis</span></div>
          <div><small>Unrealized P&amp;L</small><strong className={report.unrealized_pnl>=0?s.up:s.down}>{signed(report.unrealized_pnl)}</strong><span>Open positions</span></div>
        </div>
        {rename.isError&&<p className={s.error} role="alert">{rename.error.message}</p>}
        {report.unpriced_count>0 && <p className={s.warning} role="status">{report.unpriced_count} holding(s) have no stored close. Equity and P&amp;L exclude their market value.</p>}
        <section className="surface"><div className="surface-top"><h2 className="section-title">Holdings</h2><span className="subtle">Latest stored closes, not live quotes</span></div>
          <div className="table-scroll"><table><thead><tr><th>Stock</th><th>Quantity</th><th>Avg cost</th><th>Last close</th><th>Price date</th><th>Market value</th><th>Unrealized P&amp;L</th><th>Weight</th></tr></thead>
            <tbody>{report.holdings.map(row=><tr key={row.ticker}><td><StockTicker ticker={row.ticker}/></td>
              <td>{row.quantity.toLocaleString("en-IN")}</td><td>{inr.format(row.average_cost)}</td><td>{amount(row.close)}</td><td>{row.price_date??"—"}</td>
              <td>{amount(row.market_value)}</td><td className={(row.unrealized_pnl??0)>=0?s.up:s.down}>{row.unrealized_pnl==null?"—":signed(row.unrealized_pnl)}</td>
              <td>{row.weight_pct==null?"—":<span className={s.weight}><i style={{width:pct(row.weight_pct)}}/>{pct(row.weight_pct)}</span>}</td></tr>)}</tbody></table>
            {!report.holdings.length && <State>No open holdings. Add cash, then record a buy.</State>}</div></section>
        <section className="surface"><div className="surface-top"><h2 className="section-title">Record activity</h2><span className="subtle">Buys require cash; sells require owned shares.</span></div>
          <form className={s.entryForm} onSubmit={submitTrade}>
            <label className="field">Type<select value={kind} onChange={e=>setKind(e.target.value as typeof kind)}>
              <option value="buy">Buy</option><option value="sell">Sell</option><option value="deposit">Deposit cash</option><option value="withdrawal">Withdraw cash</option></select></label>
            <label className="field">Date<input type="date" required max={today()} value={tradeDate} onChange={e=>setTradeDate(e.target.value)}/></label>
            {kind==="buy"||kind==="sell" ? <>
              <TickerPicker required value={ticker} onChange={setTicker}/>
              <label className="field">Shares<input required type="number" min="0.000001" step="any" value={quantity} onChange={e=>setQuantity(e.target.value)}/></label>
              <label className="field">Price per share · ₹<input required type="number" min="0.0001" step="any" value={price} onChange={e=>setPrice(e.target.value)}/></label>
              <label className="field">Fees · ₹<input required type="number" min="0" step="any" value={fees} onChange={e=>setFees(e.target.value)}/></label>
            </> : <label className="field">Amount · ₹<input required type="number" min="0.01" step="any" value={tradeAmount} onChange={e=>setTradeAmount(e.target.value)}/></label>}
            <label className={`field ${s.note}`}>Note<input maxLength={500} placeholder="Optional research or trade note" value={note} onChange={e=>setNote(e.target.value)}/></label>
            <div className={s.submit}><Button disabled={add.isPending} type="submit">{add.isPending?"Saving…":"Save activity"}</Button>
              {add.isError && <span className={s.error} role="alert">{add.error.message}</span>}</div>
          </form></section>
        <section className="surface"><div className="surface-top"><h2 className="section-title">Activity ledger</h2><span className="subtle">{report.entries.length} entries · newest first</span></div>
          <div className="table-scroll"><table><thead><tr><th>Date</th><th>Type</th><th>Ticker</th><th>Quantity</th><th>Price</th><th>Fees</th><th>Cash amount</th><th>Note</th><th/></tr></thead>
            <tbody>{report.entries.map(row=><tr key={row.id}><td>{row.trade_date}</td><td className={s.kind}>{row.kind}</td>
              <td>{row.ticker?<StockTicker ticker={row.ticker}/>:"—"}</td>
              <td>{row.quantity??"—"}</td><td>{amount(row.price)}</td><td>{row.fees?inr.format(row.fees):"—"}</td><td>{amount(row.amount)}</td>
              <td className={s.noteCell}>{row.note||"—"}</td><td><button className={s.icon} aria-label={`Delete ${row.kind} entry from ${row.trade_date}`}
                disabled={remove.isPending} onClick={()=>{if(confirm("Delete this ledger entry? Later entries must remain valid.")) remove.mutate(row.id);}}><Trash2 size={15}/></button></td></tr>)}</tbody></table>
            {!report.entries.length && <State>No activity yet.</State>}</div>
          {remove.isError && <p className={s.error} role="alert">{remove.error.message}</p>}</section>
      </>}
      <AngelOnePanel manual={report?.holdings??[]}/>
      <p className={s.hint}>Manual trades use end-of-day local prices. Angel One holdings remain a separate read-only snapshot.</p>
    </div>
  </div>;
}
