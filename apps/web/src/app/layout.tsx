import type { Metadata } from "next";
import type { ReactNode } from "react";
import "@fontsource-variable/archivo";
import "./globals.css";
import { Providers } from "@/components/providers";
import { Footer, Header } from "@/components/shell";
import { AssistantWidget } from "@/components/assistant-widget";

export const metadata: Metadata = {
  title: { default: "QUANTORA | Invest Smarter. Think Quant.", template: "%s | QUANTORA" },
  description: "Advanced Equity Intelligence & Quantitative Research. Screen the Nifty 500, compare ranking signals, and run equity backtests.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="en" suppressHydrationWarning><body>
    <a className="skip-link" href="#main">Skip to content</a>
    <Providers><Header/><main id="main">{children}</main><Footer/><AssistantWidget/></Providers>
  </body></html>;
}
