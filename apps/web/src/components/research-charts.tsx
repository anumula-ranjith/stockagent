"use client";

import {
  Area, AreaChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { useId } from "react";
import { agentLabels, agents, type Agent, type HistoryPoint } from "@/lib/api";
import type { Report } from "@/lib/report";
import { dateLabel } from "@/lib/utils";
import { State } from "./presentation";

const palette = ["var(--accent)", "#a37a32", "var(--long)", "var(--short)"];
const labelStyle = { color: "var(--ink)", background: "var(--panel)", borderColor: "var(--line)" };

export function EquityChart({ data }: { data: Report["equity_curve"] }) {
  const fill = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  if (!data.length) return <State>No equity points are available.</State>;
  return <div className="chart-area" role="img" aria-label="Backtest equity curve">
    <ResponsiveContainer width="100%" height="100%" minWidth={0}>
      <AreaChart data={data} margin={{ top: 12, right: 12, bottom: 4, left: 1 }}>
        <defs><linearGradient id={fill} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.27}/><stop offset="100%" stopColor="var(--accent)" stopOpacity={0.015}/>
        </linearGradient></defs>
        <CartesianGrid stroke="var(--line)" vertical={false}/>
        <XAxis dataKey="date" tickFormatter={dateLabel} minTickGap={36} tick={{ fontSize: 11, fill: "var(--muted)" }}/>
        <YAxis domain={["auto", "auto"]} width={48} tickFormatter={value => Number(value).toFixed(2)} tick={{ fontSize: 11, fill: "var(--muted)" }}/>
        <Tooltip labelFormatter={value => dateLabel(String(value))} contentStyle={labelStyle}/>
        <Area dataKey="equity" name="Equity" stroke="var(--accent)" fill={`url(#${fill})`} strokeWidth={2} isAnimationActive={false} dot={data.length === 1}/>
      </AreaChart>
    </ResponsiveContainer>
  </div>;
}

export function HistoryChart({ points }: { points: HistoryPoint[] }) {
  const rows = new Map<string, { date: string } & Partial<Record<Agent, number | null>>>();
  const available = new Set<string>();
  for (const point of points) {
    const agent = agents.find(name => name === point.agent);
    if (!agent || point.score == null) continue;
    const row = rows.get(point.date) ?? { date: point.date };
    rows.set(point.date, { ...row, [agent]: point.score });
    available.add(agent);
  }
  const data = Array.from(rows.values()).sort((a,b) => a.date.localeCompare(b.date));
  if (!data.length) return <State>No score history is stored for this ticker.</State>;
  return <div className="chart-area" role="img" aria-label="Agent scores over time from zero to one hundred">
    <ResponsiveContainer width="100%" height="100%" minWidth={0}>
      <LineChart data={data} margin={{ top: 12, right: 12, bottom: 4, left: 1 }}>
        <CartesianGrid stroke="var(--line)" vertical={false}/>
        <XAxis dataKey="date" tickFormatter={dateLabel} minTickGap={36} tick={{ fontSize: 11, fill: "var(--muted)" }}/>
        <YAxis domain={[0,100]} width={36} tick={{ fontSize: 11, fill: "var(--muted)" }}/>
        <Tooltip labelFormatter={value => dateLabel(String(value))} contentStyle={labelStyle}/>
        <Legend/>
        {agents.map((agent,i) => available.has(agent) && <Line key={agent} dataKey={agent} name={agentLabels[agent]}
          stroke={palette[i]} strokeWidth={2} dot={data.length <= 7} connectNulls isAnimationActive={false}/>)}
      </LineChart>
    </ResponsiveContainer>
  </div>;
}
