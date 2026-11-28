import {ObservableController} from './ObservableController';
import {RecordData as Obj} from './contracts';
export type Saved={path:string;body:Obj;operation:string};
const key='zombie.pending-command';
/** Persists immutable command intents and reconciles their original receipts on retry. */
export class CommandSession extends ObservableController {
 private readonly requests=new Set<AbortController>();
 private disposed=false;
 activate=()=>{this.disposed=false;};
 constructor(public run:Obj,public view:Obj,public onApplied:(result:Obj,operation:string)=>void,private readonly storage:Pick<Storage,'getItem'|'setItem'|'removeItem'>=localStorage,private readonly transport:typeof fetch=fetch){super();this.time=view.time;this.saved=this.readSaved();}
 open:boolean=false;
setOpen=(value:boolean|((previous:boolean)=>boolean))=>{this.open=typeof value==='function'?(value as (previous:boolean)=>boolean)(this.open):value;this.changed();};
operation:string='branch';
setOperation=(value:string|((previous:string)=>string))=>{this.operation=typeof value==='function'?(value as (previous:string)=>string)(this.operation):value;this.changed();};
commandId:string=crypto.randomUUID();
setCommandId=(value:string|((previous:string)=>string))=>{this.commandId=typeof value==='function'?(value as (previous:string)=>string)(this.commandId):value;this.changed();};
time:string='';
setTime=(value:string|((previous:string)=>string))=>{this.time=typeof value==='function'?(value as (previous:string)=>string)(this.time):value;this.changed();};
change:string=JSON.stringify({kind:'add_resource',resource:'FOOD',quantity:1,x:0,y:0},null,2);
setChange=(value:string|((previous:string)=>string))=>{this.change=typeof value==='function'?(value as (previous:string)=>string)(this.change):value;this.changed();};
pending:boolean=false;
setPending=(value:boolean|((previous:boolean)=>boolean))=>{this.pending=typeof value==='function'?(value as (previous:boolean)=>boolean)(this.pending):value;this.changed();};
saved:Saved|null=null;
setSaved=(value:Saved|null|((previous:Saved|null)=>Saved|null))=>{this.saved=typeof value==='function'?(value as (previous:Saved|null)=>Saved|null)(this.saved):value;this.changed();};
receipt:Obj|null=null;
setReceipt=(value:Obj|null|((previous:Obj|null)=>Obj|null))=>{this.receipt=typeof value==='function'?(value as (previous:Obj|null)=>Obj|null)(this.receipt):value;this.changed();};
error:string='';
setError=(value:string|((previous:string)=>string))=>{this.error=typeof value==='function'?(value as (previous:string)=>string)(this.error):value;this.changed();};
 private readSaved():Saved|null{try{return JSON.parse(this.storage.getItem(key)||'null');}catch{return null;}}
 private request=async(path:string,body?:Obj)=>{
 if(this.disposed)throw Error('Command observation was closed.');
 const controller=new AbortController();this.requests.add(controller);const timer=setTimeout(()=>controller.abort(),10000);
 let response:Response,text:string;
 try{response=await this.transport.call(globalThis,'/api'+path,{signal:controller.signal,...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});text=await response.text();}
 catch(e){if(controller.signal.aborted)throw Error('No command response was received within 10 seconds.');throw e;}
 finally{clearTimeout(timer);this.requests.delete(controller);}
 let result:Obj;
 try{result=text?JSON.parse(text):{};}catch{throw Error(`Request returned ${response.status}: ${text.slice(0,160)}`);}
 if(!response.ok)throw Object.assign(Error(result.error||result.detail||'Request failed'),{code:result.code,status:response.status});
 if(this.disposed||controller.signal.aborted)throw Error('Command observation was closed.');
 return result;
}

 execute = async (value: Saved, retry = false) => {
    if(this.pending)return;
    this.setPending(true);
    this.setError('');
    this.setReceipt(null);
    this.setSaved(value);
    this.storage.setItem(key, JSON.stringify(value));
    try {
        // Re-establish the local session and inspect the retained receipt first.
        // Resending the immutable original request also reconciles a reservation
        // whose process died before construction/start finished.
        if (retry) {
            try {
                await this.request('/commands/' + encodeURIComponent(value.body.command_id));
            }
            catch (e) {
                if ((e as Obj).status !== 404)
                    throw e;
            }
        }
        let result: Obj = await this.request(value.path, value.body);
        while (result.status === 'pending') {
            await new Promise(resolve => setTimeout(resolve, 150));
            result = await this.request('/commands/' + encodeURIComponent(value.body.command_id));
        }
        this.setReceipt(result);
        if (result.status === 'rejected')
            this.setError(result.error || 'Command rejected');
        else if (value.operation === 'start') {
            let started = await this.request('/commands/' + encodeURIComponent(value.body.command_id + ':start'));
            while (started.status === 'pending') {
                await new Promise(resolve => setTimeout(resolve, 150));
                started = await this.request('/commands/' + encodeURIComponent(value.body.command_id + ':start'));
            }
            if (started.status === 'rejected')
                this.setError(started.error || 'The run could not start');
            else
                this.onApplied({ ...result, generation: started.generation }, value.operation);
        }
        else
            this.onApplied(result, value.operation);
        this.storage.removeItem(key);
        this.setSaved(null);
        this.setCommandId(crypto.randomUUID());
    }
    catch (e) {
        this.setError((e as Error).message + ' Retry checks the original command receipt before sending it again.');
    }
    finally {
        this.setPending(false);
    }
}
submit = () => {
    try {
        const body: Obj = { command_id: this.commandId, generation: this.run.generation };
        let path = '/runs/' + this.run.id + '/commands';
        if (this.operation === 'start') {
            path = '/runs';
            body.config = this.run.config;
            body.start = true;
        }
        else if (this.operation === 'branch') {
            path = '/runs/' + this.run.id + '/branch';
            body.revision = this.view.revision;
            body.seed = this.run.config.seed;
        }
        else if (this.operation === 'intervention') {
            body.operation = 'intervene';
            body.change = JSON.parse(this.change);
            body.time = this.time;
            body.apply_now = this.time === this.view.time;
        }
        else
            body.operation = 'stop';
        this.execute({ path, body, operation: this.operation });
    }
    catch (e) {
        this.setError((e as Error).message);
    }
}

 dispose=()=>{this.disposed=true;for(const controller of this.requests)controller.abort();this.requests.clear();};
}
