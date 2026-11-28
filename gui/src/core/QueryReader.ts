import {Disposable} from './contracts';
export interface QueryReaderOptions {
  current():boolean;
  read(signal:AbortSignal):Promise<void>;
  interval?:number;
}
/** A reader owns one cancellable polling lifecycle and never overlaps requests. */
export class QueryReader implements Disposable {
  private controller=new AbortController();
  private timer:ReturnType<typeof setInterval>|undefined;
  private active=false;
  private inFlight=false;
  private successfulKey='';
  private failedKey='';
  constructor(private readonly options:QueryReaderOptions){}
  get signal():AbortSignal{return this.controller.signal;}
  get current():boolean{return this.active&&!this.signal.aborted&&this.options.current();}
  accepts(key:string):boolean{return this.current&&key!==this.successfulKey&&key!==this.failedKey;}
  succeeded(key:string):void{this.successfulKey=key;this.failedKey='';}
  failed(key:string):void{this.failedKey=key;}
  seed(key:string):void{this.successfulKey=key;}
  start():this{
    if(this.active)return this;this.active=true;
    void this.tick();this.timer=setInterval(()=>void this.tick(),this.options.interval??500);return this;
  }
  async tick():Promise<void>{
    if(!this.current||this.inFlight)return;
    this.inFlight=true;
    try{await this.options.read(this.signal);}finally{this.inFlight=false;}
  }
  dispose():void{this.active=false;this.controller.abort();if(this.timer!==undefined)clearInterval(this.timer);this.timer=undefined;}
}
