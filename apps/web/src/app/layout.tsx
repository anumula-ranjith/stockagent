import type { Metadata } from "next";
import type { ReactNode } from "react";
import "@fontsource-variable/archivo";
import "./globals.css";
import { Providers } from "@/components/providers";
import { MarketHeader, MarketFooter } from "@/components/market-shell";
import "./us/market.css";


export const metadata: Metadata = {
  title: { default: "QUANTORA | Invest Smarter. Think Quant.", template: "%s | QUANTORA" },
  description: "Advanced Equity Intelligence & Quantitative Research. Screen the Nifty 500, compare ranking signals, and run equity backtests.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="en" suppressHydrationWarning><body>
    <a className="skip-link" href="#main">Skip to content</a>
    <Providers><MarketHeader/><main id="main">{children}</main><MarketFooter/></Providers>
  </body></html>;
}
