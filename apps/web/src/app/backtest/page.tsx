import { Suspense } from "react";
import { PageTitle, State } from "@/components/presentation";
import { BacktestView } from "./backtest-view";

export const metadata = { title: "Backtest" };

export default function BacktestPage() {
  return <div className="shell workspace">
    <PageTitle section="Research" title="Backtest">Inspect a historical long/short simulation, its equity curve, and final positions.</PageTitle>
    <Suspense fallback={<State>Loading backtest…</State>}><BacktestView/></Suspense>
  </div>;
}
