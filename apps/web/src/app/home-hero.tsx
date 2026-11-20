"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { useSession } from "@/components/providers";
import { api, type UniverseRow } from "@/lib/api";
import { rankingQuery } from "@/lib/ranking-query";
import { dateLabel } from "@/lib/utils";

const tags = ["Technical", "Sentiment", "Momentum", "Fundamental"];

export function HomeHero() {
  const session = useSession();
  const universe = useQuery({ queryKey: ["universe"], queryFn: ({ signal }) => api<UniverseRow[]>("/universe", { signal }) });
  const book = useQuery(rankingQuery(session.data?.id));
  const longs = book.data?.books.combined.longs.slice(0, 3).map(t => book.data!.rows[t]) ?? [];
  const shorts = book.data?.books.combined.shorts.slice(0, 3).map(t => book.data!.rows[t]) ?? [];
  const asof = book.data ? dateLabel(book.data.asof) : "Live today";
  const sectors = new Set(universe.data?.map(r => r.sector).filter(Boolean)).size;
  const updates = (book.data?.universe ?? 0) + (universe.data?.length ?? 0);

  return <section className="home-hero">
    <div className="shell home-hero-inner">
      <div className="home-hero-copy">
        <p className="home-eyebrow">Equity Intelligence <span>·</span> Quant Research <span>·</span> NSE</p>
        <h1>Invest smarter.<br/>Think quant.</h1>
        <p className="home-hero-lede">Rank NSE equities with four agents — technical, sentiment, momentum and fundamental. Follow each idea from screen to backtest.</p>
        <div className="home-hero-actions">
          <Button variant="primary" asChild><Link href="/dashboard">Open dashboard <ArrowRight size={16}/></Link></Button>
          <Button variant="ghost" asChild><Link href="/datadaily/screener">Open screener</Link></Button>
        </div>
        <ul className="home-hero-tags" aria-label="Agent dimensions">
          {tags.map(t => <li key={t}>{t}</li>)}
        </ul>
      </div>

      <aside className="composite-card" aria-label="Composite summary">
        <header>
          <p className="composite-label">Composite · {asof}</p>
          <span className="composite-live"><i/>Live</span>
        </header>
        <div className="composite-books">
          <div>
            <p className="composite-col-title up">Top Long</p>
            {longs.length ? longs.map(r => <div key={r.ticker} className="composite-row">
              <span>{r.ticker}</span><strong className="up">{r.values.composite.toFixed(1)}</strong>
            </div>) : [1,2,3].map(i => <div key={i} className="composite-row"><span className="skel">—</span><strong className="skel">—</strong></div>)}
          </div>
          <div>
            <p className="composite-col-title down">Top Short</p>
            {shorts.length ? shorts.map(r => <div key={r.ticker} className="composite-row">
              <span>{r.ticker}</span><strong className="down">{r.values.composite.toFixed(1)}</strong>
            </div>) : [1,2,3].map(i => <div key={i} className="composite-row"><span className="skel">—</span><strong className="skel">—</strong></div>)}
          </div>
        </div>
        <div className="composite-stats">
          <div><strong>{book.data?.universe ?? universe.data?.length ?? "—"}</strong><span>Nifty 500</span></div>
          <div><strong>{book.data?.heat.length ?? sectors ?? "—"}</strong><span>Sectors</span></div>
          <div><strong>4</strong><span>Agents</span></div>
          <div><strong>{updates || "—"}</strong><span>Updates today</span></div>
        </div>
      </aside>
    </div>
  </section>;
}
