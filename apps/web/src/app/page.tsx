import { Activity, ArrowRight, ChartNoAxesCombined, Search } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { HomeSnapshot } from "./home-snapshot";

const research = [
  { href: "/dashboard", title: "Tune the composite", detail: "Adjust the four agent weights and see how the long and short rankings change.", icon: Activity },
  { href: "/stocks", title: "Explore the universe", detail: "Filter equities by sector and inspect price history, scores, and headlines.", icon: Search },
  { href: "/backtest", title: "Review a backtest", detail: "Inspect the equity curve and the final book, with a private report download.", icon: ChartNoAxesCombined },
];

export default function HomePage() {
  return <>
    <section className="market-hero">
      <div className="hero-photo"><Image src="/market-district.webp" alt="" fill priority sizes="(max-width: 780px) 100vw, 70vw"/></div>
      <div className="shell hero-inner">
        <p className="eyebrow">Nifty 200 · Equity research</p>
        <h1>Four signals.<br/>One market view.</h1>
        <p className="hero-copy">Rank NSE equities by technicals, sentiment, momentum, and fundamentals. Follow each signal from screen to backtest.</p>
        <div className="hero-actions">
          <Button asChild><Link href="/dashboard">Open dashboard <ArrowRight size={17}/></Link></Button>
          <Button variant="secondary" asChild><Link href="/stocks">Explore stocks</Link></Button>
        </div>
      </div>
    </section>
    <div className="shell">
      <HomeSnapshot/>
      <section className="home-section home-tools" aria-label="Research tools">
        {research.map(({ href, title, detail, icon: Icon }) => <Link key={href} href={href}>
          <Icon size={22} aria-hidden="true"/><h3>{title} <ArrowRight size={16}/></h3><p>{detail}</p>
        </Link>)}
      </section>
    </div>
  </>;
}
