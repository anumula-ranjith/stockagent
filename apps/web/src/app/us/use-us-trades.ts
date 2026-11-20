"use client";
import {useEffect,useState} from "react";
import {api} from "@/lib/api";

type Trade={price:number;time:string;source:string};
export function useUsTrades(symbols:string[],enabled:boolean){
  const key=symbols.slice(0,30).join(",");
  const [result,setResult]=useState({key:"",mode:"",prices:{} as Record<string,Trade>});
  useEffect(()=>{
    if(!key || !enabled)return;
    let closed=false, socket:WebSocket|undefined, timer:ReturnType<typeof setTimeout>;
    const controller=new AbortController();
    async function start(){
      try {
        const {ticket}=await api<{ticket:string}>("/us/subscribe",{method:"POST",body:JSON.stringify({symbols:key.split(",")}),signal:controller.signal});
        if(closed)return;
        const origin=process.env.NEXT_PUBLIC_MARKET_WS_ORIGIN || (location.protocol==="https:"?"wss://":"ws://")+location.hostname+":8701";
        socket=new WebSocket(origin+"/us/stream");
        socket.onopen=()=>socket?.send(ticket);
        socket.onmessage=event=>{if(closed)return;const packet=JSON.parse(event.data);setResult(old=>({key,mode:packet.mode,prices:{...(old.key===key?old.prices:{}),...packet.prices}}));};
        socket.onclose=()=>{if(!closed){setResult(old=>({...old,mode:"Disconnected · retrying"}));timer=setTimeout(start,6000);}};
      }catch{if(!closed){setResult({key,mode:"IEX unavailable · retrying",prices:{}});timer=setTimeout(start,15000);}}
    }
    void start();
    return ()=>{closed=true;controller.abort();clearTimeout(timer);socket?.close();};
  },[key,enabled]);
  return result.key===key?result:{mode:"Connecting to IEX…",prices:{} as Record<string,Trade>};
}
