/** JSON transport stays separate from executable controller instances. */
export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | {[key:string]:JsonValue};
export type RecordData = Record<string, any>;
export interface HistoryCursor {run_id:string; time:string; revision:string}
export interface ViewBundle extends HistoryCursor {
  state:RecordData; metrics:RecordData; sequence:string; mode:string; committed_frontier:string;
}
export interface Disposable {dispose():void}
export type RequestTransport = (path:string, body?:RecordData, signal?:AbortSignal)=>Promise<any>;

/** Exact identity is independent of display rounding or chart coordinates. */
export class ExactTime {
  readonly numerator:bigint;
  readonly denominator:bigint;
  constructor(readonly wire:string) {
    const fraction=/^(-?\d+)\/(\d+)$/.exec(wire);
    if(fraction&&BigInt(fraction[2])>0n){this.numerator=BigInt(fraction[1]);this.denominator=BigInt(fraction[2]);return;}
    const decimal=/^([+-]?)(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(wire);
    if(!decimal)throw Error('Invalid exact time.');
    const exponent=Number(decimal[4]||0)-(decimal[3]||'').length;
    if(!Number.isSafeInteger(exponent)||Math.abs(exponent)>10000)throw Error('Invalid exact time.');
    const n=BigInt((decimal[1]==='-'?'-':'')+decimal[2]+(decimal[3]||''));
    this.numerator=exponent>=0?n*10n**BigInt(exponent):n;
    this.denominator=exponent>=0?1n:10n**BigInt(-exponent);
  }
  compare(other:ExactTime):bigint{return this.numerator*other.denominator-other.numerator*this.denominator;}
  equals(other:ExactTime):boolean{return this.compare(other)===0n;}
  toString():string{return this.wire;}
}
export class ExactCursor implements HistoryCursor {
  readonly run_id:string;readonly time:string;readonly revision:string;
  constructor(source:HistoryCursor){this.run_id=source.run_id;this.time=source.time;this.revision=source.revision;}
  equals(other:HistoryCursor):boolean {
    if(this.run_id!==other.run_id||this.revision!==other.revision)return false;
    if(this.time===other.time)return true;
    try{return new ExactTime(this.time).equals(new ExactTime(other.time));}catch{return false;}
  }
  toJSON():HistoryCursor{return {run_id:this.run_id,time:this.time,revision:this.revision};}
}
