"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type UniverseRow } from "@/lib/api";
import { StockTicker } from "./stock-ticker";

export function StockIdentity(props: { ticker: string; href?: string; label?: string; showSector?: boolean }) {
  const universe = useQuery({ queryKey: ["universe"],
    queryFn: ({ signal }) => api<UniverseRow[]>("/universe", { signal }) });
  const stock = universe.data?.find(row => row.ticker === props.ticker);
  return <div className="stock-identity">
    <StockTicker ticker={props.ticker} href={props.href} label={props.label}/>
    {stock?.company_name && <span className="stock-description">{stock.company_name}</span>}
    {props.showSector !== false && stock?.sector && <span className="stock-description">{stock.sector}</span>}
  </div>;
}
