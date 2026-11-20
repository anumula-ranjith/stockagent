"use client";

import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { parseAsStringLiteral, useQueryState } from "nuqs";
import { ExternalLink, Download, ArrowUpRight, ChevronLeft, ChevronRight, SlidersHorizontal, Newspaper, FileText, Layers, Radio, ChevronDown } from "lucide-react";
import { api } from "@/lib/api";
import { useSession } from "@/components/providers";
import { SignInNotice, State } from "@/components/presentation";
import s from "./news.module.css";

type Company = {symbol:string;name:string;segment?:string};
type Story = {id:number;kind:string;source:string;title:string;url:string;published_at:string;companies:Company[];sentiment?:{polarity:number;model:string;label:string}|null};
type Coverage = {source:string;status:string;missing_days:number;failed_days:number;last_success:string|null;details:{day:string;status:string;detail:string}[]};
type Result = {items:Story[];total:number;page:number;page_size:number;start:string;end:string;coverage:Coverage[]};
type Filters = {symbol:string;kind:string;source:string;start:string;end:string};
const publishers=["NSE equities","NSE sme","Mint","The Economic Times","Moneycontrol","Business Standard"];
const stamp=(value:string)=>new Intl.DateTimeFormat("en-IN",{timeZone:"Asia/Kolkata",day:"2-digit",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false}).format(new Date(value))+" IST";
const sentimentLabel=(story:Story)=>story.sentiment ? `${story.sentiment.label} (${story.sentiment.polarity.toFixed(2)}) · FinBERT headline estimate` : story.kind==="announcement" ? "Announcement · not scored" : "Sentiment pending";
const query=(filters:Filters)=>new URLSearchParams(Object.entries(filters).filter(([,v])=>v));

const kinds = ["all", "headline", "announcement"] as const;
type Kind = typeof kinds[number];

export function CompanyNews({symbol}: {symbol?: string} = {}) {
  const session=useSession();
  const [kind, setKind] = useQueryState("kind", parseAsStringLiteral(kinds).withDefault("all"));
  if(session.isPending) return <State>Checking session…</State>;
  if(session.isError) return <State error>{session.error.message}</State>;
  if(!session.data) return <SignInNotice next={symbol ? `/stocks/${encodeURIComponent(symbol)}` : kind === "all" ? "/news" : `/news?kind=${kind}`}>Sign in to read company news and download reports.</SignInNotice>;
  return <Workspace key={symbol} symbol={symbol} kind={kind} setKind={value => void setKind(value)}/>;
}

const sections = [
  {value:"all", label:"All news", Icon:Layers},
  {value:"headline", label:"Market Headlines", Icon:Newspaper},
  {value:"announcement", label:"NSE filings", Icon:FileText},
] as const;
const newsDate = new Intl.DateTimeFormat("en-IN", {timeZone:"Asia/Kolkata", day:"numeric", month:"short", year:"numeric"});
const newsTime = new Intl.DateTimeFormat("en-IN", {timeZone:"Asia/Kolkata", hour:"2-digit", minute:"2-digit", second:"2-digit", hour12:false});
const dayLabel = (iso:string) => newsDate.format(new Date(iso));
const sourceLabel = (name:string) => name === "NSE sme" ? "NSE SME" : name;

function StoryRow({story, lead}: {story:Story; lead:boolean}) {
  const media = story.kind === "headline";
  const date = new Date(story.published_at);
  return <article className={s.story} data-lead={lead || undefined}>
    <div className={s.byline}>
      <span className={media ? s.media : s.filing}>{media ? <Newspaper size={13}/> : <FileText size={13}/>}
        {media ? "Headline" : "Filing"}</span>
      <span>{sourceLabel(story.source)}</span>
      <time dateTime={story.published_at}>{newsDate.format(date)} · {newsTime.format(date)} IST</time>
    </div>
    <h3><a href={story.url} target="_blank" rel="noopener noreferrer">{story.title}
      <ArrowUpRight size={16} aria-label="Open source in a new tab"/></a></h3>
    <p className="subtle">{sentimentLabel(story)}</p>
    {!!story.companies?.length && <div className={s.issuers}>{story.companies.map(c=>
      <span key={c.symbol}><b>{c.symbol}</b> {c.name}</span>)}</div>}
  </article>;
}

