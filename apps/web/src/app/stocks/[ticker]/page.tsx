import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
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
    <Link href="/stocks" className="text-link mb-4"><ArrowLeft size={16}/> Stocks</Link>
    <StockDetail key={ticker} ticker={ticker} {...context}/>
  </div>;
}
