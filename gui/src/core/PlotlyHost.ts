export type Ref<T>={current:T};
export interface PlotlyOwner {active:boolean;pending:boolean;queued:boolean;draw():void;dispose():void}
/** Keeps render/teardown ordering across React Strict Mode's successive owners. */
export class PlotlyHost {
 readonly work:Ref<Promise<unknown>>={current:Promise.resolve()};
 readonly controller:Ref<PlotlyOwner|undefined>={current:undefined};
 readonly axes:Ref<{following:boolean;x?:number[];y?:number[]}>={current:{following:true}};
 reset=()=>{this.axes.current={following:true};this.controller.current?.draw();};
 dispose=()=>this.controller.current?.dispose();
}
