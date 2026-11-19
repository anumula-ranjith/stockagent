"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Download, Play } from "lucide-react";
import dynamic from "next/dynamic";
import { parseAsString, useQueryState } from "nuqs";
import { useEffect, useState, type FormEvent } from "react";
import { z } from "zod";
import { DataTable } from "@/components/data-table";
import { StockTicker } from "@/components/stock-ticker";
import { SignInNotice, State } from "@/components/presentation";
import { useSession } from "@/components/providers";
import { Button } from "@/components/ui/button";
import { api, type JobRef, type JobStatus } from "@/lib/api";
import { reportSchema, type Report } from "@/lib/report";
import { dateLabel } from "@/lib/utils";

const EquityChart = dynamic(() => import("@/components/research-charts").then(module => module.EquityChart), {
  ssr: false, loading: () => <State>Loading equity chart…</State>,
});
const inputSchema = z.object({ start: z.iso.date(), end: z.iso.date(), n: z.number().int().min(3).max(30) })
  .refine(values => values.start <= values.end, "Start date must be on or before end date.");
const percentage = new Intl.NumberFormat("en-IN", { style: "percent", maximumFractionDigits: 2, minimumFractionDigits: 2 });
const bookColumns: ColumnDef<{ ticker: string }>[] = [
  { id: "rank", header: "#", enableSorting: false, cell: ({ row }) => row.index + 1 },
  { accessorKey: "ticker", header: "Ticker", cell: ({ row }) => <StockTicker ticker={row.original.ticker}/> },
];
const terminal = (status?: string) => !!status && ["finished", "failed", "stopped", "canceled"].includes(status);

function ReportView({ report, artifact }: { report: Report; artifact?: string | null }) {
  const summary = [
    ["Total return", percentage.format(report.total_return), report.total_return >= 0 ? "positive" : "negative"],
    ["Annual return", percentage.format(report.annual_return), ""],
    ["Sharpe", report.sharpe.toFixed(2), ""],
    ["Max drawdown", percentage.format(report.max_drawdown), "negative"],
    ["Annual volatility", percentage.format(report.annual_vol), ""],
  ];
  return <>
    <div className="metrics">{summary.map(([label, value, color]) => <div className="metric" key={label}>
      <span>{label}</span><strong className={color}>{value}</strong>
    </div>)}</div>
    <div className="surface">
      <div className="surface-top"><div><h2 className="section-title">Equity curve</h2>
        <p className="subtle">{dateLabel(report.start)} to {dateLabel(report.end)} · {report.n_days} trading days</p></div>
        {artifact && /^https?:\/\//i.test(artifact) && <Button asChild variant="secondary">
          <a href={artifact} target="_blank" rel="noopener noreferrer"><Download size={16}/> Download JSON</a>
        </Button>}
      </div>
      <div className="chart-pad"><EquityChart data={report.equity_curve}/></div>
    </div>
    <div className="two-books">
      {([["Final longs", report.longs_last], ["Final shorts", report.shorts_last]] as const).map(([label, tickers]) =>
        <div className="surface" key={label}><div className="surface-top"><h2 className="section-title">{label}</h2></div>
          <DataTable data={tickers.map(ticker => ({ ticker }))} columns={bookColumns} label={label} empty="No positions in this book."/>
        </div>)}
    </div>
  </>;
}

