import { Suspense } from "react";
import Link from "next/link";
import { PageTitle, State } from "@/components/presentation";
import { BacktestView } from "./backtest-view";

export const metadata = { title: "Backtest" };

export default function BacktestPage() {
  return <div className="shell workspace">
    <PageTitle section="Research" title="Backtest" action={<Link className="text-link" href="/dashboard?tab=portfolio">Four-agent portfolio ↗</Link>}>Inspect a historical long/short simulation, its equity curve, and final positions.</PageTitle>
    <Suspense fallback={<State>Loading backtest…</State>}><BacktestView/></Suspense>
  </div>;
}
