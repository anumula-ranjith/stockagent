"use client";
import {useEffect,useState} from "react";
import {api} from "@/lib/api";

type Price = {price:number;time:string|null;source?:"tick"};
export function useMarketPrices(id:string, tickers:string, scope:"watchlist"|"subscribe"="watchlist") {
  const [feed,setFeed]=useState<{key:string;status:string;quotes:Record<string,Price>}>({key:"",status:"",quotes:{}});
  useEffect(()=>{
    if(!id || !tickers) return;
    let ended=false;
    let socket:WebSocket|undefined;
    let timer:ReturnType<typeof setTimeout>;
    const controller=new AbortController();
    const key=id+":"+tickers;
    const update=(status:string,quotes:Record<string,Price>={})=>{if(!ended)setFeed({key,status,quotes});};
    async function connect(){
      try {
        update("Connecting to Angel One…");
        const {ticket}=await api<{ticket:string}>("/market-feed/"+scope+"/"+encodeURIComponent(id),{method:"POST",signal:controller.signal});
        if(ended)return;
        const origin=process.env.NEXT_PUBLIC_MARKET_WS_ORIGIN || (location.protocol==="https:"?"wss://":"ws://")+location.hostname+":8701";
        socket=new WebSocket(origin+"/market-feed/stream");
        socket.onopen=()=>socket?.send(ticket);
        socket.onmessage=event=>{
          const packet=JSON.parse(event.data);
          update(packet.error || (packet.mode==="ticks" ? "Angel One · streaming prices" : "Angel One · quote snapshots every 10 seconds"),packet.quotes);
        };
        socket.onclose=()=>{if(!ended){update("Price stream disconnected");timer=setTimeout(connect,5000);}};
      } catch {if(!ended){update("Price stream unavailable");timer=setTimeout(connect,15000);}}
    }
    void connect();
    return ()=>{ended=true;controller.abort();clearTimeout(timer);socket?.close();};
  },[id,tickers,scope]);
  return feed.key===id+":"+tickers ? feed : {status:"",quotes:{} as Record<string,Price>};
}
