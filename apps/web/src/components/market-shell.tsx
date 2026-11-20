"use client";
import Link from "next/link";
import {usePathname} from "next/navigation";
import {Header,Footer} from "./shell";
import {AssistantWidget} from "./assistant-widget";

const pages=[["/us","Dashboard"],["/us/stocks","Stocks"],["/us/screener","Screener"],["/us/watchlist","Watchlist"],["/us/news","News"]];
export function MarketHeader(){
  const path=usePathname();
  const us=path==="/us" || path.startsWith("/us/");
  const section=(us?path.slice(3):path.replace(/^\/datadaily(?=\/)/,"")).split("/")[1] || "";
  const counterpart=["stocks","dashboard","screener","watchlist","news"].includes(section)?"/"+section:"/";
  return <><nav aria-label="Select stock market" className="market-selector">
    <div className="shell"><span>Market</span><Link href={us?(counterpart==="/news"?"/":counterpart):path} aria-current={!us?"true":undefined}>India</Link>
    <Link href={us?path:counterpart==="/" ? "/us" : "/us"+counterpart} aria-current={us?"true":undefined}>United States</Link></div>
  </nav>{us?<header className="us-header"><div className="shell"><Link className="wordmark" href="/us"><span className="brand-mark">Q</span>QUANTORA</Link>
    <nav aria-label="US market navigation">{pages.map(([href,name])=><Link key={href} href={href} aria-current={(path===href || (href==="/us/stocks" && path.startsWith("/us/stocks/")))?"page":undefined}>{name}</Link>)}</nav>
    <Link href="/account">Account</Link></div></header>:<Header/>}</>;
}
export function MarketFooter(){
  const path=usePathname();
  return path==="/us" || path.startsWith("/us/") ? <footer className="footer"><div className="shell footer-inner"><Link href="/us">QUANTORA · United States</Link><span>USD · New York time</span></div></footer> : <><Footer/><AssistantWidget/></>;
}
