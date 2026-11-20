"use client";

import { useRef, type ReactNode } from "react";
import { agentLabels, agents } from "@/lib/api";
import { defaults, factors, pillars, type Settings, type Snapshot, type Tab } from "./ranker-model";
import s from "./ranker.module.css";

export function Control({label, children}:{label:string;children:ReactNode}) {
  return <label className={s.control}><span>{label}</span>{children}</label>;
}
function Slider({label,value,max,onChange,share}:{label:string;value:number;max:number;onChange:(n:number)=>void;share?:string}) {
  return <label className={s.slider}><span>{label}<small>{share ?? value}</small></span>
    <input aria-label={label+" weight"} type="range" min={0} max={max} value={value} onChange={e=>onChange(Number(e.target.value))}/></label>;
}
export function SettingsPanel({tab,config,change,coverage}:{tab:Exclude<Tab,"portfolio">;config:Settings;change:(value:Settings)=>void;coverage?:Snapshot["coverage"]}) {
  const previous = useRef<Record<string,number>>({});
  function mapValue(map:"factors"|"pillars"|"agents",key:string,value:number) {
    change({...config,[map]:{...config[map],[key]:value}});
  }
  function toggleFactor(key:string) {
    const val = config.factors[key];
    if(val>0) previous.current[key] = val;
    mapValue("factors",key,val>0?0:(previous.current[key]||defaults.factors[key]||1));
  }
  function check(key:keyof Settings,label:string) {
    return <Control label={label}><input type="checkbox" checked={Boolean(config[key])} onChange={e=>change({...config,[key]:e.target.checked})}/></Control>;
  }
  function num(key:keyof Settings,label:string,min:number,max:number,step=1) {
    return <Control label={label}><input type="number" min={min} max={max} step={step} value={Number(config[key])}
      onChange={e=>change({...config,[key]:Math.max(min,Math.min(max,Number(e.target.value)))})}/></Control>;
  }
  if(tab==="combined") return <aside className={s.panel}><h2>Agent weights</h2>
    <p className={s.hint}>Set each agent’s contribution to the composite.</p>
    {agents.map(a=><Slider key={a} label={agentLabels[a]} max={100} value={config.agents[a]} onChange={v=>mapValue("agents",a,v)}/>)}
    <h3>Selection</h3>
    <Control label="Mode"><select value={config.mode} onChange={e=>change({...config,mode:e.target.value})}>
      <option value="weighted">Weighted composite</option><option value="consensus">Consensus</option><option value="hybrid">Hybrid</option>
    </select></Control>
    {num("size","Names per side",1,50)}
    {config.mode==="consensus" && num("agree","Agents that must agree",1,4)}
    {num("max_sector","Max per sector (0 = off)",0,50)}
    <p className={s.hint}>{config.mode==="consensus"?"Requires a top-20 or bottom-20 vote from the selected number of agents.":config.mode==="hybrid"?"Longs need every active score at or above 40. Shorts need every active score at or below 60.":"Ranks by the weighted agent score, subject to the sector limit."}</p>
  </aside>;
  if(tab==="fundamental") return <aside className={s.panel+" "+s.pillars}><h2>Fundamental pillars</h2><p className={s.hint}>Set pillar weights and select the metrics to include.</p>
    {pillars.map(([key,label,,items])=><div key={key}><h3>{label}</h3>
      <Slider label={label+" pillar"} value={config.pillars[key]} max={50} onChange={v=>mapValue("pillars",key,v)}/>
      {items.map(([id,name])=><label className={s.control} key={id} title={coverage ? coverage[id]+" observed stocks":undefined}><span>{name}{coverage?.[id]===0 && <small> · No data</small>}</span>
        <input type="checkbox" checked={config.factors[id]>0} onChange={()=>toggleFactor(id)}/></label>)}</div>)}
    <h3>Long-list filters</h3>{check("sector_neutral","Rank within sectors")}{num("max_pe","Maximum P/E (0 = off)",0,10000,.1)}
    {num("max_de","Maximum D/E (0 = off)",0,10000,.1)}{check("positive_fcf","Positive FCF yield")}
  </aside>;
  const items = factors[tab];
  const total = items.reduce((sum,[key])=>sum+config.factors[key],0);
  return <aside className={s.panel}><h2>{agentLabels[tab]} factors</h2>
    <p className={s.hint}>{tab==="sentiment"?"Seven-day news tone decays with a two-day half-life.":tab==="technical"?"Weight each indicator 0–10. Untick to drop it.":"Blend returns across lookbacks using cross-sectional percentile ranks."}</p>
    {items.map(([key,label])=><div className={s.factor} key={key}>
      <label title={coverage ? coverage[key]+" observed stocks":undefined}><input type="checkbox" checked={config.factors[key]>0} onChange={()=>toggleFactor(key)}/>
        <span>{label}{coverage?.[key]===0 && <small> · No data</small>}</span><small>{total?Math.round(100*config.factors[key]/total):0}%</small></label>
      <input aria-label={label+" weight"} type="range" min={0} max={10} value={config.factors[key]} onChange={e=>mapValue("factors",key,Number(e.target.value))}/>
    </div>)}
    {tab==="technical" && <><h3>Long-list filters</h3>{num("rsi_min","RSI minimum",0,config.rsi_max)}{num("rsi_max","RSI maximum",config.rsi_min,100)}
      {check("tech_above_ma","Only above 200-day avg")}{num("min_traded_value","Min daily traded value (₹)",0,1e13,100000)}</>}
    {tab==="sentiment" && <><h3>Rules</h3>{num("min_headlines","Min headlines in 7 days",0,10000)}
      {check("boost_sectors","Boost top 3 sectors (+10)")}<Control label="Short interest"><select value={config.short_squeeze?"squeeze":"avoid"}
        onChange={e=>change({...config,short_squeeze:e.target.value==="squeeze"})}><option value="avoid">High is bad</option><option value="squeeze">Squeeze potential</option></select></Control></>}
    {tab==="momentum" && <><h3>Options</h3>{check("vol_adjust","Volatility-adjust returns")}{check("mom_above_ma","Longs only above 200-day avg")}
      <p className={s.hint}>12–1 month return skips the most recent month.</p></>}
  </aside>;
}
