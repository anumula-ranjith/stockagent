"use client";

import { useQuery } from "@tanstack/react-query";
import { useId, useMemo, useState, type KeyboardEvent } from "react";
import { api, type UniverseRow } from "@/lib/api";
import s from "./ticker-picker.module.css";

type Props = { value: string; onChange: (ticker: string) => void; readOnly?: boolean; required?: boolean };

export function TickerPicker({ value, onChange, readOnly = false, required = false }: Props) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const universe = useQuery({queryKey:["universe"],queryFn:({signal})=>api<UniverseRow[]>("/universe",{signal}),staleTime:5*60_000});
  const matches = useMemo(() => {
    const term = value.trim().toLowerCase();
    if (!term || readOnly) return [];
    return (universe.data??[]).filter(row => row.ticker.toLowerCase().includes(term) || row.symbol?.toLowerCase().includes(term))
      .sort((a,b) => Number(!a.ticker.toLowerCase().startsWith(term))-Number(!b.ticker.toLowerCase().startsWith(term)) || a.ticker.localeCompare(b.ticker))
      .slice(0,8);
  },[universe.data,value,readOnly]);
  const visible = open && matches.length>0 && !matches.some(row=>row.ticker===value.trim().toUpperCase());
  function select(ticker:string) { onChange(ticker);setOpen(false);setActive(0); }
  function keyDown(event:KeyboardEvent<HTMLInputElement>) {
    if (!visible) return;
    if (event.key==="ArrowDown") {event.preventDefault();setActive(index=>(index+1)%matches.length);}
    if (event.key==="ArrowUp") {event.preventDefault();setActive(index=>(index-1+matches.length)%matches.length);}
    if (event.key==="Enter") {event.preventDefault();select(matches[active]?.ticker??matches[0].ticker);}
    if (event.key==="Escape") {event.preventDefault();setOpen(false);}
  }
  return <div className={`${s.picker} field`}>
    <label htmlFor={id}>NSE ticker</label>
    <input id={id} required={required} readOnly={readOnly} role="combobox" aria-autocomplete="list"
      aria-expanded={visible} aria-controls={visible?`${id}-options`:undefined}
      aria-activedescendant={visible?`${id}-option-${active}`:undefined}
      autoComplete="off" placeholder="Search ticker or exchange symbol" value={value}
      onFocus={()=>setOpen(true)} onBlur={()=>setOpen(false)} onKeyDown={keyDown}
      onChange={event=>{onChange(event.target.value.toUpperCase());setActive(0);setOpen(true);}}/>
    {visible && <ul id={`${id}-options`} className={s.options} role="listbox" aria-label="Matching NSE tickers">
      {matches.map((row,index)=><li key={row.ticker} id={`${id}-option-${index}`} role="option" aria-selected={index===active}>
        <button type="button" className={index===active?s.active:undefined} onMouseDown={event=>event.preventDefault()}
          onClick={()=>select(row.ticker)}><strong>{row.ticker}</strong><span>{row.symbol}{row.sector?` · ${row.sector}`:""}</span></button>
      </li>)}
    </ul>}
    {universe.isError && !readOnly && <small className={s.hint}>Ticker suggestions are unavailable. You can still enter a ticker.</small>}
  </div>;
}
