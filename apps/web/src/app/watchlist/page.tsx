import { PageTitle } from "@/components/presentation";
import { WatchlistWorkspace } from "./watchlist-workspace";

export const metadata = {title:"Watchlists"};
export default function WatchlistPage() {
  return <div className="shell workspace"><PageTitle section="Personal workspace" title="Watchlists">
    Organize NSE companies, keep research notes, and monitor price levels against the latest stored close.
  </PageTitle><WatchlistWorkspace/></div>;
}
