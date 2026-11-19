"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { dateLabel } from "@/lib/utils";

type History = components["schemas"]["ScheduledPriceHistory"];
const outcomes = {ok: "Successful", partial: "Partial update", failed: "Failed"} as const;
const finishTime = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata", hour: "numeric", minute: "2-digit", second: "2-digit", hour12: true,
});

export function ScheduledPriceHistory({user}: {user: string}) {
  const history = useInfiniteQuery({
    queryKey: ["scheduled-price-history", user],
    initialPageParam: null as string | null,
    queryFn: ({pageParam, signal}) => api<History>("/admin/angel-one/scheduled-runs"
      + (pageParam ? "?before=" + encodeURIComponent(pageParam) : ""), {signal}),
    getNextPageParam: page => page.next_before,
    refetchInterval: 30_000, refetchOnWindowFocus: "always",
  });
  const runs = history.data?.pages.flatMap(page => page.runs) ?? [];
  return <section className="surface" aria-labelledby="scheduled-price-history">
    <div className="surface-top"><h2 id="scheduled-price-history">Angel One run history · 3:16 p.m. IST</h2></div>
    <div className="table-scroll"><table aria-labelledby="scheduled-price-history">
      <thead><tr><th scope="col">Trading date</th><th scope="col">Finished at (IST)</th><th scope="col">Price and volume update</th></tr></thead>
      <tbody>{runs.map(run => <tr key={run.trade_date}>
        <td>{dateLabel(run.trade_date)}</td>
        <td><time dateTime={run.finished_at}>{finishTime.format(new Date(run.finished_at))}</time></td>
        <td>{outcomes[run.status]}</td>
      </tr>)}
      {!runs.length && <tr><td colSpan={3}>{history.isPending ? "Loading run history…" : history.isError
        ? "Run history could not be loaded." : "No scheduled Angel One runs have been recorded yet."}</td></tr>}
      </tbody>
    </table></div>
    {history.isError && runs.length > 0 && <p role="status">Run history could not be refreshed.</p>}
    {history.hasNextPage && <div className="table-paging"><Button variant="secondary" type="button"
      disabled={history.isFetching} onClick={() => void history.fetchNextPage()}>Show older runs</Button></div>}
  </section>;
}