export function BacktestView() {
  const session = useSession();
  const queryClient = useQueryClient();
  const [jobId, setJobId] = useQueryState("job", parseAsString);
  const [range, setRange] = useState({ start: "", end: "", n: 10 });
  const [validation, setValidation] = useState("");
  useEffect(() => {
    const end = new Date();
    const start = new Date(end);
    start.setUTCFullYear(start.getUTCFullYear() - 1);
    setRange(current => ({ ...current, start: start.toISOString().slice(0,10), end: end.toISOString().slice(0,10) }));
  }, []);
  const latestKey = ["latest-backtest", session.data?.id];
  const latest = useQuery({
    queryKey: latestKey, enabled: !!session.data && !jobId,
    queryFn: ({ signal }) => api<unknown>("/backtest/latest", { signal }),
  });
  const job = useQuery({
    queryKey: ["job", session.data?.id, jobId],
    enabled: !!session.data && !!jobId,
    queryFn: ({ signal }) => api<JobStatus>("/jobs/" + encodeURIComponent(jobId!), { signal }),
    refetchInterval: query => query.state.error ? false : terminal(query.state.data?.status)
      ? query.state.data?.result_url ? 240_000 : false
      : 1500,
    staleTime: 0,
    refetchOnWindowFocus: true,
  });
  const submission = useMutation({
    mutationFn: (values: z.infer<typeof inputSchema>) => {
      const query = new URLSearchParams({ ...values, n: String(values.n) });
      return api<JobRef>("/backtest/run?" + query, { method: "POST" });
    },
    onSuccess: response => {
      void setJobId(response.job_id);
      void queryClient.invalidateQueries({ queryKey: latestKey });
    },
  });
  const admin = !!session.data?.is_admin;
  const processing = !!jobId && !job.isError && !terminal(job.data?.status);
  const result = reportSchema.safeParse(jobId ? job.data?.result : latest.data);

  function run(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const input = inputSchema.safeParse(range);
    if (!input.success) {
      setValidation(input.error.issues[0].message);
      return;
    }
    setValidation("");
    submission.mutate(input.data);
  }
  if (session.isPending) return <State>Checking your session…</State>;
  if (session.isError) return <State error>Session unavailable. Try again shortly.</State>;
  if (!session.data) return <SignInNotice next="/backtest">Sign in to view backtest reports. Administrators can start new runs.</SignInNotice>;
  return <div className="split">
    <aside className="surface">
      <h2 className="section-title">Run configuration</h2>
      <form className="controls" onSubmit={run}>
        <label className="field">Start date<input type="date" value={range.start} required
          disabled={!admin} onChange={event => setRange(current => ({ ...current, start: event.target.value }))}/></label>
        <label className="field">End date<input type="date" value={range.end} required
          disabled={!admin} onChange={event => setRange(current => ({ ...current, end: event.target.value }))}/></label>
        <label className="field">Names per side<input type="number" value={range.n || ""} min={3} max={30}
          required disabled={!admin} onChange={event => setRange(current => ({ ...current, n: Number(event.target.value) }))}/></label>
        <Button type="submit" disabled={!admin || submission.isPending || processing}><Play size={16}/> Run backtest</Button>
        {!admin && <p className="subtle">Only administrators can start a run.</p>}
        {validation && <p className="state-error" role="alert">{validation}</p>}
        {submission.isError && <p className="state-error" role="alert">{submission.error.message}</p>}
      </form>
    </aside>
    <section className="stack">
      {jobId && <div className="surface surface-top">
        <div><h2 className="section-title">Job status</h2>
          <p className="job-label">{jobId}</p></div>
        <strong role="status">{job.data?.status ?? (job.isError ? "Unavailable" : "Queued")}</strong>
        <Button variant="ghost" onClick={() => void setJobId(null)}>Latest report</Button>
      </div>}
      {job.isError ? <div className="surface"><State error>{job.error.message} <button className="text-link" onClick={() => void job.refetch()}>Retry</button></State></div>
        : processing ? <div className="surface"><State>The worker is processing your backtest.</State></div>
        : job.data && terminal(job.data.status) && job.data.status !== "finished" ? <div className="surface"><State error>{job.data.error ?? "The job ended before producing a report."}</State></div>
        : latest.isError ? <div className="surface"><State error>{latest.error.message}</State></div>
        : !jobId && latest.isPending ? <div className="surface"><State>Loading the latest report…</State></div>
        : result.success ? <ReportView report={result.data} artifact={job.data?.result_url}/>
        : <div className="surface"><State>{jobId ? "This job returned no backtest report." : "No backtest reports are available yet."}</State></div>}
    </section>
  </div>;
}