function SourceCoverage({data}: {data:Result}) {
  return <section className={s.coverage} aria-label="Source coverage">
    <h2><Radio size={17}/> Source coverage</h2>
    <p>{dayLabel(data.start)} – {dayLabel(data.end)}</p>
    {data.coverage.map(c=><details key={c.source}>
      <summary><span>{sourceLabel(c.source)}</span><span className={s.health} data-issue={!!(c.failed_days || c.missing_days)}>
        {c.status.replaceAll("_"," ")}</span><ChevronDown size={13}/></summary>
      <div className={s.sourceDetail}><p>Last successful update · {c.last_success ? stamp(c.last_success) : "Not yet collected"}</p>
        {!!c.missing_days && <p>Days without a collection · {c.missing_days}</p>}
        {!!c.failed_days && <p>Incomplete or unavailable days · {c.failed_days}</p>}
        {c.details.filter(d=>d.status==="failed" || d.status==="partial").map(d=><p key={d.day}>{d.day} · {d.detail}</p>)}
      </div>
    </details>)}
    <p>Media archive coverage varies by publisher.</p>
  </section>;
}

function Workspace({symbol, kind, setKind}: {symbol?:string; kind:Kind; setKind:(value:Kind)=>void}) {
  const initial = {symbol:symbol ? symbol.replace(/\.(NS|NSE)$/i,"")+".NS" : "", source:"", start:"", end:""};
  const [draft,setDraft] = useState(initial);
  const [applied,setFilters] = useState(initial);
  const filters = {...applied, kind};
  const [page,setPage] = useState(1);
  const [validation,setValidation] = useState("");
  const [mobileFilters,setMobileFilters] = useState(false);
  const params = query(filters);
  const news = useQuery({queryKey:["company-news",filters,page],
    queryFn:({signal})=>api<Result>(`/company-news?${params}&page=${page}&page_size=50`,{signal}),refetchInterval:60000});
  const lookup = useQuery({queryKey:["news-companies",draft.symbol],enabled:!symbol && draft.symbol.trim().length>=2,
    queryFn:({signal})=>api<Company[]>("/company-news/companies?q="+encodeURIComponent(draft.symbol),{signal})});
  const set = (key:keyof typeof initial,value:string)=>setDraft(old=>({...old,[key]:value}));
  function apply(event:FormEvent) {
    event.preventDefault();
    if (draft.start && draft.end && draft.start>draft.end) {setValidation("Choose an end date on or after the start date.");return;}
    setValidation("");setPage(1);setFilters({...draft,symbol:draft.symbol.trim()});setMobileFilters(false);
  }
  const data = news.data;
  const problem = data?.coverage.some(c=>c.missing_days>0 || c.failed_days>0);
  const base = (process.env.NEXT_PUBLIC_API_BASE || "/backend").replace(/\/$/,"");
  return <div className={s.newsroom}>
    <div className={s.toolbar}>
      <div className={s.sections} role="group" aria-label="News type">{sections.map(({value,label,Icon})=>
        <button key={value} type="button" aria-pressed={filters.kind===value} onClick={()=>{
          setKind(value);setPage(1);
        }}><Icon size={15}/>{label}</button>)}</div>
      {data && <a className={s.export} href={`${base}/company-news/export.csv?${params}`} download title="Download all matching records"><Download size={15}/> Download CSV</a>}
    </div>
    <div className={s.columns}>
      <div className={s.rail}>
        <section className={s.filterBox} aria-label="News filters">
          <h2 className={s.desktopFilterTitle}><SlidersHorizontal size={17}/> Filters</h2>
          <button type="button" className={s.filterToggle} aria-expanded={mobileFilters} aria-controls="news-filter-form"
            onClick={()=>setMobileFilters(v=>!v)}><SlidersHorizontal size={17}/> Filters <ChevronDown size={16}/></button>
          <form id="news-filter-form" className={s.filters} data-open={mobileFilters} onSubmit={apply}>
            {!symbol && <label className="field">Company<input type="search" list="news-companies" value={draft.symbol} onChange={e=>set("symbol",e.target.value)} placeholder="Company or ticker"/>
              <datalist id="news-companies">{lookup.data?.map(c=><option key={c.symbol} value={c.symbol}>{c.name} · {c.segment}</option>)}</datalist></label>}
            <label className="field">Publisher or exchange<select value={draft.source} onChange={e=>set("source",e.target.value)}>
              <option value="">All sources</option>{publishers.map(p=><option key={p} value={p}>{sourceLabel(p)}</option>)}</select></label>
            <div className={s.dates}><label className="field">From<input type="date" value={draft.start} onChange={e=>set("start",e.target.value)}/></label>
              <label className="field">To<input type="date" value={draft.end} onChange={e=>set("end",e.target.value)}/></label></div>
            <p className={s.help}>Dates use IST. Leave both blank for the latest seven days, or choose one date for a single day.</p>
            {validation && <p role="alert" className={s.error}>{validation}</p>}
            <div className={s.actions}><button type="submit">Apply filters</button>
              <button type="button" onClick={()=>{setDraft(initial);setFilters(initial);setKind("all");setPage(1);setValidation("");}}>Clear</button></div>
          </form>
        </section>
        {data && <SourceCoverage data={data}/>}
      </div>
      <section className={s.feed} aria-labelledby="news-feed-title">
        <div className={s.feedHeading}><h2 id="news-feed-title">Latest stories</h2>
          {data && <span>{data.total.toLocaleString("en-IN")} records</span>}</div>
        {data && <div className={s.period}>{dayLabel(data.start)} – {dayLabel(data.end)} · Newest first{filters.symbol && " · "+filters.symbol}{filters.source && " · "+sourceLabel(filters.source)}</div>}
        {news.isError && <State error>{news.error.message} <button className="text-link" onClick={()=>void news.refetch()}>Retry</button></State>}
        {news.isPending && <State>Loading company news…</State>}
        {data && <>
          {!data.items.length ? <State>{problem ? "No stored matches. Check source coverage for gaps in this period." : "No matching stories in the collected results."}</State> :
            <div key={`${params}-${page}`} className={s.stories}>{data.items.map((story,i)=><StoryRow key={story.id} story={story} lead={page===1 && i===0}/>)}</div>}
          <div className={s.paging}><span>Page {page} of {Math.max(1,Math.ceil(data.total/50))}</span>
            <button type="button" disabled={page===1} onClick={()=>setPage(p=>p-1)}><ChevronLeft size={16}/> Previous</button>
            <button type="button" disabled={page*50>=data.total} onClick={()=>setPage(p=>p+1)}>Next <ChevronRight size={16}/></button></div>
        </>}
      </section>
    </div>
  </div>;
}

