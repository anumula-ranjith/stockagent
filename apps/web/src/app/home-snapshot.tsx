"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { SignInNotice, State } from "@/components/presentation";
import { useSession } from "@/components/providers";
import { api, type Combine, type RankedStock, type UniverseRow } from "@/lib/api";
import { dateLabel } from "@/lib/utils";

function SnapshotBook({ title, entries, direction }: { title: string; entries: RankedStock[]; direction: "positive" | "negative" }) {
  return <div className="snapshot-book">
    <h3 className={direction}>{title}</h3>
    <ul>{entries.map(entry => <li key={entry.ticker}>
      <Link href={"/stocks/" + encodeURIComponent(entry.ticker)}>{entry.ticker}</Link>
      <span>{entry.sector}</span>
      <strong className={direction}>{entry.composite.toFixed(1)}</strong>
    </li>)}</ul>
  </div>;
}

export function HomeSnapshot() {
  const session = useSession();
  const universe = useQuery({ queryKey: ["universe"], queryFn: ({ signal }) => api<UniverseRow[]>("/universe", { signal }) });
  const book = useQuery({
    queryKey: ["home-book", session.data?.id], enabled: !!session.data,
    queryFn: ({ signal }) => api<Combine>("/combine?n=5", { signal }),
  });
  const sectors = new Set(universe.data?.map(row => row.sector).filter(Boolean));
  return <>
    <div className="market-overview" aria-label="Research coverage">
      <div><strong>{universe.data?.length ?? "—"}</strong><span>Stocks in the universe</span></div>
      <div><strong>{sectors.size || "—"}</strong><span>Sectors covered</span></div>
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
      : book.data.note ? <State>{book.data.note}</State>
      : <div className="surface two-books snapshot-books">
        <SnapshotBook title="Long candidates" entries={book.data.longs} direction="positive"/>
        <SnapshotBook title="Short candidates" entries={book.data.shorts} direction="negative"/>
      </div>}
    </section>
  </>;
}
