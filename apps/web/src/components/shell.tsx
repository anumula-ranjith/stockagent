"use client";

import { ArrowUpRight, Moon, Sun, Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import dynamic from "next/dynamic";
import { useState } from "react";
import { api } from "@/lib/api";
import { useSession, usesClerk } from "./providers";
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
        {links.map(([href, label]) => <Link key={href} href={href} onClick={() => setMenu(false)}
          aria-current={pathname === href || (href !== "/" && pathname.startsWith(href + "/")) ? "page" : undefined}>
          {label}
        </Link>)}
        {session.data?.is_admin && <a href="/_admin/rq/">Job queues <ArrowUpRight size={14}/></a>}
      </nav>
      <div className="top-actions">
        <span className="market-chip"><i/>NSE India</span>
        <button className="icon-button" type="button" aria-label={resolvedTheme === "dark" ? "Switch to light theme" : "Switch to dark theme"} title={resolvedTheme === "dark" ? "Light theme" : "Dark theme"} onClick={switchTheme}>{resolvedTheme === "dark" ? <Sun size={19}/> : <Moon size={19}/>}</button>
        {session.data && !usesClerk && <Link className="text-link" href="/account">Account</Link>}
        {session.data
          ? usesClerk ? <ClerkSignOut/> : <Button variant="ghost" onClick={logout} disabled={signingOut}>Sign out</Button>
          : <Button variant="secondary" asChild><Link href={"/login?next=" + encodeURIComponent(pathname)}>Sign in</Link></Button>}
        <button className="icon-button menu-toggle" type="button" aria-label={menu ? "Close navigation" : "Open navigation"}
          aria-expanded={menu} onClick={() => setMenu(!menu)}>{menu ? <X size={21}/> : <Menu size={21}/>}</button>
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
