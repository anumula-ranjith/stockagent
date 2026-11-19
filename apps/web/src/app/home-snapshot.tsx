"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight } from "lucide-react";
import { StockTicker } from "@/components/stock-ticker";
import Link from "next/link";
import { SignInNotice, State } from "@/components/presentation";
import { useSession } from "@/components/providers";
import { api, type UniverseRow } from "@/lib/api";
import type { Snapshot } from "./dashboard/ranker-model";
import { dateLabel } from "@/lib/utils";
import { rankingQuery } from "@/lib/ranking-query";

function SnapshotBook({ title, entries, direction }: { title: string; entries: Snapshot["rows"][string][]; direction: "positive" | "negative" }) {
  return <div className="snapshot-book">
    <h3 className={direction}>{title}</h3>
    <ul>{entries.map(entry => <li key={entry.ticker}>
      <StockTicker ticker={entry.ticker}/>
      <span>{entry.sector}</span>
      <strong className={direction}>{entry.values.composite.toFixed(1)}</strong>
    </li>)}</ul>
  </div>;
}

export function HomeSnapshot() {
  const session = useSession();
  const universe = useQuery({ queryKey: ["universe"], queryFn: ({ signal }) => api<UniverseRow[]>("/universe", { signal }) });
  const book = useQuery(rankingQuery(session.data?.id));
  const sectors = new Set(universe.data?.map(row => row.sector).filter(Boolean));
  return <>
    <div className="market-overview" aria-label="Research coverage">
      <div><strong>{book.data?.universe ?? universe.data?.length ?? "—"}</strong><span>{book.data ? "Nifty 500 constituents" : "Stocks in NSE directory"}</span></div>
      <div><strong>{book.data?.heat.length ?? (sectors.size || "—")}</strong><span>{book.data ? "Sectors with 20-day returns" : "Directory sectors"}</span></div>
      <div><strong>4</strong><span>Ranking agents</span></div>
      <div><strong>NSE</strong><span>India equity market</span></div>
    </div>
    <section className="home-section"><div className="home-heading">
      <div><h2>Latest rankings</h2><p className="subtle">{book.data ? dateLabel(book.data.asof) : "Top five long and short candidates."}</p></div>
      <Link href="/dashboard" className="text-link">Open dashboard <ArrowUpRight size={17}/></Link>
    </div>
    {session.isPending ? <State>Checking your session…</State>
      : session.isError ? <State error>Session unavailable. Try again shortly.</State>
      : !session.data ? <SignInNotice next="/dashboard">Compare the latest agent scores and composite rankings.</SignInNotice>
      : book.isError ? <State error>Rankings are unavailable.</State>
      : !book.data ? <State>Loading rankings…</State>
      : !book.data.books.combined.longs.length && !book.data.books.combined.shorts.length ? <State>No candidates have an observed composite score.</State>
      : <div className="surface two-books snapshot-books">
        <SnapshotBook title="Long candidates" entries={book.data.books.combined.longs.slice(0,5).map(t=>book.data!.rows[t])} direction="positive"/>
        <SnapshotBook title="Short candidates" entries={book.data.books.combined.shorts.slice(0,5).map(t=>book.data!.rows[t])} direction="negative"/>
      </div>}
    </section>
  </>;
}
