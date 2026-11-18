import { z } from "zod";

export const reportSchema = z.object({
  start: z.string(), end: z.string(), n_days: z.number(),
  total_return: z.number(), annual_return: z.number(), annual_vol: z.number(),
  sharpe: z.number(), max_drawdown: z.number(), longs_last: z.array(z.string()).default([]),
  shorts_last: z.array(z.string()).default([]),
  equity_curve: z.array(z.object({ date: z.string(), equity: z.number() })).default([]),
});
export type Report = z.infer<typeof reportSchema>;
