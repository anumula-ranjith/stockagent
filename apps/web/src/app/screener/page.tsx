import { PageTitle } from "@/components/presentation";
import { Screener } from "./screener";

export const metadata = { title: "Nifty 500 screener" };

export default function ScreenerPage() {
  return <div className="shell workspace">
    <PageTitle section="Equity research" title="Nifty 500 screener">
      Choose an index, market-cap segment or industry, then screen its stocks by trading range, EMA and MACD.
    </PageTitle>
    <Screener/>
  </div>;
}
