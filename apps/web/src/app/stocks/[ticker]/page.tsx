import type { Metadata } from "next";
import { StockReturnLink } from "@/components/stock-return-link";
import { StockDetail } from "./detail";
import { stockContext, type StockQuery } from "@/lib/stock-context";

type Props = { params: Promise<{ ticker: string }>; searchParams: Promise<StockQuery> };

function listingSymbol(segment: string) {
  try { return decodeURIComponent(segment).toUpperCase(); }
  catch { return segment.toUpperCase(); }
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  return { title: listingSymbol((await params).ticker) };
}

export default async function TickerPage({ params, searchParams }: Props) {
  const ticker = listingSymbol((await params).ticker);
  const context = stockContext(await searchParams);
  return <div className="shell workspace">
    <StockReturnLink/>
    <StockDetail key={ticker} ticker={ticker} {...context}/>
  </div>;
}
