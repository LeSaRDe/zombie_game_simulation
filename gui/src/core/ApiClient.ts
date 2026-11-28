import {RecordData} from './contracts';
export interface ApiInstrumentation {started?(path:string):void; completed?(path:string,elapsed:number,body?:RecordData):void}
/** Owns the transport policy; consumers receive plain data, never fetch responses. */
export class ApiClient {
  constructor(private readonly base='/api',private readonly instrumentation:ApiInstrumentation={},private readonly transport:typeof fetch=fetch){}
  async request(path:string,body?:RecordData,signal?:AbortSignal):Promise<any>{
    this.instrumentation.started?.(path);const sent=performance.now();
    const response=await this.transport.call(globalThis,this.base+path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal}:{signal});
    this.instrumentation.completed?.(path,performance.now()-sent,body);
    const text=await response.text();let data:RecordData;
    try{data=text?JSON.parse(text):{};}
    catch{throw Object.assign(Error(`The server returned ${response.status} without a valid JSON response. ${text.replace(/<[^>]*>/g,'').slice(0,160)}`),{status:response.status,code:'INVALID_RESPONSE'});}
    if(!response.ok)throw Object.assign(Error(data.error||data.detail||`Request failed (${response.status})`),{status:response.status,code:data.code,issues:data.issues});
    return data;
  }
}
