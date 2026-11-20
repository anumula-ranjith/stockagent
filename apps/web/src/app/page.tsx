import { Activity, ArrowRight, ChartNoAxesCombined, Search } from "lucide-react";
import Link from "next/link";
import { HomeHero } from "./home-hero";
import { HomeNews } from "./home-news";
import { HomeSnapshot } from "./home-snapshot";

const research = [
  { href: "/dashboard", n: "01", eyebrow: "Weight", title: "Tune the composite", detail: "Adjust the four agent weights and watch the long and short lists re-rank.", icon: Activity },
  { href: "/stocks", n: "02", eyebrow: "Screen", title: "Explore the universe", detail: "Filter by sector and inspect price history, agent scores and headlines.", icon: Search },
  { href: "/datadaily/backtest", n: "03", eyebrow: "Test", title: "Review a backtest", detail: "Inspect the equity curve and final book, with a private report download.", icon: ChartNoAxesCombined },
];

export default function HomePage() {
  return <>
    <HomeHero/>
    <div className="shell">
      <HomeSnapshot/>
      <HomeNews/>
      <section className="home-section home-tools" aria-label="Research tools">
        {research.map(({ href, n, eyebrow, title, detail, icon: Icon }) => <Link key={href} href={href}>
          <p className="home-tool-eyebrow"><span>{n}</span> · {eyebrow}</p>
          <h3>{title} <ArrowRight size={16}/></h3>
          <p>{detail}</p>
          <Icon size={18} aria-hidden="true" className="home-tool-icon"/>
        </Link>)}
      </section>
    </div>
  </>;
}
