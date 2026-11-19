"use client";



import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useRef, useState } from "react";

import { api } from "@/lib/api";

import { useSession } from "@/components/providers";

import { SignInNotice, State } from "@/components/presentation";

import { Button } from "@/components/ui/button";

import s from "./portal.module.css";



type Stage = {name:string;status:string;started_at:string;finished_at?:string;error?:string;result?:Record<string,unknown>;attempt:number};

type Run = {id:string;pipeline:string;trade_date:string;status:string;trigger:string;created_at:string;started_at?:string;finished_at?:string;heartbeat_at?:string;attempt:number;cancel_requested:boolean;stages:Stage[];error?:string;parent_id?:string};

type Overview = {latest_session:string;active_runs:number;pipelines:Record<string,string[]>;latest_run:Run|null;cache_note:string;services:{broker:boolean;scheduler:boolean;worker:boolean;eodhd_configured:boolean;timezone:string}};

type Schedule = {id:string;label:string;hour:number;minute:number;enabled:boolean;next_run:string|null;timezone:string};

type Quality = {trade_date:string;members:number;priced:number;adjusted:number;missing_prices:string[];missing_adjusted:string[];missing_sectors:string[];invalid_prices:string[];status:string};

type User = {id:string;email:string;is_admin:boolean;email_verified:boolean};

type Audit = {id:number;user_id:string;action:string;occurred_at:string};

const active = (status:string) => ["queued","running","retrying"].includes(status);

const format = (value?:string|null) => value ? new Date(value).toLocaleString("en-IN",{timeZone:"Asia/Kolkata"}) : "—";

const label = (value:string) => value.replaceAll("_"," ");

const tabs = ["Overview","Pipelines","Schedules","Data quality","Users","Audit"] as const;



