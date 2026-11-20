import Image from "next/image";
import { CalendarDays } from "lucide-react";
import "@fontsource/instrument-serif/400.css";
import "@fontsource/instrument-serif/400-italic.css";
import { CompanyNews } from "./company-news";
import s from "./news.module.css";

export const metadata = {title: "Company News"};
export const dynamic = "force-dynamic";
export default function NewsPage() {
  const edition = new Intl.DateTimeFormat("en-IN", {timeZone:"Asia/Kolkata", day:"numeric", month:"long", year:"numeric", weekday:"long"}).format(new Date());
  return <div className={s.page}><div className="shell">
    <header className={s.masthead}>
      <Image src="/market-district.webp" alt="" fill priority sizes="(max-width: 700px) 100vw, 70vw" className={s.district}/>
      <div className={s.mastCopy}>
        <p className={s.edition}><CalendarDays size={14}/>{edition}</p>
        <h1>Company <em>News</em></h1>
        <p className={s.intro}>Media headlines and exchange filings for NSE main-board and SME companies.</p>
      </div>
    </header>
    <CompanyNews/>
  </div></div>;
}
