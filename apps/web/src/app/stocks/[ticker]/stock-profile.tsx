"use client";

import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { SignInNotice, State } from "@/components/presentation";
import { useSession } from "@/components/providers";
import { api, ApiError } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { dateLabel, rupees } from "@/lib/utils";
import styles from "./stock-profile.module.css";

type Profile = components["schemas"]["Profile"];
type Metric = Profile["fundamentals"][number];

const names: Record<string, string> = {
  eodhd: "EODHD", nse_indices: "NSE Indices", nse: "NSE", nse_bhavcopy: "NSE Bhavcopy",
  nse_fo: "NSE F&O", seed_csv: "Local security directory",
};
const headlineKeys = new Set(["market_cap","eps_ttm","pe_ttm","dividend_yield"]);
const decimal = new Intl.NumberFormat("en-IN", {maximumFractionDigits: 2});
const count = new Intl.NumberFormat("en-IN", {maximumFractionDigits: 0});
const money = (n: number | null) => n == null ? "—" : rupees.format(n);
const from = (source: string, date: string) => `${names[source] ?? source} · ${dateLabel(date)}`;
function metricValue(m: Metric) {
  if (m.unit === "INR") return `₹${decimal.format(m.value / 10_000_000)} cr`;
  if (m.unit === "INR/share") return rupees.format(m.value);
  if (m.unit === "fraction") return `${decimal.format(100 * m.value)}%`;
  if (m.unit === "multiple") return `${decimal.format(m.value)}×`;
  return decimal.format(m.value);
}
function Detail({label, children, note}: {label: string; children: ReactNode; note?: string}) {
  return <div className={styles.item}><dt>{label}</dt><dd>{children}{note && <small>{note}</small>}</dd></div>;
}
function Metrics({rows, empty}: {rows: Metric[]; empty: string}) {
  if (!rows.length) return <p className={styles.empty}>{empty}</p>;
  return <dl className={styles.grid}>{rows.map(m => <Detail key={m.key} label={m.label}
    note={from(m.source, m.asof)}>{metricValue(m)}</Detail>)}</dl>;
}
function ProfileData({data: p}: {data: Profile}) {
  const q = p.quote;
  return <section className={`surface ${styles.card}`} aria-label="Company and trading profile">
    <div className={styles.head}>
      <div>
        <h2>{p.company_name ?? p.ticker}</h2>
        <p className={styles.identifiers}>{[p.venue, p.ticker, p.series && `Series ${p.series}`, p.isin && `ISIN ${p.isin}`].filter(Boolean).join(" · ")}</p>
        {p.identity_source && p.identity_date && <small>Identity from {from(p.identity_source,p.identity_date)}</small>}
      </div>
      {q && <div className={styles.close}><span>Last traded close</span><strong>{money(q.close)}</strong>
        {q.change != null && q.change_pct != null && <p className={q.change < 0 ? "negative" : q.change > 0 ? "positive" : ""}>
          {q.change > 0 ? "+" : ""}{money(q.change)} ({q.change_pct > 0 ? "+" : ""}{decimal.format(q.change_pct)}%)
        </p>}
        <small>{from(q.source,q.date)}</small>
      </div>}
    </div>
    <div className={styles.block}>
      <dl className={styles.grid}>
        <Detail label="Industry" note={p.classification_source && p.classification_date ? from(p.classification_source,p.classification_date) : undefined}>{p.industry ?? "Unavailable"}</Detail>
        {p.sector && p.sector !== p.industry && <Detail label="Sector">{p.sector}</Detail>}
        <Detail label="Index size segment">{p.cap_segment ? p.cap_segment[0].toUpperCase() + p.cap_segment.slice(1) + " cap" : "Unclassified"}</Detail>
        <Detail label="Directory status">{p.active ? "Active" : "Inactive"}</Detail>
      </dl>
      {!!p.memberships.length && <div className={styles.members}>
        <span>Index and F&O membership</span><ul>{p.memberships.map(m =>
          <li key={m.code} title={`Observed ${dateLabel(m.observed_on)}`}>{m.name}</li>)}</ul>
      </div>}
    </div>
    <div className={styles.block}>
      <h3>Trading session</h3>
      {q ? <dl className={styles.grid}>
        <Detail label="Open">{money(q.open)}</Detail><Detail label="High">{money(q.high)}</Detail>
        <Detail label="Low">{money(q.low)}</Detail><Detail label="Volume">{count.format(q.volume)} {p.series === "RR" || p.series === "IV" ? "units" : "shares"}</Detail>
        <Detail label="Previous close" note={q.previous_date ? dateLabel(q.previous_date) : undefined}>{money(q.previous_close)}</Detail>
      </dl> : <p className={styles.empty}>No closing price is available for this security.</p>}
    </div>
    <div className={styles.block}>
      <h3>Fundamentals</h3>
      <Metrics rows={p.fundamentals.filter(m => headlineKeys.has(m.key))}
        empty="No headline fundamentals are available."/>
      {p.fundamentals.some(m => !headlineKeys.has(m.key)) &&
        <details className={styles.more}><summary>Valuation, growth and profitability</summary>
          <Metrics rows={p.fundamentals.filter(m => !headlineKeys.has(m.key))}
            empty="No additional fundamentals are available."/></details>}
    </div>
    <details className={styles.fold}><summary>Analyst estimates</summary>
      <Metrics rows={p.analyst} empty="No shareable analyst estimates are available."/></details>
    <details className={styles.fold}><summary>Reported earnings</summary>
      {!p.earnings.length ? <p className={styles.empty}>No earnings reports are available.</p> :
        <div className="table-scroll"><table><caption className={styles.caption}>The earnings feed omits the EPS reporting currency.</caption><thead><tr><th>Period end</th><th>Reported EPS</th><th>Consensus EPS</th><th>Surprise</th><th>Reported</th></tr></thead>
          <tbody>{p.earnings.map(e => <tr key={e.fiscal_period}><td>{e.fiscal_period}</td><td>{e.reported == null ? "—" : decimal.format(e.reported)}</td><td>{e.estimate == null ? "—" : decimal.format(e.estimate)}</td>
            <td>{e.surprise_pct == null ? "—" : decimal.format(e.surprise_pct) + "%"}</td><td>{from(e.source,e.report_date)}</td></tr>)}</tbody></table></div>}
    </details>
    <details className={styles.fold}><summary>Corporate actions</summary>
      {!p.actions.length ? <p className={styles.empty}>No corporate actions are available.</p> :
        <div className="table-scroll"><table><thead><tr><th>Ex-date</th><th>Action</th><th>Amount or ratio</th><th>Source</th></tr></thead>
          <tbody>{p.actions.map(a => <tr key={a.ex_date+a.kind}><td>{dateLabel(a.ex_date)}</td><td className={styles.capitalize}>{a.kind}</td>
            <td>{a.value == null ? "—" : a.unit.startsWith("INR/") ? money(a.value) + "/" + a.unit.slice(4) : `${decimal.format(a.value)} ${a.unit}`}</td>
            <td>{names[a.source] ?? a.source}</td></tr>)}</tbody></table></div>}
    </details>
  </section>;
}

export function StockProfile({ticker}: {ticker: string}) {
  const session = useSession();
  const encoded = encodeURIComponent(ticker);
  const query = useQuery({queryKey: ["stock-profile",ticker,session.data?.id], enabled: !!session.data,
    queryFn: ({signal}) => api<Profile>(`/stock-profile/${encoded}`,{signal})});
  if (session.isPending) return <State>Checking your session…</State>;
  if (session.isError) return <State error>{session.error.message}</State>;
  if (!session.data || query.error instanceof ApiError && query.error.status === 401)
    return <SignInNotice next={`/stocks/${encoded}`}>Sign in to view the company profile.</SignInNotice>;
  if (query.isError) return query.error instanceof ApiError && query.error.status === 404
    ? <State>No company profile is available for {ticker}.</State> : <State error>{query.error.message}</State>;
  if (!query.data) return <State>Loading company profile…</State>;
  return <ProfileData data={query.data}/>;
}
