import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { PageTitle } from "@/components/presentation";
import { StockDetail } from "./detail";

type Props = { params: Promise<{ ticker: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  return { title: (await params).ticker.toUpperCase() };
}

export default async function TickerPage({ params }: Props) {
  const ticker = (await params).ticker.toUpperCase();
  return <div className="shell workspace">
    <Link href="/stocks" className="text-link mb-4"><ArrowLeft size={16}/> Stocks</Link>
    <PageTitle title={ticker}>NSE equity · Prices, agent scores, and headlines</PageTitle>
    <StockDetail ticker={ticker}/>
  </div>;
}