export function LatestStockNews({symbol}: {symbol:string}) {
  const session=useSession();
  const news=useQuery({queryKey:["company-news-latest",symbol,session.data?.id],enabled:!!session.data,
    queryFn:({signal})=>api<Story[]>(`/company-news/latest?symbol=${encodeURIComponent(symbol)}`,{signal}),refetchInterval:60000});
  return <section className="surface" id="news" aria-label={`${symbol} latest news`}>
    <div className="surface-top"><h2 className="section-title">Latest news · {symbol}</h2><a className="text-link" href="/news">Company News archive</a></div>
    <p className="chart-pad subtle">The 7 latest stored headlines and announcements, newest first. Older news remains in the archive.</p>
    {session.isPending ? <State>Checking session…</State> : session.isError ? <State error>{session.error.message}</State> : !session.data ? <State>Sign in to view company news.</State> :
      news.isError ? <State error>{news.error.message} <button onClick={()=>void news.refetch()}>Retry</button></State> : news.isPending ? <State>Loading news…</State> :
      !news.data?.length ? <State>No news stored for this company yet.</State> :
      <div className="table-scroll" role="region" aria-label="Latest stock news" tabIndex={0}><table className={s.table}>
        <thead><tr><th scope="col">Published (IST)</th><th scope="col">Publisher / exchange</th><th scope="col">Headline / announcement</th></tr></thead>
        <tbody>{news.data.map(item=><tr key={item.id}><td><time dateTime={item.published_at}>{stamp(item.published_at)}</time></td>
          <td><strong>{item.source}</strong><small>{item.kind==="headline"?"Media headline":"Official announcement"}</small></td>
          <td><a href={item.url} target="_blank" rel="noopener noreferrer">{item.title} <ExternalLink size={13} aria-label="Open source"/></a><small>{sentimentLabel(item)}</small></td></tr>)}</tbody>
      </table></div>}
  </section>;
}
