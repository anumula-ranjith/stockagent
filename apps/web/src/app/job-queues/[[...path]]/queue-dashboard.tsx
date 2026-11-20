"use client";

import { AngelMarketStatus } from "@/components/angel-market-status";
import { SignInNotice, State } from "@/components/presentation";
import { useSession } from "@/components/providers";
import { ScheduledPriceHistory } from "./scheduled-price-history";

export function QueueDashboard({path}: {path: string}) {
  const session = useSession();
  if (session.isPending) return <State>Checking administrator access…</State>;
  if (session.error) return <State error>{session.error.message}</State>;
  if (!session.data) return <SignInNotice next={path ? "/datadaily/job-queues/" + path : "/datadaily/job-queues"}>Sign in to view job queues.</SignInNotice>;
  if (!session.data.is_admin) return <State error>Administrator access is required to view job queues.</State>;
  return <>
    <div className="shell queue-market-status">
      <AngelMarketStatus user={session.data.id}/>
      <ScheduledPriceHistory user={session.data.id}/>
    </div>
    <iframe title="RQ job queues" className="queue-dashboard"
    src={"/operations/" + (path || "0/view/queues") + window.location.search}
    onLoad={event => {
      const location = event.currentTarget.contentDocument?.location;
      if (location?.pathname.startsWith("/_admin/rq/")) {
        const prefix = "/datadaily/job-queues";
        const target = window.location.pathname.startsWith(prefix)
          ? prefix + "/" + location.pathname.slice("/_admin/rq/".length) : location.pathname;
        window.history.replaceState(window.history.state, "", target + location.search);
      }
    }}/>
  </>;
}
