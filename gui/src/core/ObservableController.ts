/** React and non-React clients can subscribe to the same owned application state. */
export abstract class ObservableController {
  private listeners=new Set<()=>void>();
  private version=0;
  readonly subscribe=(listener:()=>void)=>{this.listeners.add(listener);return()=>{this.listeners.delete(listener);};};
  readonly getVersion=()=>this.version;
  protected changed():void{this.version++;for(const listener of this.listeners)listener();}
}
