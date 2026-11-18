import { PageTitle } from "@/components/presentation";
import { Tuner } from "./tuner";

export const metadata = { title: "Dashboard" };

export default function DashboardPage() {
  return <div className="shell workspace">
    <PageTitle section="Rankings" title="Four-agent dashboard">Change the signal weights and compare the long and short books.</PageTitle>
    <Tuner/>
  </div>;
}
