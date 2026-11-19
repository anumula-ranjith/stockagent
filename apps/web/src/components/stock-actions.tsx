"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { BookmarkPlus, BriefcaseBusiness } from "lucide-react";
import Link from "next/link";
import { createPortal } from "react-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { inr, signed, type PortfolioDetail } from "@/lib/personal-types";
import { useSession } from "@/components/providers";
import styles from "./save-stock.module.css";

type Destination = "watchlist" | "portfolio";
type Account = { id: string; name: string };

type ListFields = { note: string; target_above: string; target_below: string };
type Member = Account & {note: string | null; target_above: number | null; target_below: number | null};

function PortfolioPosition({account, ticker, held, userId}: {
  account: Account; ticker: string; held: boolean; userId: string;
}) {
  const detail = useQuery({
    queryKey: ["portfolio-detail", account.id, userId],
    queryFn: ({signal}) => api<PortfolioDetail>("/portfolios/" + account.id, {signal}),
    enabled: held,
    staleTime: 0,
  });
  const position = held ? detail.data?.holdings.find(row => row.ticker === ticker) : undefined;
  return <tr>
    <th scope="row">{account.name}</th>
    {held && !detail.data ? <td colSpan={3}>{detail.isError ? "Position unavailable" : "Loading position…"}</td> : <>
      <td>{position?.quantity.toLocaleString("en-IN", {maximumFractionDigits: 6}) ?? "0"}</td>
      <td>{position ? inr.format(position.average_cost) : "—"}</td>
      <td>{position?.unrealized_pnl != null ? signed(position.unrealized_pnl) : position ? "No price" : "—"}
        {position?.price_date && <small>{position.price_date}</small>}</td>
    </>}
  </tr>;
}

export function StockActions({ ticker, expanded = false }: { ticker: string; expanded?: boolean }) {
  const [destination, open] = useState<Destination | null>(null);
  return <span className={expanded ? "stock-personal-actions" : styles.stock}>
    <button className={expanded ? "button button-secondary" : undefined} type="button" aria-label={`Add ${ticker} to watchlist`} title="Add to watchlist" onClick={() => open("watchlist")}><BookmarkPlus size={16}/>{expanded && "Add to watchlist"}</button>
    <button className={expanded ? "button button-secondary" : undefined} type="button" aria-label={`Record a trade for ${ticker}`} title="Record a trade" onClick={() => open("portfolio")}><BriefcaseBusiness size={16}/>{expanded && "Record a trade"}</button>
    {destination && createPortal(<SaveDialog ticker={ticker} destination={destination} dismiss={() => open(null)}/>, document.body)}
  </span>;
}

