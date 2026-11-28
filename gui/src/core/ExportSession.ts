import {ObservableController} from './ObservableController';
export type ExportJob={id:string;status:string;active_tasks:number;artifact_url:string;provenance_url:string;error?:string;bytes?:number;[key:string]:unknown};
/** Owns exact export drafts and cancellable observation of independent export jobs. */
export class ExportSession extends ObservableController {
 format='scene_png';selected:string;start='0';end:string;interval='1';cohort='all';cohorts:{id?:string;name:string}[]=[];
 job:ExportJob|null=null;error='';pending=false;private disposed=false;private generation=0;private poll?:ReturnType<typeof setInterval>;private pollInFlight=false;private cohortAbort?:AbortController;private pollAbort?:AbortController;
 constructor(public runId:string,time:string,private readonly transport:typeof fetch=fetch){super();this.selected=time;this.end=time;}
 get active(){return !!this.job&&['PENDING','RUNNING','CANCELLING'].includes(this.job.status);}
 setFormat=(value:string)=>{this.format=value;this.changed();};setSelected=(value:string)=>{this.selected=value;this.changed();};setStart=(value:string)=>{this.start=value;this.changed();};setEnd=(value:string)=>{this.end=value;this.changed();};setInterval=(value:string)=>{this.interval=value;this.changed();};setCohort=(value:string)=>{this.cohort=value;this.changed();};
 private request=async(path:string,body?:Record<string,unknown>,signal?:AbortSignal):Promise<ExportJob>=>{
  const response=await this.transport.call(globalThis,path,{signal,...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});
  const text=await response.text();let result;try{result=JSON.parse(text);}catch{throw Error(`Export request returned ${response.status}: ${text.slice(0,120)}`);}
  if(!response.ok)throw Error(result.error||result.detail||'Export request failed');return result;
 };
 private setJob=(value:ExportJob)=>{this.job=value;this.changed();if(!this.active){clearInterval(this.poll);this.poll=undefined;}else if(!this.disposed&&!this.poll)this.poll=globalThis.setInterval(()=>void this.refresh(),100);};
 private refresh=async()=>{if(this.disposed||!this.active||!this.job||this.pollInFlight)return;this.pollInFlight=true;const identity=this.job.id,controller=this.pollAbort=new AbortController();try{const value=await this.request(`/api/export-jobs/${identity}`,undefined,controller.signal);if(!this.disposed&&!controller.signal.aborted&&this.job?.id===identity)this.setJob(value);}catch(error){if(!this.disposed&&!controller.signal.aborted){this.error=(error as Error).message;this.changed();}}finally{if(this.pollAbort===controller){this.pollInFlight=false;this.pollAbort=undefined;}}};
 load=(runId:string)=>{this.runId=runId;this.disposed=false;this.cohortAbort?.abort();const controller=this.cohortAbort=new AbortController();const generation=++this.generation;
  this.transport.call(globalThis,`/api/runs/${runId}/cohorts`,{signal:controller.signal}).then(response=>response.json()).then(rows=>{if(!controller.signal.aborted&&!this.disposed&&generation===this.generation&&Array.isArray(rows)){this.cohorts=rows.map(row=>row.definition);this.changed();}}).catch(()=>{});
  if(this.active&&!this.poll)this.poll=globalThis.setInterval(()=>void this.refresh(),100);
 };
 begin=async()=>{if(this.pending||this.active)return;this.error='';this.pending=true;this.changed();try{this.setJob(await this.request(`/api/runs/${this.runId}/exports`,{format:this.format,time:this.selected,interval:[this.start,this.end],sample_interval:this.interval,cohort:this.cohort}));}catch(error){this.error=(error as Error).message;}finally{this.pending=false;this.changed();}};
 cancel=async()=>{if(!this.job)return;this.error='';this.changed();try{this.setJob(await this.request(`/api/export-jobs/${this.job.id}/cancel`,{}));}catch(error){this.error=(error as Error).message;this.changed();}};
 dispose=()=>{this.disposed=true;this.generation++;clearInterval(this.poll);this.poll=undefined;this.cohortAbort?.abort();this.pollAbort?.abort();this.pollAbort=undefined;this.pollInFlight=false;};
}
