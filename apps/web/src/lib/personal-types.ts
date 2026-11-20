export type PortfolioRow = {id:string;name:string;created_at:string;entry_count:number};
export type Holding = {ticker:string;quantity:number;cost_basis:number;average_cost:number;close:number|null;
  price_date:string|null;market_value:number|null;unrealized_pnl:number|null;weight_pct:number|null};
export type Entry = {id:string;kind:"deposit"|"withdrawal"|"buy"|"sell";trade_date:string;ticker:string|null;
  quantity:number|null;price:number|null;fees:number;amount:number|null;note:string|null};
export type PortfolioDetail = {id:string;name:string;currency:"INR";cash:number;net_contributions:number;
  market_value:number;total_equity:number;realized_pnl:number;unrealized_pnl:number;total_pnl:number;
  unpriced_count:number;holdings:Holding[];entries:Entry[]};
export type WatchlistRow = {id:string;name:string;created_at:string;item_count:number};
export type WatchItem = {ticker:string;note:string|null;target_above:number|null;target_below:number|null;
  close:number|null;price_date:string|null;change_pct:number|null;alert:"above"|"below"|null};
export type WatchlistDetail = {id:string;name:string;items:WatchItem[]};
export type BrokerHolding = {symbol:string;ticker:string|null;exchange:string;isin:string|null;quantity:number|null;
  average_price:number|null;broker_ltp:number|null;broker_pnl:number|null};
export type BrokerTrade = {symbol:string;ticker:string|null;exchange:string;side:string;quantity:number|null;
  fill_price:number|null;fill_time:string;fill_id:string;order_id:string};
export type BrokerSnapshot = {broker:string;account_mask:string;fetched_at:string;holdings:BrokerHolding[];trades:BrokerTrade[]};

export const inr = new Intl.NumberFormat("en-IN", {style:"currency",currency:"INR",maximumFractionDigits:2});
export const signed = (value:number) => `${value>=0?"+":""}${inr.format(value)}`;
export function csvDownload(filename:string, rows:(string|number|null|undefined)[][]) {
  const data = rows.map(row => row.map(value => `"${String(value??"").replaceAll('"','""')}"`).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob(["\uFEFF",data], {type:"text/csv;charset=utf-8"}));
  const link = document.createElement("a"); link.href=url; link.download=filename; link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
