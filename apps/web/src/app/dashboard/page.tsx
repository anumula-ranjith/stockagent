import { Suspense } from "react";
import { State } from "@/components/presentation";
import { Tuner } from "./tuner";

export const metadata = { title: "Four-agent stock ranker" };

export default function DashboardPage() {
  return <Suspense fallback={<State>Loading the stock ranker…</State>}><Tuner/></Suspense>;
}
