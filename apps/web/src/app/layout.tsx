import type { Metadata } from "next";
import type { ReactNode } from "react";
import "@fontsource-variable/archivo";
import "@fontsource/instrument-serif/latin-400.css";
import "./globals.css";
import { Providers } from "@/components/providers";
import { Footer, Header } from "@/components/shell";

export const metadata: Metadata = {
  title: { default: "Stock Agents | NSE equity research", template: "%s | Stock Agents" },
  description: "Explore the Nifty 200, compare four ranking signals, and run point-in-time equity backtests.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="en" suppressHydrationWarning><body>
    <a className="skip-link" href="#main">Skip to content</a>
    <Providers><Header/><main id="main">{children}</main><Footer/></Providers>
  </body></html>;
}
