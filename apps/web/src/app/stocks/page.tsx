import { Suspense } from "react";
import { PageTitle, State } from "@/components/presentation";
import { StockTable } from "./stock-table";

export const metadata = { title: "Stocks" };

export default function StocksPage() {
  return <div className="shell workspace">
    <PageTitle section="Universe" title="Stocks">Explore the NSE research universe by ticker, sector, and agent score.</PageTitle>
    <Suspense fallback={<State>Loading stocks…</State>}><StockTable/></Suspense>
  </div>;
}
