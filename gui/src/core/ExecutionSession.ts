import {ObservableController} from './ObservableController';
import {RecordData,RequestTransport} from './contracts';
import {RunCatalog} from './RunCatalog';
import {isInactiveRun} from '../runLifecycle';
export interface ExecutionContext {identity():string;run():RecordData|undefined;starting(identity:string):boolean;live():boolean;loadView():Promise<unknown>;requested(operation:string):void;applied(operation:string,result:RecordData):void;error(message:string):void}
/** Owns command serialization and confirmed control generations for the workspace. */
export class ExecutionSession extends ObservableController {
 readonly generations={current:{} as Record<string,number>};pending=false;terminationRequest='';result?:RecordData;
 constructor(public context:ExecutionContext,private readonly catalog:RunCatalog,private readonly transport:RequestTransport,private readonly identity:()=>string=()=>crypto.randomUUID()){super();}
 setResult=(result:RecordData)=>{this.result=result;this.changed();};
 execute=async(operation:string,extra:RecordData={})=>{
  const identity=this.context.identity();if(!identity||this.pending||this.context.starting(identity))return;
  const requestedAt=Date.now();this.pending=true;this.terminationRequest=operation==='terminate'?identity:'';this.changed();this.context.error('');this.context.requested(operation);
  try{
   let result=await this.transport(`/runs/${identity}/commands`,{operation,command_id:this.identity(),generation:this.generations.current[identity]??this.context.run()?.generation,...extra});
   while(result.status==='pending'){await new Promise(resolve=>setTimeout(resolve,150));result=await this.transport(`/commands/${result.command_id}`);}
   this.setResult(result);if(result.status==='rejected')throw Error(result.error);this.generations.current[identity]=result.generation;
   this.catalog.setRows(rows=>rows.map(row=>row.id===identity?RunCatalog.newest(row,{...row,generation:result.generation,status:result.run_status,status_read_started_at:requestedAt,resource_status:operation==='terminate'?{...row.resource_status,phase:'stopping',cleanup_complete:false}:row.resource_status,frontier:{...row.frontier,time:result.time,revision:result.revision,generation:result.generation,status:result.run_status,pacing:result.pacing??row.frontier?.pacing}}):row));
   if(identity===this.context.identity()){this.context.applied(operation,result);if(this.context.live()&&!isInactiveRun({status:result.run_status}))await this.context.loadView();}
   await this.catalog.refresh();
  }catch(error:any){if(identity===this.context.identity())this.context.error(error.message);await this.catalog.refresh();}
  finally{this.pending=false;this.terminationRequest='';this.changed();}
 };
}
