"use client";

import { Moon, Sun, Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import dynamic from "next/dynamic";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { rankingQuery } from "@/lib/ranking-query";
import { screenQuery } from "@/lib/screener-query";
import { savedScreen } from "@/lib/screen-filters";
import { api } from "@/lib/api";
import { useSession, usesClerk } from "./providers";
import { MarketSelect } from "./market-select";
import { Button } from "./ui/button";

const ClerkSignOut = dynamic(() => import("./clerk-sign-out"), { ssr: false });
const links = [
  ["/", "Home"], ["/dashboard", "Dashboard"], ["/screener", "Screener"], ["/stocks", "Stocks"],
  ["/portfolio", "Portfolio"], ["/watchlist", "Watchlists"],
  ["/backtest", "Backtest"],
] as const;

export function Header() {
  const pathname = usePathname();
  const session = useSession();
  const client = useQueryClient();
  function warmPage(href: string) {
    if (href === "/stocks") {
      void client.prefetchQuery({queryKey: ["universe"], queryFn: ({signal}) => api("/universe", {signal})});
    }
    const user = session.data?.id;
    if (!user) return;
    if (href === "/" || href === "/dashboard") void client.prefetchQuery(rankingQuery(user));
    if (href === "/screener") void client.prefetchQuery(screenQuery(user, savedScreen(user)));
    const reads: Record<string, [string, string]> = {
      "/backtest": ["latest-backtest", "/backtest/latest"],
      "/portfolio": ["my-portfolios", "/portfolios"],
      "/watchlist": ["my-watchlists", "/watchlists"],
    };
    const read = reads[href];
    if (read) void client.prefetchQuery({queryKey: [read[0], user], queryFn: ({signal}) => api(read[1], {signal})});
  }
  const { resolvedTheme, setTheme } = useTheme();
  const [menu, setMenu] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [sessionError, setSessionError] = useState(false);
  const switchTheme = () => setTheme(resolvedTheme === "dark" ? "light" : "dark");
  async function logout() {
    setSigningOut(true);
    try { await api("/logout", { method: "POST" }); window.location.assign("/"); }
    catch { setSigningOut(false); setSessionError(true); }
  }
  return <header className="topbar">
    <div className="shell topbar-inner">
      <Link href="/" className="wordmark" aria-label="QUANTORA home">
        <span className="brand-mark" aria-hidden="true">Q</span>QUANTORA
      </Link>
      <nav className={menu ? "main-nav is-open" : "main-nav"} aria-label="Main navigation">
        {links.map(([href, label]) => <Link key={href} href={href} onMouseEnter={() => warmPage(href)} onFocus={() => warmPage(href)}
          onClick={() => {warmPage(href); setMenu(false);}}
          aria-current={pathname === href || (href !== "/" && pathname.startsWith(href + "/")) ? "page" : undefined}>
          {label}
        </Link>)}
        {session.data?.is_admin && <Link href="/admin">Admin</Link>}
        {session.data?.is_admin && <a href="/_admin/rq/" aria-current={pathname.startsWith("/_admin/rq") || pathname.startsWith("/job-queues") ? "page" : undefined}>Job queues</a>}
      </nav>
      <div className="top-actions">
        <button className="icon-button" type="button" aria-label={resolvedTheme === "dark" ? "Switch to light theme" : "Switch to dark theme"} title={resolvedTheme === "dark" ? "Light theme" : "Dark theme"} onClick={switchTheme}>{resolvedTheme === "dark" ? <Sun size={19}/> : <Moon size={19}/>}</button>
        {session.data && !usesClerk && <Link className="text-link" href="/account">Account</Link>}
        {session.data
          ? usesClerk ? <ClerkSignOut/> : <Button variant="ghost" onClick={logout} disabled={signingOut}>Sign out</Button>
          : <Button variant="secondary" asChild><Link href={"/login?next=" + encodeURIComponent(pathname)}>Sign in</Link></Button>}
        <button className="icon-button menu-toggle" type="button" aria-label={menu ? "Close navigation" : "Open navigation"}
          aria-expanded={menu} onClick={() => setMenu(!menu)}>{menu ? <X size={21}/> : <Menu size={21}/>}</button>
        <MarketSelect/>
      </div>
      {sessionError && <p role="status" className="header-error">Sign-out failed. Try again.</p>}
    </div>
  </header>;
}

export function Footer() {
  return <footer className="footer"><div className="shell footer-inner">
    <div><Link href="/" className="wordmark">QUANTORA</Link><p>Invest Smarter. Think Quant.</p></div>
    <nav aria-label="Footer navigation"><Link href="/dashboard">Dashboard</Link><Link href="/screener">Screener</Link><Link href="/methodology">Methodology</Link><Link href="/assistant">AI Assistant</Link></nav>
    <small>© {new Date().getFullYear()} QUANTORA · Research tools for NSE equities.</small>
  </div></footer>;
}
