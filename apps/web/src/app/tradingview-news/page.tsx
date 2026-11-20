import { CompanyNews } from "../news/company-news";

export const metadata = { title: "Market Headlines" };

export default function MarketHeadlinesPage() {
  return (
    <div className="shell workspace">
      <header className="page-title">
        <div>
          <h1>Market Headlines</h1>
          <p className="lede">Indian market headlines from publisher feeds. This page checks for new stories every minute.</p>
        </div>
        <a className="text-link" href="https://in.tradingview.com/markets/stocks-india/news/"
          target="_blank" rel="noopener noreferrer">TradingView India news ↗</a>
      </header>
      <CompanyNews initialKind="headline" nextPath="/tradingview-news" />
    </div>
  );
}
