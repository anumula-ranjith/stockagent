import { redirect } from "next/navigation";

export default function MarketHeadlinesPage() {
  redirect("/news?kind=headline");
}
