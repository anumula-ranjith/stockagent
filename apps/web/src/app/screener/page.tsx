import { PageTitle } from "@/components/presentation";
import { Screener } from "./screener";

export const metadata = { title: "Nifty 500 screener" };

export default function ScreenerPage() {
  return <div className="shell workspace">
    <PageTitle section="Equity research" title="Nifty 500 screener">
      Screen current constituents by their yearly trading range, EMA trends and MACD signals.
    </PageTitle>
    <Screener/>
  </div>;
}
