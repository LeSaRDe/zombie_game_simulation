import {ObservableController} from './ObservableController';
import {RecordData,RequestTransport} from './contracts';
/** Polls one summary request at a time and preserves confirmed monotonic boundaries. */
export class RunCatalog extends ObservableController {
 rows:RecordData[]=[];
 state:{phase:'loading'|'ready'|'failed';error?:string;version?:number}={phase:'loading'};
 readonly request={current:0};private inFlight=false;private timer?:ReturnType<typeof setInterval>;private controller?:AbortController;
 perspective:()=>string=()=> 'researcher';onSummary:(row:RecordData)=>void=()=>{};
 constructor(private readonly transport:RequestTransport){super();}
 static newest(previous:RecordData|undefined,incoming:RecordData):RecordData {
  if(!previous)return incoming;
  if(previous.generation>incoming.generation)return previous;
  if(previous.generation===incoming.generation){const before=BigInt(previous.frontier?.revision??0),after=BigInt(incoming.frontier?.revision??0);if(before>after||(before===after&&previous.status_read_started_at>incoming.status_read_started_at))return previous;}
  return incoming;
 }
 setRows=(value:RecordData[]|((rows:RecordData[])=>RecordData[]))=>{this.rows=typeof value==='function'?value(this.rows):value;this.changed();};
 setState=(state:RunCatalog['state'])=>{this.state=state;this.changed();};
 refresh=async()=>{
  if(this.inFlight)return;this.inFlight=true;const token=++this.request.current,requestedAt=Date.now(),controller=this.controller=new AbortController();
  try{let data=await this.transport('/runs',undefined,controller.signal);if(controller.signal.aborted||token!==this.request.current)return;
   if(this.perspective()==='agent')data=data.map((item:RecordData)=>({...item,config:{scenario:item.config.scenario,seed:item.config.seed,horizon:item.config.horizon}}));
   for(const row of data)this.onSummary(row);
   this.rows=data.map((item:RecordData)=>RunCatalog.newest(this.rows.find(row=>row.id===item.id),{...item,status_read_started_at:requestedAt}));
   this.setState({phase:'ready',version:token});
  }catch(error:any){if(!controller.signal.aborted&&token===this.request.current)this.setState({phase:'failed',error:error.message});}
  finally{if(this.controller===controller){this.inFlight=false;this.controller=undefined;}}
 };
 start=()=>{void this.refresh();this.timer=setInterval(this.refresh,1000);};
 dispose=()=>{clearInterval(this.timer);this.controller?.abort();this.controller=undefined;this.inFlight=false;this.request.current++;};
}
