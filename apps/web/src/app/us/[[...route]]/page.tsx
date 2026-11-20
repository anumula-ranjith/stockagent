import {notFound} from "next/navigation";
import {UsWorkspace} from "../workspace";

export default async function UsPage({params}:{params:Promise<{route?:string[]}>}) {
  const {route=[]}=await params;
  const [page="dashboard",ticker]=route;
  if (!["dashboard","stocks","screener","watchlist","news"].includes(page) ||
      route.length>2 || (ticker && (page!=="stocks" || !/^[A-Z0-9.-]{1,15}$/.test(ticker)))) notFound();
  return <UsWorkspace page={page} ticker={ticker}/>;
}
