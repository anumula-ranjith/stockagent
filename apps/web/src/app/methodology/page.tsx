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
          <p>The screener uses active constituents in the locally recorded official Nifty 500 membership. The wider stock directory also includes NSE derivatives names. The four-agent dashboard ranks eligible constituents using the observations available for the chosen date.</p>
        </section>
        <section id="agents"><h2 className="section-title">The four agents</h2>
          <h3>Technical</h3><p>Price trends combine trailing returns, annualized volatility, moving averages, and RSI.</p>
          <h3>Momentum</h3><p>Relative performance captures three-month and six-month returns and the 12–1 month momentum signal.</p>
          <h3>Sentiment</h3><p>Headline polarity and news coverage help distinguish the level and breadth of sentiment.</p>
          <h3>Fundamental</h3><p>EODHD and entitled FactSet inputs support value, quality, growth, balance-sheet health and shareholder yield. Adjust the pillar weights and select individual factors on the dashboard. Coverage varies by company and reporting date.</p>
        </section>
        <section id="combiner"><h2 className="section-title">Ranking methods</h2>
          <ul>
            <li><strong>Weighted composite.</strong> An average of the four agents using normalized weights.</li>
            <li><strong>Consensus.</strong> Require agreement across a chosen number of agents.</li>
            <li><strong>Hybrid.</strong> Apply agreement thresholds alongside the composite ranking.</li>
          </ul>
          <p>The ranking book applies the configured sector cap to each side. Use the <Link href="/dashboard" className="text-link">dashboard</Link> to compare dates and weights.</p>
        </section>
        <section id="point-in-time"><h2 className="section-title">Point-in-time data</h2>
          <p><code>effective_date</code> records the period a fact describes. <code>known_date</code> records when the fact was available. Point-in-time factor queries use the known date to avoid using information before it became available.</p>
        </section>
        <section id="backtests"><h2 className="section-title">Backtests</h2>
          <p>The dashboard portfolio tab replays the chosen settings. Historical membership mode uses observations known at each rebalance. Current-cohort mode studies today’s constituents over stored price history and is subject to survivorship bias and later price adjustments. Periods with insufficient point-in-time coverage can yield no eligible portfolio. The backtest page also provides the existing research strategy and stored reports.</p>
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
