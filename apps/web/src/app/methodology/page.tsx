import Link from "next/link";
import { PageTitle } from "@/components/presentation";

export const metadata = { title: "Methodology" };

const sections = [
  ["universe", "Universe and scoring"], ["agents", "The four agents"], ["combiner", "Ranking methods"],
  ["point-in-time", "Point-in-time data"], ["backtests", "Backtests"], ["sources", "Data sources"],
] as const;

export default function MethodologyPage() {
  return <div className="shell workspace">
    <PageTitle title="Methodology">How the agents score stocks, how the ranking book is assembled, and what the backtest measures.</PageTitle>
    <div className="method-layout">
      <nav className="method-nav" aria-label="On this page">
        {sections.map(([id,label]) => <a key={id} href={"#" + id}>{label}</a>)}
      </nav>
      <article className="method-content">
        <section id="universe"><h2 className="section-title">Universe and scoring</h2>
          <p>The research universe is seeded from Nifty 200 constituents on NSE India. EODHD symbols use the <code>.NSE</code> suffix. Factor inputs are ranked across the universe and agent scores are expressed on a 0–100 scale. The combiner uses a neutral score of 50 for missing agent values.</p>
        </section>
        <section id="agents"><h2 className="section-title">The four agents</h2>
          <h3>Technical</h3><p>Price trends combine trailing returns, annualized volatility, moving averages, and RSI.</p>
          <h3>Momentum</h3><p>Relative performance captures three-month and six-month returns and the 12–1 month momentum signal.</p>
          <h3>Sentiment</h3><p>Headline polarity and news coverage help distinguish the level and breadth of sentiment.</p>
          <h3>Fundamental</h3><p>The model defines value, quality, growth, balance-sheet health, and shareholder yield. The current fundamental agent uses a neutral score until the vendor fundamentals pipeline supplies its inputs.</p>
        </section>
        <section id="combiner"><h2 className="section-title">Ranking methods</h2>
          <ul>
            <li><strong>Weighted composite.</strong> An average of the four agents using normalized weights.</li>
            <li><strong>Consensus.</strong> An equal-weight average of the four scores in the current engine.</li>
            <li><strong>Hybrid.</strong> A 70% weighted composite and 30% weakest-agent score.</li>
          </ul>
          <p>The ranking book applies the configured sector cap to each side. Use the <Link href="/dashboard" className="text-link">dashboard</Link> to compare dates and weights.</p>
        </section>
        <section id="point-in-time"><h2 className="section-title">Point-in-time data</h2>
          <p><code>effective_date</code> records the period a fact describes. <code>known_date</code> records when the fact was available. Point-in-time factor queries use the known date to avoid using information before it became available.</p>
        </section>
        <section id="backtests"><h2 className="section-title">Backtests</h2>
          <p>The current research backtest ranks technical and momentum scores at monthly rebalance dates and simulates equal-weight long and short positions using adjusted prices. The report shows trading days, equity, drawdown, return, volatility, and the final holdings.</p>
          <p>Slippage, fees, short borrow, and execution assumptions belong to the configured strategy model. The current prototype simulation does not apply all of them to realized returns.</p>
        </section>
        <section id="sources"><h2 className="section-title">Data sources</h2>
          <ul><li>EODHD supplies NSE prices, corporate actions, headlines, and sentiment where available.</li>
            <li>FactSet access is licensed. Rankings and backtest reports require sign-in.</li>
            <li>FRED supports optional cross-market research. Alpaca Paper is a separate execution sandbox for US equities.</li></ul>
        </section>
      </article>
    </div>
  </div>;
}
