"use client";

import {
  type ColumnDef, type SortingState, flexRender, getCoreRowModel, getPaginationRowModel,
  getSortedRowModel, useReactTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { State } from "./presentation";

export function DataTable<T>({ data, columns, label, empty, pageSize = 25 }: {
  data: T[]; columns: ColumnDef<T>[]; label: string; empty: string; pageSize?: number;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const table = useReactTable({
    data, columns, state: { sorting }, onSortingChange: setSorting,
    initialState: { pagination: { pageSize } },
    getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });
  if (!data.length) return <State>{empty}</State>;
  return <>
    <div className="table-scroll" tabIndex={0} role="region" aria-label={label}>
      <table aria-label={label}>
        <thead>{table.getHeaderGroups().map(group => <tr key={group.id}>
          {group.headers.map(header => {
            const sorted = header.column.getIsSorted();
            const title = flexRender(header.column.columnDef.header, header.getContext());
            return <th key={header.id} scope="col" aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined}>
              {header.column.getCanSort()
                ? <button className="sort-button" onClick={header.column.getToggleSortingHandler()}>
                  {title} {sorted === "asc" ? <ArrowUp size={13}/> : sorted === "desc" ? <ArrowDown size={13}/> : <ArrowUpDown size={13}/>}
                </button> : title}
            </th>;
          })}
        </tr>)}</thead>
        <tbody>{table.getRowModel().rows.map(row => <tr key={row.id}>
          {row.getVisibleCells().map(cell => <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>)}
        </tr>)}</tbody>
      </table>
    </div>
    {data.length > pageSize && <div className="table-paging">
      <span>Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()}</span>
      <button className="icon-button" aria-label="Previous page" disabled={!table.getCanPreviousPage()} onClick={() => table.previousPage()}><ChevronLeft size={19}/></button>
      <button className="icon-button" aria-label="Next page" disabled={!table.getCanNextPage()} onClick={() => table.nextPage()}><ChevronRight size={19}/></button>
    </div>}
  </>;
}
