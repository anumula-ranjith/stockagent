"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { parseAsString, useQueryStates } from "nuqs";
import Link from "next/link";
import { useMemo } from "react";
import { DataTable } from "@/components/data-table";
import { State } from "@/components/presentation";
import { StockIdentity as StockTicker } from "@/components/stock-identity";
import { useSession } from "@/components/providers";
import { agentLabels, agents, api, type Agent, type ScoreRow, type UniverseRow } from "@/lib/api";

type Stock = UniverseRow & Partial<Record<Agent, number | null>>;
const baseColumns: ColumnDef<Stock>[] = [
  { accessorKey: "ticker", header: "Ticker", cell: ({ row }) => <StockTicker ticker={row.original.ticker} showSector={false}/> },
  { accessorKey: "symbol", header: "Exchange symbol", cell: ({ row }) => row.original.symbol || "—" },
  { accessorKey: "sector", header: "Sector", cell: ({ row }) => row.original.sector || "—" },
  { accessorKey: "industry", header: "Industry", cell: ({ row }) => row.original.industry || "—" },
];
const columnsWithScores: ColumnDef<Stock>[] = [
  ...baseColumns,
  ...agents.map(agent => ({
    accessorFn: (row: Stock) => row[agent] ?? undefined, id: agent, header: agentLabels[agent],
    cell: ({ row }: { row: { original: Stock } }) => row.original[agent]?.toFixed(1) ?? "—",
  })),
];

export function StockTable() {
  const session = useSession();
  const [{ q, sector }, setFilters] = useQueryStates({
    q: parseAsString.withDefault(""), sector: parseAsString.withDefault(""),
  });
  const universe = useQuery({
    queryKey: ["universe"], queryFn: ({ signal }) => api<UniverseRow[]>("/universe", { signal }),
  });
  const scoreData = useQueries({ queries: agents.map(agent => ({
    queryKey: ["agent", agent, session.data?.id], enabled: !!session.data,
    queryFn: ({ signal }: { signal: AbortSignal }) => api<ScoreRow[]>("/agents/" + agent, { signal }),
  })) });
  const scores = scoreData.map(query => query.data);
  const universeRows = universe.data;
  const sectors = useMemo(() => Array.from(new Set((universeRows ?? []).flatMap(row => row.sector ? [row.sector] : []))).sort(), [universeRows]);
  const maps = scores.map(rows => new Map(rows?.map(row => [row.ticker, row.score])));
  const term = q.trim().toLowerCase();
  const rows = (universeRows ?? []).filter(row =>
    (!sector || row.sector === sector) && [row.ticker, row.company_name, row.symbol, row.industry, row.sector].some(value => value?.toLowerCase().includes(term))
  ).map(row => Object.assign({}, row, Object.fromEntries(agents.map((agent, idx) => [agent, maps[idx].get(row.ticker)]))) as Stock);
  return <div className="surface">
    <div className="filters">
      <label className="field">Search
        <input type="search" value={q} onChange={event => void setFilters({ q: event.target.value })}
          placeholder="Company, ticker or industry"/>
      </label>
      <label className="field">Sector
        <select value={sector} onChange={event => void setFilters({ sector: event.target.value })}>
          <option value="">All sectors</option>{sectors.map(value => <option key={value}>{value}</option>)}
        </select>
      </label>
    </div>
    <div className="surface-top"><strong>{rows.length} stocks</strong>
      {session.data ? scoreData.some(query => query.isError) && <span className="subtle">Some agent scores are unavailable.</span>
        : <Link href="/login?next=%2Fstocks" className="text-link">Sign in to compare agent scores</Link>}</div>
    {universe.isError ? <State error>{universe.error.message}</State> : !universe.data ? <State>Loading stocks…</State>
      : <DataTable data={rows} columns={session.data ? columnsWithScores : baseColumns} label="NSE stock universe" empty="No stocks match these filters."/>}
  </div>;
}
