import { StockActions } from "./stock-actions";
import Link from "next/link";
import s from "./stock-ticker.module.css";

export function StockTicker({ticker,href,label}:{ticker:string;href?:string;label?:string}) {
  const encoded = encodeURIComponent(ticker);
  return <span className={s.stock}>
    <Link prefetch={false} className={s.name} target="_blank" rel="opener" referrerPolicy="same-origin"
      title={`Open ${ticker} in a new tab`} href={href??`/stocks/${encoded}`}>{label??ticker}</Link>
    <StockActions ticker={ticker}/>
  </span>;
}
