"use client";

import { Moon, Sun, Menu, X, Palette } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { rankingQuery } from "@/lib/ranking-query";
import { api } from "@/lib/api";
import { useSession, usesClerk } from "./providers";
import { MarketSelect } from "./market-select";
import { Button } from "./ui/button";

const ClerkSignOut = dynamic(() => import("./clerk-sign-out"), { ssr: false });
const links = [
  ["/", "Home"], ["/dashboard", "Dashboard"], ["/stocks", "Stocks"],
  ["/portfolio", "Portfolio"], ["/watchlist", "Watchlist"], ["/news", "News"],
  ["/tradingview-news", "Market Headlines"],
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
    const reads: Record<string, [string, string]> = {
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
      </nav>
      <div className="top-actions">
        <PalettePicker/>
        <button className="icon-button" type="button" aria-label={resolvedTheme === "dark" ? "Switch to light theme" : "Switch to dark theme"} title={resolvedTheme === "dark" ? "Light theme" : "Dark theme"} onClick={switchTheme}>{resolvedTheme === "dark" ? <Sun size={19}/> : <Moon size={19}/>}</button>
        {session.data
          ? usesClerk ? <ClerkSignOut/> : <Button variant="ghost" onClick={logout} disabled={signingOut}>Sign out</Button>
          : <Button variant="primary" asChild><Link href={"/login?next=" + encodeURIComponent(pathname)}>Sign in</Link></Button>}
        <button className="icon-button menu-toggle" type="button" aria-label={menu ? "Close navigation" : "Open navigation"}
          aria-expanded={menu} onClick={() => setMenu(!menu)}>{menu ? <X size={21}/> : <Menu size={21}/>}</button>
        <MarketSelect/>
      </div>
      {sessionError && <p role="status" className="header-error">Sign-out failed. Try again.</p>}
    </div>
  </header>;
}

const palettes = [
  { id: "default", name: "Indigo", color: "#4f46e5" },
  { id: "forest",  name: "Forest", color: "#059669" },
  { id: "slate",   name: "Slate",  color: "#334155" },
  { id: "rose",    name: "Rose",   color: "#e11d48" },
  { id: "amber",   name: "Amber",  color: "#d97706" },
] as const;
type PaletteId = (typeof palettes)[number]["id"];

function PalettePicker() {
  const [open, setOpen] = useState(false);
  const [palette, setPalette] = useState<PaletteId>("default");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const saved = (localStorage.getItem("palette") as PaletteId | null) || "default";
    setPalette(saved);
    if (saved === "default") document.documentElement.removeAttribute("data-palette");
    else document.documentElement.setAttribute("data-palette", saved);
  }, []);

  useEffect(() => {
    if (!open) return;
    function close(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function key(e: KeyboardEvent) { if (e.key === "Escape") setOpen(false); }
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", key); };
  }, [open]);

  function apply(id: PaletteId) {
    if (id === "default") document.documentElement.removeAttribute("data-palette");
    else document.documentElement.setAttribute("data-palette", id);
    localStorage.setItem("palette", id);
    setPalette(id);
    setOpen(false);
  }

  const current = palettes.find(p => p.id === palette) ?? palettes[0];

  return <div className="palette-picker" ref={ref}>
    <button className="icon-button palette-trigger" type="button"
      aria-label={`Accent color: ${current.name}. Open palette picker.`}
      aria-haspopup="menu" aria-expanded={open}
      onClick={() => setOpen(v => !v)}>
      <Palette size={16}/>
      <span className="palette-swatch" style={{background: current.color}} aria-hidden="true"/>
    </button>
    {open && <div className="palette-menu" role="menu">
      <p className="palette-menu-title">Accent color</p>
      {palettes.map(p => <button key={p.id} role="menuitemradio" aria-checked={palette === p.id}
        className="palette-option" onClick={() => apply(p.id)}>
        <span className="palette-swatch" style={{background: p.color}} aria-hidden="true"/>
        <span>{p.name}</span>
      </button>)}
    </div>}
  </div>;
}

export function Footer() {
  return <footer className="footer"><div className="shell footer-inner">
    <div><Link href="/" className="wordmark">QUANTORA</Link><p>Invest Smarter. Think Quant.</p></div>
    <nav aria-label="Footer navigation"><Link href="/dashboard">Dashboard</Link><Link href="/datadaily">Data Daily</Link></nav>
    <small>© {new Date().getFullYear()} QUANTORA · Research tools for NSE equities.</small>
  </div></footer>;
}