export function AdminPortal() {

  const session=useSession(), client=useQueryClient();

  const allowed=!!session.data?.is_admin;

  const [tab,setTab]=useState<typeof tabs[number]>("Overview");

  const [pipeline,setPipeline]=useState("daily"), [day,setDay]=useState("");

  const [selected,setSelected]=useState(""), [status,setStatus]=useState(""), [offset,setOffset]=useState(0);

  const [peopleOffset,setPeopleOffset]=useState(0), [auditOffset,setAuditOffset]=useState(0), [search,setSearch]=useState("");

  const [message,setMessage]=useState("");

  const [angelCode,setAngelCode]=useState("");

  const requestKeys=useRef(new Map<string,string>());

  const key=["admin",session.data?.id];

  const overview=useQuery({queryKey:[...key,"overview"],enabled:allowed,queryFn:()=>api<Overview>("/admin/overview"),refetchInterval:15000});

  const angel=useQuery({queryKey:[...key,"angel"],enabled:allowed,queryFn:()=>api<{connected:boolean;stream_ready:boolean;configured:boolean;expires_at:string|null;account_mask:string|null}>("/admin/angel-one"),refetchInterval:30000});

  const connectAngel=useMutation({mutationFn:()=>api("/admin/angel-one/connect",{method:"POST",body:JSON.stringify({code:angelCode})}),onSuccess:()=>{setAngelCode("");void client.invalidateQueries({queryKey:[...key,"angel"]});},onError:()=>setAngelCode("")});

  const runs=useQuery({queryKey:[...key,"runs",offset,status],enabled:allowed&&tab==="Pipelines",

    queryFn:()=>api<{total:number;items:Run[]}>(`/admin/runs?offset=${offset}${status?"&status="+status:""}`),refetchInterval:5000});

  const detail=useQuery({queryKey:[...key,"run",selected],enabled:allowed&&!!selected&&tab==="Pipelines",

    queryFn:()=>api<Run>("/admin/runs/"+selected),refetchInterval:q=>q.state.data&&active(q.state.data.status)?2000:false});

  const schedules=useQuery({queryKey:[...key,"schedules"],enabled:allowed&&(tab==="Schedules"||tab==="Overview"),queryFn:()=>api<Schedule[]>("/admin/schedules")});

  const quality=useQuery({queryKey:[...key,"quality"],enabled:allowed&&tab==="Data quality",queryFn:()=>api<Quality>("/admin/quality")});

  const users=useQuery({queryKey:[...key,"users",peopleOffset],enabled:allowed&&tab==="Users",queryFn:()=>api<{total:number;items:User[]}>(`/admin/users?offset=${peopleOffset}`)});

  const audit=useQuery({queryKey:[...key,"audit",auditOffset],enabled:allowed&&tab==="Audit",queryFn:()=>api<{total:number;items:Audit[]}>(`/admin/audit?offset=${auditOffset}`)});

  const write=useMutation({mutationFn:({path,body,method="POST"}:{path:string;body?:Record<string,unknown>;method?:string})=>{

    const intent=path+JSON.stringify(body||{});

    if(path==="/admin/runs"||path.endsWith("/retry")) {

      if(!requestKeys.current.has(intent)) requestKeys.current.set(intent,crypto.randomUUID());

      body={...body,idempotency_key:requestKeys.current.get(intent)};

    }

    return api<Partial<Run>>(path,{method,body:body?JSON.stringify(body):undefined});

  },onMutate:()=>setMessage(""),onSuccess:(data,variables)=>{

    requestKeys.current.delete(variables.path+JSON.stringify(variables.body||{}));

    setMessage(data.pipeline?"Pipeline request accepted. Follow completion in run history.":"Changes saved.");

    if(data.id && data.pipeline){setSelected(data.id);setTab("Pipelines");}

    void client.invalidateQueries({queryKey:key});void client.invalidateQueries({queryKey:["session"]});

  },onError:()=>setMessage("")});

  function start(kind=pipeline) {write.mutate({path:"/admin/runs",body:{pipeline:kind,trade_date:day||overview.data?.latest_session}});}

  if(session.isPending)return <State>Checking administrator access…</State>;

  if(session.isError)return <State error>Session unavailable. Refresh to try again.</State>;

  if(!session.data)return <SignInNotice next="/admin">Sign in with an administrator account.</SignInNotice>;

  if(!allowed)return <State error>Administrator access required. Your account cannot run pipelines or change system settings.</State>;

  const current=detail.data;

  return <div className={s.root}>

    <header className={s.header}><div><p className="subtle">QUANTORA OPERATIONS · INDIA</p><h1>Administration</h1><p>Market data, pipeline runs and access controls in one workspace.</p></div>

      <Button variant="secondary" onClick={()=>void client.invalidateQueries({queryKey:key})}>Refresh status</Button></header>

    <nav className={s.tabs} aria-label="Admin sections">{tabs.map(name=><button key={name} aria-current={tab===name?"page":undefined} onClick={()=>{setTab(name);setMessage("");write.reset();}}>{name}</button>)}</nav>

    {write.isError&&<p role="alert" className={s.error}>{write.error.message}</p>}{message&&<p role="status">{message}</p>}

    {(tab==="Overview"||tab==="Pipelines")&&<section className="surface"><h2>Angel One market-data connection</h2>

      <p>{angel.data?.connected?`Connected ${angel.data.account_mask||""} · ${angel.data.stream_ready?"Feed token ready":"Quotes only · reconnect for streaming"} · expires ${format(angel.data.expires_at)}`:"Connection required: enter the current six-digit code from your authenticator."}</p>

      <p className="subtle">The code changes every 30 seconds. The TOTP secret is a separate setup key. This form never saves your code. The encrypted broker session expires at midnight IST; reconnect before the next scheduled update. Historical daily candles recover missed captures.</p>

      {angel.data&&!angel.data.configured&&<p role="alert">Configure the API key, client code and PIN on the server first.</p>}

      <form onSubmit={e=>{e.preventDefault();connectAngel.mutate();}} className={s.form}>

        <label className="field">Current six-digit Angel One code<input type="password" inputMode="numeric" autoComplete="one-time-code" required pattern="[0-9]{6}" minLength={6} maxLength={6} value={angelCode} onChange={e=>setAngelCode(e.target.value.replace(/\D/g,""))}/></label>

        <Button type="submit" disabled={connectAngel.isPending||angelCode.length!==6||!angel.data?.configured}>{connectAngel.isPending?"Connecting…":"Connect Angel One"}</Button>

      </form>{connectAngel.isError&&<p role="alert">{connectAngel.error.message}</p>}{connectAngel.isSuccess&&<p role="status">Angel One connected. You can now run or retry a pipeline.</p>}{angel.isError&&<p role="alert">{angel.error.message}</p>}

    </section>}

    {tab==="Overview"&&<>

      {overview.isError?<State error>{overview.error.message}</State>:!overview.data?<State>Loading operations…</State>:<>

        <div className={s.cards}><Card title="Latest completed session" value={overview.data.latest_session}/><Card title="Active runs" value={overview.data.active_runs}/>

          <Card title="Redis broker" value={overview.data.services.broker?"Connected":"Offline"}/><Card title="Pipeline worker" value={overview.data.services.worker?"Online":"Offline"}/><Card title="Scheduler" value={overview.data.services.scheduler?"Online":"Offline"}/></div>

        {(!overview.data.services.worker||!overview.data.services.scheduler)&&<p role="alert" className={s.warning}>Services are offline or have not reported a heartbeat. Submitted jobs remain durable in PostgreSQL until delivery recovers.</p>}

        <section className="surface"><h2>How data is updated</h2><ol className={s.flow}><li>Refresh Nifty 500 and F&O membership, company names and sectors.</li><li>Load completed-session OHLCV, corporate actions and adjusted closes into PostgreSQL.</li><li>Refresh configured fundamentals, estimates, exchange disclosures, news and sentiment.</li><li>Validate coverage and prices; recompute scores after required data checks pass.</li><li>Publish results and refresh server snapshots. {overview.data.cache_note}</li></ol>

          <p>7:00 AM catches up the previous completed session. 6:30 PM updates after market close. Weekends and holidays resolve to the latest NSE session. Source delays are reported and retried.</p>

          <p className="subtle">Optional unavailable sources produce a partial result. A queued run is not a completed update. Cancellation takes effect between stages and keeps committed data.</p>

          <Button onClick={()=>setTab("Pipelines")}>Manage pipelines</Button></section>

        <section className="surface"><h2>Source configuration</h2><p>EODHD: {overview.data.services.eodhd_configured?"Configured":"Not configured"}. NSE exchange files: public source. Other vendor availability is reported by its pipeline stage.</p><p>Credentials are managed in server configuration and are never displayed here.</p></section>

        {overview.data.latest_run&&<section className="surface"><h2>Latest run</h2><p>{label(overview.data.latest_run.pipeline)} · <Badge status={overview.data.latest_run.status}/> · {format(overview.data.latest_run.created_at)}</p><Button variant="secondary" onClick={()=>{setSelected(overview.data!.latest_run!.id);setTab("Pipelines");}}>View run</Button></section>}

      </>}

    </>}

    {tab==="Pipelines"&&<>

      <form className={`surface ${s.form}`} onSubmit={e=>{e.preventDefault();start();}}><h2>Run a pipeline</h2>

        <label className="field">Pipeline<select value={pipeline} onChange={e=>setPipeline(e.target.value)}>{Object.keys(overview.data?.pipelines??{daily:[]}).map(p=><option key={p} value={p}>{label(p)}</option>)}</select></label>

        <label className="field">Trading session<input type="date" value={day||overview.data?.latest_session||""} max={overview.data?.latest_session} onChange={e=>setDay(e.target.value)} required/></label>

        <Button disabled={write.isPending||!overview.data||!!overview.data.active_runs} type="submit">{write.isPending?"Submitting…":"Run pipeline now"}</Button>

        <p className="subtle">One market pipeline at a time. Dates are limited to completed NSE sessions within 31 days. Price repair is incremental and reuses healthy bars.</p>

        <p className="subtle">Stages: {(overview.data?.pipelines[pipeline]??[]).map(label).join(" → ")}</p>

      </form>

      <section className="surface"><div className={s.row}><h2>Run history</h2><label className="field">Status<select value={status} onChange={e=>{setStatus(e.target.value);setOffset(0);}}><option value="">All statuses</option>{["queued","running","retrying","success","partial","failed","cancelled"].map(v=><option key={v}>{v}</option>)}</select></label></div>

        {runs.isError?<State error>{runs.error.message}</State>:!runs.data?<State>Loading runs…</State>:<><div className="table-scroll"><table><thead><tr><th>Created · IST</th><th>Pipeline</th><th>Session</th><th>Status</th><th>Trigger</th><th/></tr></thead><tbody>{runs.data.items.map(r=><tr key={r.id}><td>{format(r.created_at)}</td><td>{label(r.pipeline)}</td><td>{r.trade_date}</td><td><Badge status={r.status}/></td><td>{r.trigger}</td><td><button onClick={()=>setSelected(r.id)}>Details</button></td></tr>)}</tbody></table></div>{!runs.data.items.length&&<State>No pipeline runs match this filter.</State>}<Paging offset={offset} total={runs.data.total} size={25} change={setOffset}/></>}

      </section>

      {selected&&<section className="surface" aria-label="Pipeline run details">{detail.isError?<State error>{detail.error.message}</State>:!current?<State>Loading run…</State>:<>

        <div className={s.row}><h2>{label(current.pipeline)} · {current.trade_date}</h2><Badge status={current.status}/></div><p className="subtle">Run {current.id} · attempt {current.attempt} · heartbeat {format(current.heartbeat_at)}</p>

        {current.error&&<p role="alert" className={s.warning}>{current.error}</p>}

        {current.parent_id&&<p>Retry of {current.parent_id}</p>}

        <div className={s.row}>{active(current.status)&&<Button variant="secondary" disabled={write.isPending||current.cancel_requested} onClick={()=>write.mutate({path:`/admin/runs/${current.id}/cancel`})}>{current.cancel_requested?"Cancellation requested":"Cancel after current stage"}</Button>}

        {["failed","partial","cancelled"].includes(current.status)&&<Button disabled={write.isPending} onClick={()=>write.mutate({path:`/admin/runs/${current.id}/retry`})}>Retry pipeline</Button>}</div>

        {!current.stages.length&&<p>Awaiting worker delivery.</p>}{current.stages.map(stage=><details className={s.stage} key={stage.name} open={stage.status==="running"||!!stage.error}><summary>{label(stage.name)} <Badge status={stage.status}/></summary><p>Started {format(stage.started_at)} · finished {format(stage.finished_at)}</p>{stage.error&&<p className={s.error}>{stage.error}</p>}{stage.result&&<pre>{JSON.stringify(stage.result,null,2)}</pre>}</details>)}

      </>}</section>}

    </>}

    {tab==="Schedules"&&<section className="surface"><h2>Daily schedules</h2><p>Timezone: Asia/Kolkata. Missed slots catch up within 24 hours after recovery. Pausing a schedule does not cancel an existing run.</p>

      {schedules.isError?<State error>{schedules.error.message}</State>:!schedules.data?<State>Loading schedules…</State>:schedules.data.map(item=><div className={s.schedule} key={item.id}><div><h3>{item.label} · {String(item.hour).padStart(2,"0")}:{String(item.minute).padStart(2,"0")}</h3><p>{item.enabled?"Next: "+format(item.next_run):"Paused"}</p></div><Button disabled={write.isPending} variant="secondary" onClick={()=>write.mutate({path:"/admin/schedules/"+item.id,method:"PATCH",body:{enabled:!item.enabled}})}>{item.enabled?"Pause":"Resume"} {item.label.toLowerCase()}</Button></div>)}

    </section>}

    {tab==="Data quality"&&<section className="surface"><h2>Data coverage</h2>{quality.isError?<State error>{quality.error.message}</State>:!quality.data?<State>Checking market coverage…</State>:<><p>Session {quality.data.trade_date} · current Nifty 500 + F&O membership</p><div className={s.cards}><Card title="Members" value={quality.data.members}/><Card title="Priced" value={quality.data.priced}/><Card title="Adjusted closes" value={quality.data.adjusted}/></div>

      <label className="field">Find a ticker<input type="search" value={search} onChange={e=>setSearch(e.target.value)}/></label>

      {(["missing_prices","missing_adjusted","missing_sectors","invalid_prices"] as const).map(k=><div key={k}><h3>{label(k)} · {quality.data![k].length}</h3><p>{quality.data![k].filter(t=>t.includes(search.trim().toUpperCase())).join(", ")||"No matching issues"}</p></div>)}

      <Button disabled={write.isPending||!!overview.data?.active_runs} onClick={()=>{setDay(quality.data!.trade_date);setPipeline("prices");setTab("Pipelines");}}>Prepare EOD repair</Button>

    </>}</section>}

    {tab==="Users"&&<section className="surface"><h2>Account access</h2><p>Role changes are audited. The final administrator cannot be demoted.</p>{users.isError?<State error>{users.error.message}</State>:!users.data?<State>Loading accounts…</State>:<><div className="table-scroll"><table><thead><tr><th>Email</th><th>Verified</th><th>Role</th><th>Action</th></tr></thead><tbody>{users.data.items.map(u=><tr key={u.id}><td>{u.email}</td><td>{u.email_verified?"Yes":"No"}</td><td>{u.is_admin?"Administrator":"Member"}</td><td><Button variant="secondary" disabled={write.isPending} onClick={()=>{if(window.confirm(`Change ${u.email} to ${u.is_admin?"member":"administrator"}?`))write.mutate({path:`/admin/users/${u.id}/role`,method:"PATCH",body:{is_admin:!u.is_admin}});}}>{u.is_admin?"Make member":"Make administrator"}</Button></td></tr>)}</tbody></table></div><Paging offset={peopleOffset} size={50} total={users.data.total} change={setPeopleOffset}/></>}</section>}

    {tab==="Audit"&&<section className="surface"><h2>Administrative audit</h2>{audit.isError?<State error>{audit.error.message}</State>:!audit.data?<State>Loading audit…</State>:<><div className="table-scroll"><table><thead><tr><th>Time · IST</th><th>Action</th><th>Actor ID</th></tr></thead><tbody>{audit.data.items.map(a=><tr key={a.id}><td>{format(a.occurred_at)}</td><td>{a.action}</td><td>{a.user_id||"System"}</td></tr>)}</tbody></table></div><Paging offset={auditOffset} size={50} total={audit.data.total} change={setAuditOffset}/></>}</section>}

  </div>;

}

function Card({title,value}:{title:string;value:string|number}) {return <div className={s.card}><span>{title}</span><strong>{value}</strong></div>;}

function Badge({status}:{status:string}) {return <span className={s.badge} data-status={status}>{label(status)}</span>;}

function Paging({offset,total,size,change}:{offset:number;total:number;size:number;change:(n:number)=>void}) {return <div className={s.row}><span>{total} records</span><Button variant="ghost" disabled={offset===0} onClick={()=>change(Math.max(0,offset-size))}>Previous</Button><Button variant="ghost" disabled={offset+size>=total} onClick={()=>change(offset+size)}>Next</Button></div>;}

