import { Suspense } from "react";
import { PageTitle, State } from "@/components/presentation";
import { PortfolioWorkspace } from "./portfolio-workspace";

export const metadata = {title:"My portfolios"};
export default function PortfolioPage() {
  return <div className="shell workspace"><PageTitle section="Personal workspace" title="My portfolios">
    Track manual NSE trades, cash, holdings and FIFO profit and loss against locally stored EOD prices.
  </PageTitle><Suspense fallback={<State>Loading portfolio…</State>}><PortfolioWorkspace/></Suspense></div>;
}
