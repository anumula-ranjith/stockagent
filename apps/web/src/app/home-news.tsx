"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ArrowLeft, ArrowRight, ExternalLink, Pause, Play } from "lucide-react";
import { api } from "@/lib/api";
import { useSession } from "@/components/providers";
import { SignInNotice, State } from "@/components/presentation";
import s from "./home-news.module.css";

type Story={id:number;title:string;source:string;kind:string;url:string;published_at:string;companies:{symbol:string;name:string}[];sentiment?:{polarity:number;label:string}|null};
const todayIST=()=>new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Kolkata",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
const time=(value:string)=>new Intl.DateTimeFormat("en-IN",{timeZone:"Asia/Kolkata",hour:"2-digit",minute:"2-digit"}).format(new Date(value));

export function HomeNews() {
  const session=useSession();
  const [day,setDay]=useState(todayIST);
  const [paused,setPaused]=useState(false);
  const [interacting,setInteracting]=useState(false);
  const [reduced,setReduced]=useState(true);
  const rail=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    const timer=setInterval(()=>setDay(todayIST()),30000);
    const preference=window.matchMedia("(prefers-reduced-motion: reduce)");
    const update=()=>setReduced(preference.matches);
    update();preference.addEventListener("change",update);
    return ()=>{clearInterval(timer);preference.removeEventListener("change",update);};
  },[]);
  const news=useQuery({queryKey:["home-company-news",day,session.data?.id],enabled:!!session.data,
    queryFn:({signal})=>api<{items:Story[];total:number;coverage:{missing_days:number;failed_days:number}[]}>(`/company-news?start=${day}&end=${day}&page_size=20`,{signal}),refetchInterval:60000});
  useEffect(()=>{
    if(paused||interacting||reduced||!news.data?.items.length)return;
    const timer=setInterval(()=>{
      const el=rail.current;if(!el||el.scrollWidth<=el.clientWidth)return;
      const atEnd=el.scrollLeft+el.clientWidth>=el.scrollWidth-4;
      el.scrollTo({left:atEnd?0:el.scrollLeft+el.clientWidth,behavior:"smooth"});
    },6000);
    return ()=>clearInterval(timer);
  },[paused,interacting,reduced,news.data?.items.length]);
  const move=(direction:number)=>{setPaused(true);const el=rail.current;if(el)el.scrollBy({left:direction*el.clientWidth,behavior:reduced?"instant":"smooth"});};
  const unavailable=news.data?.coverage.some(c=>c.failed_days||c.missing_days);
  return <section className={`home-section ${s.section}`} aria-labelledby="home-news-title">
    <div className={s.heading}><div><p className="eyebrow">NSE company updates · {day} IST</p><h2 id="home-news-title">Today’s latest news</h2><p className="subtle">Latest stored headlines and announcements. Headlines collected every 15 minutes; filings every 5 minutes.</p></div>
      <Link className="text-link" href="/news">All company news <ArrowRight size={16}/></Link></div>
    {session.isPending?<State>Checking session…</State>:session.isError?<State error>{session.error.message}</State>:!session.data?<SignInNotice next="/">Sign in to see today’s company news.</SignInNotice>:
      news.isError?<State error>{news.error.message} <button onClick={()=>void news.refetch()}>Retry</button></State>:news.isPending?<State>Loading today’s news…</State>:<>
        {unavailable&&<p role="status" className="subtle">Some sources have not completed today’s update. Available stories are shown below.</p>}
        {!news.data?.items.length?<State>No stories collected for today yet. Earlier news remains in the Company News archive.</State>:<>
          <div className={s.controls}><span className="subtle">Newest first · {news.data.items.length} of {news.data.total} today</span>
            <button type="button" className="button" aria-label="Previous news cards" onClick={()=>move(-1)}><ArrowLeft size={16}/></button>
            {!reduced&&<button type="button" className="button" onClick={()=>setPaused(p=>!p)} aria-label={paused?"Resume news scrolling":"Pause news scrolling"}>{paused?<Play size={16}/>:<Pause size={16}/>}</button>}
            <button type="button" className="button" aria-label="Next news cards" onClick={()=>move(1)}><ArrowRight size={16}/></button></div>
          <div ref={rail} className={s.rail} tabIndex={0} role="region" aria-label="Today’s news cards, scroll horizontally"
            onMouseEnter={()=>setInteracting(true)} onMouseLeave={()=>setInteracting(false)}
            onFocusCapture={()=>setInteracting(true)} onBlurCapture={e=>{if(!e.currentTarget.contains(e.relatedTarget as Node|null))setInteracting(false);}}
            onTouchStart={()=>setPaused(true)} onKeyDown={()=>setPaused(true)}>
            {news.data.items.map(story=><article className={`surface ${s.card}`} key={story.id}>
              <div className={s.meta}><strong>{story.source}</strong><time dateTime={story.published_at}>{time(story.published_at)} IST</time></div>
              <span className={s.kind}>{story.kind==="announcement"?"NSE announcement":"Media headline"}</span>
              <h3><a href={story.url} target="_blank" rel="noopener noreferrer">{story.title} <ExternalLink size={14} aria-label="Open original source"/></a></h3>
              <span className={s.kind}>{story.sentiment ? `FinBERT estimate: ${story.sentiment.label} (${story.sentiment.polarity.toFixed(2)})` : story.kind==="announcement"?"Announcement · not scored":"Sentiment pending"}</span>
              <div className={s.companies}>{story.companies.map(c=><Link key={c.symbol} href={`/stocks/${encodeURIComponent(c.symbol)}`} title={c.name}>{c.name} · {c.symbol}</Link>)}</div>
            </article>)}
          </div>
        </>}
      </>}
  </section>;
}
