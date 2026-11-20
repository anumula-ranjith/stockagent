import { DailyLinks } from "./daily-links";

export const metadata = { title: "Data Daily" };

export default function DataDailyPage() {
  return <div className="shell workspace">
    <div className="page-title"><h1>Data Daily</h1></div>
    <DailyLinks/>
  </div>;
}
