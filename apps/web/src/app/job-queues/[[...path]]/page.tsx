import { QueueDashboard } from "./queue-dashboard";

export const metadata = { title: "Job queues" };

export default async function JobQueuesPage({params}: {params: Promise<{path?: string[]}>}) {
  const segments = (await params).path ?? [];
  return <QueueDashboard path={segments.map(encodeURIComponent).join("/")}/>;
}
