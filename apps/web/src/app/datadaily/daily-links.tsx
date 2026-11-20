"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { useSession, usesClerk } from "@/components/providers";

const research = [
  ["screener", "Screener"], ["backtest", "Backtest"],
  ["methodology", "Methodology"], ["assistant", "AI Assistant"],
];

export function DailyLinks() {
  const session = useSession();
  const links = [...research];
  if (session.data && !usesClerk) links.push(["account", "Account"]);
  if (session.data?.is_admin) links.push(["admin", "Admin"], ["job-queues", "Job queues"]);
  return <nav className="daily-tools" aria-label="Data Daily tools">
    {links.map(([slug, label]) => <Link key={slug} href={"/datadaily/" + slug}>
      {label}<ArrowRight size={16} aria-hidden="true"/>
    </Link>)}
  </nav>;
}
