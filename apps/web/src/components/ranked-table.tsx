"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { StockTicker } from "./stock-ticker";
import { agentLabels, agents, type RankedStock } from "@/lib/api";
import { DataTable } from "./data-table";

const columns: ColumnDef<RankedStock>[] = [
  { id: "rank", header: "#", enableSorting: false, cell: ({ row }) => row.index + 1 },
  { accessorKey: "ticker", header: "Ticker", cell: ({ row }) => <StockTicker ticker={row.original.ticker}/> },
  { accessorKey: "sector", header: "Sector" },
  { accessorKey: "composite", header: "Composite", cell: ({ row }) => <strong>{row.original.composite.toFixed(1)}</strong> },
  ...agents.map(agent => ({ accessorKey: agent, header: agentLabels[agent], cell: ({ row }: { row: { original: RankedStock } }) => row.original[agent]?.toFixed(1) ?? "—" })),
];

export function RankedTable({ rows, side }: { rows: RankedStock[]; side: "long" | "short" }) {
  return <DataTable data={rows} columns={columns} label={side === "long" ? "Long candidates" : "Short candidates"}
    empty="No candidates match this configuration." pageSize={20}/>;
}
