import {ApiClient} from './core/ApiClient';
import {RequestTransport} from './core/contracts';
export type Obj = Record<string, any>;
export type ViewerLoad = {phase:'idle'|'initializing'|'loading'|'ready'|'failed';run_id:string;error?:string;details?:boolean};
export type Bundle = {state: Obj; metrics: Obj; time: string; revision: string; sequence: string; mode: string; run_id: string; committed_frontier: string};
export const inspection:Obj={transport:{snapshot_requests:0,application_trace:[],max_queue_depth:0,queue_depth:0,receipt_latencies_ms:[]},configuration:{}};
Object.defineProperty(window,'__zombieInspection',{get:()=>structuredClone(inspection)});
Object.defineProperty(window,'__zombieMeasurements',{get:()=>structuredClone({world_frame:inspection.world_frame,react_commit:inspection.react_commit,transport:inspection.transport})});
export const colors: Obj = {healthy: '#77d5c5', infected: '#f4bc65', zombies: '#ef8796', dead: '#88919c'};
export const values = (v: any): Obj[] => Array.isArray(v) ? v : Object.values(v || {});
export const seconds = (v: any): number => { const parts=String(v??0).split('/').map(Number); return parts[0]/(parts[1]||1); };
export const fixed = (v: any) => Number(seconds(v)).toLocaleString(undefined,{maximumFractionDigits:2});
export const id = () => crypto.randomUUID();
export const apiClient=new ApiClient('/api',{
 started:path=>{if(path.includes('/view'))inspection.transport.snapshot_requests++;},
 completed:(path,elapsed,body)=>{if(body&&path.endsWith('/commands'))inspection.transport.receipt_latencies_ms.push(elapsed);},
});
export const api:RequestTransport=(path,body,signal)=>apiClient.request(path,body,signal);
export function download(name: string, content: string, type='application/json') {
  const url=URL.createObjectURL(new Blob([content],{type})); const a=document.createElement('a'); a.href=url; a.download=name; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
}
export const agentStatus = (a: Obj) => a.status==='DEAD'||a.life===0?'dead':a.type==='Zombie'?'zombies':a.status==='INFECTED'||a.infection_episode?'infected':'healthy';

