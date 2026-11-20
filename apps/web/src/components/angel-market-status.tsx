"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { dateLabel } from "@/lib/utils";
import styles from "./angel-market-status.module.css";

type MarketStatus = components["schemas"]["MarketStatus"];
const captureLabels: Record<MarketStatus["scheduled_status"], string> = {
  complete: "Successful", partial: "Partial update", failed: "Failed", upcoming: "Scheduled",
  awaiting_result: "Awaiting confirmation", unrecorded: "No run result recorded", market_closed: "No scheduled session",
};
const ist = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit", hour12: true,
});
const timestamp = (value: string) => ist.format(new Date(value)) + " IST";

export function AngelMarketStatus({user}: {user: string}) {
  const query = useQuery({
    queryKey: ["screener-market-status", user],
    queryFn: ({signal}) => api<MarketStatus>("/screener/market-status", {signal}),
    refetchInterval: 30_000, refetchOnWindowFocus: "always",
  });
  const data = query.data;
  if (!data) return <div className={styles.feed} role="status">{query.isError
    ? "Market update status unavailable." : "Checking Angel One and the scheduled update…"}</div>;
  const update = data.last_update;
  return <section className={styles.feed} aria-label="Market data status">
    <div><span>Angel One connection</span>
      <strong className={data.connected === true ? styles.up : undefined}>{data.connected === null ? "Status unavailable" : data.connected ? "Connected" : "Disconnected"}</strong>
      {data.expires_at && <small>Session expires {timestamp(data.expires_at)}</small>}
    </div>
    <div><span>Last successful price and volume update</span>
      <strong>{update ? timestamp(update.completed_at) : "No successful update recorded"}</strong>
      {update && <small>{update.method} · Trading session {dateLabel(update.trade_date)}</small>}
    </div>
    <div><span>3:16 p.m. IST · Angel One price and volume</span>
      <strong className={data.scheduled_status === "complete" ? styles.up : undefined}>{captureLabels[data.scheduled_status]}</strong>
      <small>{data.scheduled_ended_at ? timestamp(data.scheduled_ended_at) : dateLabel(data.scheduled_date)}</small>
    </div>
    {query.isError && <small role="status">Status refresh failed. Showing the last check.</small>}
  </section>;
}