function SaveDialog({ ticker, destination, dismiss }: { ticker: string; destination: Destination; dismiss: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const client = useQueryClient();
  const session = useSession();
  const watch = destination === "watchlist";
  const accounts = useQuery({
    queryKey: [watch ? "my-watchlists" : "my-portfolios", session.data?.id],
    queryFn: ({signal}) => api<Account[]>(watch ? "/watchlists" : "/portfolios", {signal}),
    enabled: !!session.data,
  });
  const portfolios = useQuery({
    queryKey: ["my-portfolios", session.data?.id],
    queryFn: ({signal}) => api<Account[]>("/portfolios", {signal}),
    enabled: !!session.data,
  });
  const [choice, setChoice] = useState<string>();
  const selected = choice ?? accounts.data?.[0]?.id ?? "new";
  const [edits, setEdits] = useState<Record<string, boolean>>({});
  const [drafts, setDrafts] = useState<Record<string, Partial<ListFields>>>({});
  const [newList, setNewList] = useState(false);
  const membershipPath = "/stock-memberships/" + encodeURIComponent(ticker);
  const membership = useQuery({
    queryKey: ["stock-memberships", session.data?.id, ticker],
    queryFn: ({signal}) => api<{watchlists: Member[]; portfolios: Account[]}>(membershipPath, {signal}),
    enabled: !!session.data,
    staleTime: 0,
  });
  const members = new Set(membership.data?.watchlists.map(list => list.id));
  const additions = Object.keys(edits).filter(id => edits[id] && !members.has(id));
  const removals = Object.keys(edits).filter(id => !edits[id] && members.has(id));
  const creating = watch ? newList || accounts.data?.length === 0 : selected === "new";
  const activeDrafts = Object.entries(drafts).filter(([id]) =>
    id === "new" ? creating : (edits[id] ?? members.has(id)));
  function fieldsFor(id: string, name: string) {
    const member = membership.data?.watchlists.find(list => list.id === id);
    const value = (key: keyof ListFields) => drafts[id]?.[key] ?? String(member?.[key] ?? "");
    function change(key: keyof ListFields, next: string) {
      setDrafts(previous => ({...previous, [id]: {...previous[id], [key]: next}}));
    }
    return <fieldset aria-label={name + " details"} className={styles.listDetails}>
      <label className="field">Research note<input maxLength={500} value={value("note")} onChange={e => change("note", e.target.value)}/></label>
      {(["target_above", "target_below"] as const).map(key => <label className="field" key={key}>
        {key === "target_above" ? "Alert at or above · ₹" : "Alert at or below · ₹"}
        <input type="number" min="0.0001" max="1000000000" step="any" value={value(key)} onChange={e => change(key, e.target.value)}/>
      </label>)}
    </fieldset>;
  }
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  const save = useMutation({
    mutationFn: async (form: FormData) => {
      if (watch) {
        const patches = Object.fromEntries(activeDrafts.map(([id, patch]) => [
          id, Object.fromEntries(Object.entries(patch).map(([key, value]) => [key, value || null])),
        ]));
        const {new: newDetails, ...details} = patches;
        const body = {details, new_details: newDetails, watchlist_ids: additions, remove_ids: removals, new_name: creating ? String(form.get("name") ?? "").trim() : null};
        const result = await api<{added: number; removed: number}>(membershipPath + "/watchlists", {method: "POST", body: JSON.stringify(body)});
        if (!result.added && !result.removed) return `Watchlist details saved for ${ticker}.`;
        return `Watchlists updated for ${ticker}. Added to ${result.added}, removed from ${result.removed}.`;
      }
      let id = String(form.get("account"));
      let name = accounts.data?.find(account => account.id === id)?.name;
      if (id === "new") {
        const inputName = String(form.get("name") ?? "").trim();
        if (!inputName) throw new Error("Enter a name.");
        if (Number(form.get("cash")) < Number(form.get("quantity")) * Number(form.get("price")) + Number(form.get("fees")) - 1e-8) {
          throw new Error("Opening cash must cover the purchase and fees.");
        }
        const body = {
          name: inputName, initial_cash: form.get("cash"), initial_date: form.get("date"),
        };
        const account = await api<Account>("/portfolios", {
          method: "POST", body: JSON.stringify(body),
        });
        id = account.id;
        name = account.name;
        client.setQueryData<Account[]>([watch ? "my-watchlists" : "my-portfolios", session.data?.id],
          previous => [...(previous ?? []).filter(row => row.id !== id), account]);
        setChoice(id);
      }
        await api("/portfolios/" + id + "/entries", {method:"POST", body:JSON.stringify({
          ticker, kind:form.get("kind"), trade_date:form.get("date"), quantity:form.get("quantity"),
          price:form.get("price"), fees:form.get("fees") || "0",
        })});
      return ticker + " trade recorded in " + name + ".";
    },
    onSuccess: () => {
      void client.invalidateQueries({queryKey:["stock-memberships",session.data?.id,ticker]});
      void client.invalidateQueries({queryKey:[watch ? "my-watchlists" : "my-portfolios"]});
      void client.invalidateQueries({queryKey:[watch ? "watchlist-detail" : "portfolio-detail"]});
    },
  });
  const today = new Date().toLocaleDateString("en-CA", {timeZone:"Asia/Kolkata"});
  const [trade, setTrade] = useState({kind:"buy", quantity:"", price:"", fees:"0", date:today, cash:""});
  const kind = creating ? "buy" : trade.kind;
  const payload = {kind, trade_date:trade.date, quantity:trade.quantity, price:trade.price,
    fees:trade.fees || "0", opening_cash:creating ? trade.cash || "0" : "0", ticker};
  const complete = !watch && !!trade.date && Number(trade.quantity)>0 && Number(trade.price)>0 && (!creating || !!trade.cash);
  const detail = useQuery({
    queryKey:["portfolio-detail", selected, session.data?.id],
    queryFn:({signal}) => api<PortfolioDetail>("/portfolios/" + selected, {signal}),
    enabled:!watch && !creating && !!session.data,
  });
  const preview = useQuery({
    queryKey:["trade-preview", selected, session.data?.id, payload],
    enabled:complete && !!session.data && !save.isSuccess,
    staleTime:0, gcTime:0,
    queryFn:({signal}) => api<{cash:number; shares:number; average_cost:number|null}>(
      "/portfolios/" + selected + "/entries/preview", {signal, method:"POST", body:JSON.stringify(payload)}),
  });
  const cash = creating ? Number(trade.cash || 0) : detail.data?.cash;
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    event.stopPropagation();
    if (!save.isPending) save.mutate(new FormData(event.currentTarget));
  }
  return <dialog ref={ref} aria-label={`${ticker} · ${destination}`} className={styles.dialog}
    onCancel={event => {event.preventDefault(); if (!save.isPending) dismiss();}}>
    <h2>{watch ? "Add to watchlist" : "Record portfolio trade"} · {ticker}</h2>
    {!session.isPending && !session.data ? <p><Link href={"/login?next=" + encodeURIComponent(location.pathname + location.search)}>Sign in</Link> to save {ticker}.</p> : save.isSuccess ? <p role="status">{save.data}</p> : accounts.isPending ? <p>Loading destinations…</p>
      : accounts.isError ? <p role="alert">{accounts.error.message}</p>
      : <form onSubmit={submit}>
        {membership.data ? <div>
          <p><strong>In watchlists</strong> · {membership.data.watchlists.map(list => list.name).join(", ") || "None"}</p>
          {portfolios.data?.length && session.data ? <section className={styles.positions}>
            <table aria-label={ticker + " portfolio positions"}>
              <caption>Portfolio positions · {ticker}</caption>
              <thead><tr><th>Portfolio</th><th>Shares</th><th>Avg buy price</th><th>Unrealized P&amp;L</th></tr></thead>
              <tbody>{portfolios.data.map(account => <PortfolioPosition key={account.id} account={account}
                ticker={ticker} userId={session.data!.id} held={membership.data.portfolios.some(row => row.id === account.id)}/>)}</tbody>
            </table>
            <small>Average cost includes buy fees. P&amp;L uses the latest stored close.</small>
          </section> : <p>{portfolios.isError ? "Portfolios unavailable." : portfolios.isPending ? "Loading portfolios…" : "No portfolios yet."}</p>}
        </div> : <p role="status">{membership.isError ? "Could not load memberships." : "Checking memberships…"}</p>}
        {watch ? <fieldset disabled={save.isPending || !membership.data}>
          <legend>Choose watchlists</legend>
          {accounts.data.map(list => <div key={list.id}><label>
            <input type="checkbox" checked={edits[list.id] ?? members.has(list.id)}
              onChange={event => setEdits({...edits, [list.id]: event.target.checked})}/>
            {" "}{list.name}{removals.includes(list.id) ? " · Will remove" : members.has(list.id) && " · Already saved"}
          </label>{(edits[list.id] ?? members.has(list.id)) && fieldsFor(list.id, list.name)}</div>)}
          {!!accounts.data.length && <label><input type="checkbox" checked={newList} onChange={event => setNewList(event.target.checked)}/> Create new watchlist</label>}
        </fieldset> :
        <label className="field">{watch ? "Watchlist" : "Portfolio"}<select name="account" value={selected} disabled={save.isPending} onChange={event => setChoice(event.target.value)} required>{accounts.data.map(account =>
          <option key={account.id} value={account.id}>{account.name}</option>)}
          <option value="new">Create new {destination}…</option></select></label>}
        {watch && removals.length > 0 && <p>Removing a stock also removes its note and alerts from the unchecked lists.</p>}
        {creating && <label className="field">New {destination} name<input name="name" required maxLength={80}/></label>}
        {creating && watch && fieldsFor("new", "New watchlist")}
        {creating && !watch && <label className="field">Opening cash · ₹<input name="cash" value={trade.cash} onChange={e => setTrade({...trade, cash:e.target.value})} type="number" min="0" step="0.01" required/></label>}
        {!watch && <>
          <label className="field">Trade type<select name="kind" value={kind} onChange={e => setTrade({...trade, kind:e.target.value})}><option value="buy">Buy</option>{!creating && <option value="sell">Sell</option>}</select></label>
          <label className="field">Trade date<input type="date" name="date" value={trade.date} onChange={e => setTrade({...trade, date:e.target.value})} max={today} required/></label>
          <label className="field">Shares<input type="number" name="quantity" value={trade.quantity} onChange={e => setTrade({...trade, quantity:e.target.value})} min="0.000001" step="any" required/></label>
          <label className="field">Price per share · ₹<input type="number" name="price" value={trade.price} onChange={e => setTrade({...trade, price:e.target.value})} min="0.0001" step="any" required/></label>
          <label className="field">Fees · ₹<input type="number" name="fees" value={trade.fees} onChange={e => setTrade({...trade, fees:e.target.value})} min="0" step="any"/></label>
          <section className={styles.positions} aria-label="Trade preview">
            <strong>Available cash · {cash == null ? "—" : inr.format(cash)}</strong>
            {preview.data && complete ? <table aria-label="After trade"><caption>After this trade</caption>
              <thead><tr><th>Shares</th><th>Avg buy price</th><th>Cash balance</th></tr></thead>
              <tbody><tr><td>{preview.data.shares.toLocaleString("en-IN", {maximumFractionDigits:6})}</td>
                <td>{preview.data.average_cost == null ? "—" : inr.format(preview.data.average_cost)}</td>
                <td>{inr.format(preview.data.cash)}</td></tr></tbody></table>
              : <p>{complete ? preview.isError ? preview.error.message : "Calculating preview…" : "Enter the trade details to preview your balance."}</p>}
          </section>
        </>}
        {save.isError && <p role="alert">{save.error.message}</p>}
        <button type="submit" className="button" disabled={save.isPending || (!watch && (!complete || !preview.isSuccess || preview.isFetching)) || (watch && (!membership.data || (!creating && !additions.length && !removals.length && !activeDrafts.length)))}>{save.isPending ? "Saving…" : creating ? "Create and save" : "Save"}</button>
      </form>}
    <button type="button" className="button button-secondary" disabled={save.isPending} onClick={dismiss}>{save.isSuccess ? "Done" : "Close"}</button>
  </dialog>;
}
