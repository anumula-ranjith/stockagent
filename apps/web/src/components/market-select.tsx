"use client";

import { ChevronDown } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";

export function MarketSelect() {
  const pathname = usePathname();
  const router = useRouter();
  const us = pathname === "/us" || pathname.startsWith("/us/");
  const section = pathname.replace(/^\/(us|datadaily)(?=\/|$)/, "").split("/")[1];
  const shared = ["dashboard", "stocks", "screener", "watchlist", "news"].includes(section);
  function switchMarket(market: string) {
    const destination = shared ? "/" + section : "";
    router.push(market === "us" ? "/us" + destination : destination === "/news" ? "/" : destination || "/");
  }
  return <label className="market-select">
    <select aria-label="Stock market" title="Switch stock market" value={us ? "us" : "india"}
      onChange={event => switchMarket(event.target.value)}>
      <option value="india">India</option>
      <option value="us">United States</option>
    </select>
    <ChevronDown size={14} aria-hidden="true"/>
  </label>;
}
