"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { RankedTable } from "@/components/ranked-table";
import { SignInNotice, State } from "@/components/presentation";
import { useSession } from "@/components/providers";
import { Button } from "@/components/ui/button";
import { agentLabels, agents, api, type Agent, type Combine } from "@/lib/api";
import { dateLabel } from "@/lib/utils";

const initial = { technical: 25, sentiment: 25, momentum: 25, fundamental: 25 };
type Mode = "weighted" | "consensus" | "hybrid";

export function Tuner() {
  const session = useSession();
  const [weights, setWeights] = useState<Record<Agent, number>>(initial);
  const [debounced, setDebounced] = useState(weights);
  const [mode, setMode] = useState<Mode>("weighted");
  const [size, setSize] = useState(10);
  const [asof, setAsof] = useState("");
  const [side, setSide] = useState<"long" | "short">("long");
  const total = agents.reduce((sum, agent) => sum + weights[agent], 0);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(weights), 300);
    return () => window.clearTimeout(timer);
  }, [weights]);
  const book = useQuery({
    queryKey: ["combine", session.data?.id, mode, size, asof, debounced],
    queryFn: ({ signal }) => {
      const query = new URLSearchParams({ mode, n: String(size) });
      if (asof) query.set("asof", asof);
      if (mode !== "consensus") agents.forEach(agent => query.set(agent, String(debounced[agent])));
      return api<Combine>("/combine?" + query, { signal });
    },
    enabled: !!session.data && (mode === "consensus" || (total > 0 && agents.some(name => debounced[name] > 0))),
    placeholderData: keepPreviousData,
  });
  if (session.isPending) return <State>Checking your session…</State>;
  if (session.isError) return <State error>Session unavailable. Try again shortly.</State>;
  if (!session.data) return <SignInNotice next="/dashboard">Sign in to tune the composite and view the ranking book.</SignInNotice>;
  return <div className="split">
    <aside className="surface"><h2 className="section-title">Configuration</h2>
      <div className="controls">
        <label className="field">Method
          <select value={mode} onChange={event => setMode(event.target.value as Mode)}>
            <option value="weighted">Weighted composite</option><option value="consensus">Consensus</option><option value="hybrid">Hybrid</option>
          </select>
        </label>
        <label className="field">Ranking date
          <input aria-label="Ranking date" type="date" value={asof} onChange={event => setAsof(event.target.value)}/>
        </label>
        <label className="field">Names per side
          <select value={size} onChange={event => setSize(Number(event.target.value))}>
            {[5, 10, 15, 20, 30, 50].map(value => <option key={value}>{value}</option>)}
          </select>
        </label>
        <fieldset className="controls">
          <legend className="mb-2 font-semibold">Agent weights</legend>
          {agents.map(agent => <label className="field" key={agent}>
            <span className="control-label"><span>{agentLabels[agent]}</span>
              <span>{mode === "consensus" ? "25%" : total ? (100 * weights[agent] / total).toFixed(0) + "%" : "0%"}</span></span>
            <input aria-label={agentLabels[agent] + " weight"} type="range" min={0} max={100} value={weights[agent]}
              disabled={mode === "consensus"}
              onChange={event => setWeights(current => ({ ...current, [agent]: Number(event.target.value) }))}/>
          </label>)}
        </fieldset>
        <Button variant="secondary" onClick={() => setWeights(initial)}><RotateCcw size={15}/> Reset weights</Button>
      </div>
    </aside>
    <section className="stack">
      <div className="metrics">
        <div className="metric"><span>As of</span><strong>{book.data ? dateLabel(book.data.asof) : "—"}</strong></div>
        <div className="metric"><span>Long candidates</span><strong className="positive">{book.data?.longs.length ?? "—"}</strong></div>
        <div className="metric"><span>Short candidates</span><strong className="negative">{book.data?.shorts.length ?? "—"}</strong></div>
      </div>
      <div className="surface" aria-busy={book.isFetching}>
        <div className="surface-top">
          <div><h2 className="section-title">Ranking book</h2><p className="subtle" role="status">{book.isFetching && book.data ? "Updating rankings…" : ""}</p></div>
          <div className="tabs" aria-label="Book side">
            <button aria-pressed={side === "long"} onClick={() => setSide("long")}>Longs</button>
            <button aria-pressed={side === "short"} onClick={() => setSide("short")}>Shorts</button>
          </div>
        </div>
        {mode !== "consensus" && total === 0 ? <State>Set at least one weight above zero.</State>
          : book.isError ? <State error>{book.error.message}</State>
          : !book.data ? <State>Loading rankings…</State>
          : book.data.note ? <State>No rankings are stored for this date.</State>
          : <RankedTable rows={side === "long" ? book.data.longs : book.data.shorts} side={side}/>}
      </div>
    </section>
  </div>;
}
