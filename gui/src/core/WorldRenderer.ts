import {RecordData as Obj} from './contracts';
import {agentStatus,colors,values} from '../uiRuntime';
/** Owns Canvas2D rendering independently of React and simulation state. */
export class WorldRenderer {
 constructor(private readonly canvas:HTMLCanvasElement,private readonly onFrame:(frame:Obj)=>void=()=>{}){}
 render({state,selected,camera,layers,world,agents,aggregate,scale,x,y,size}:{state:Obj;selected:string;camera:Obj;layers?:Obj;world:Obj;agents:Obj[];aggregate:boolean;scale:number;x:number;y:number;size:{width:number;height:number}}):void {
    const element=this.canvas;if(!element)return;const context=element.getContext('2d');if(!context)return;
    const dpr=window.devicePixelRatio||1;element.width=size.width*dpr;element.height=size.height*dpr;context.scale(dpr,dpr);
    context.fillStyle='#101a24';context.fillRect(0,0,size.width,size.height);
    context.save();context.translate(x,y+world.width*scale);context.scale(scale,-scale);
    context.fillStyle='#14232d';context.fillRect(0,0,world.length,world.width);
    context.strokeStyle='#233640';context.lineWidth=1/scale;
    const grid=10**Math.floor(Math.log10(world.length/8));
    for(let gx=0;gx<=world.length;gx+=grid){context.beginPath();context.moveTo(gx,0);context.lineTo(gx,world.width);context.stroke();}
    for(let gy=0;gy<=world.width;gy+=grid){context.beginPath();context.moveTo(0,gy);context.lineTo(world.length,gy);context.stroke();}
    for(const shelter of values(state.shelters)){const r=shelter.interior;if(r){context.fillStyle='#36554430';context.fillRect(r[0],r[1],r[2]-r[0],r[3]-r[1]);}}
    for(const b of values(state.barriers)){const r=b.footprint||b.rect;if(!r)continue;context.fillStyle=b.type==='Gate'?(b.mode==='OPEN'?'#78bd8a':b.mode==='BREACHED'?'#685941':'#d2a666'):b.type==='Barricade'?'#aa815d':'#5a727e';context.fillRect(r[0],r[1],r[2]-r[0],r[3]-r[1]);}
    if(layers?.resources!==false)for(const s of values(state.stockpiles)){context.fillStyle='#d9d8b2';context.fillRect(s.x-3/scale,s.y-3/scale,6/scale,6/scale);}
    if(layers?.remains!==false)for(const r of values(state.remains)){context.strokeStyle='#8f7887';context.beginPath();context.arc(r.x,r.y,3/scale,0,Math.PI*2);context.stroke();}
    if(aggregate&&layers?.agents!==false){
      const bins=new Map<string,{x:number,y:number,n:number,color:string}>();
      for(const a of agents){const px=a.x*scale+x,py=(world.width-a.y)*scale+y;if(px<0||py<0||px>size.width||py>size.height)continue;const color=colors[agentStatus(a)];const key=`${Math.floor(px/8)}:${Math.floor(py/8)}:${color}`;const bin=bins.get(key)||{x:0,y:0,n:0,color};bin.x+=a.x;bin.y+=a.y;bin.n++;bins.set(key,bin);}
      for(const bin of bins.values()){context.beginPath();context.fillStyle=bin.color;context.globalAlpha=Math.min(1,.35+Math.log2(bin.n+1)/6);context.arc(bin.x/bin.n,bin.y/bin.n,Math.min(7,2+Math.sqrt(bin.n))/scale,0,2*Math.PI);context.fill();}context.globalAlpha=1;
    }
    for(const a of agents){
      if(layers?.agents===false||aggregate&&String(a.id)!==selected)continue;
      if(a.x*scale+x < -10||(world.width-a.y)*scale+y < -10||a.x*scale+x>size.width+10||(world.width-a.y)*scale+y>size.height+10)continue;
      const status=agentStatus(a);const radius=(String(a.id)===selected?6:Math.max(2.6,Math.min(4,camera.scale*2)))/scale;
      if(layers?.sensing&&String(a.id)===selected){context.beginPath();context.arc(a.x,a.y,a.sense_r||a.sensing_radius||a.effective_sensing||30,0,Math.PI*2);context.fillStyle='#77d5c512';context.fill();context.strokeStyle='#77d5c560';context.stroke();}
      const path=state.occurrences?.[a.active_action]?.parameters?.path;if(layers?.trails&&path){context.beginPath();for(const [i,p]of path.entries())i?context.lineTo(p.x,p.y):context.moveTo(p.x,p.y);context.strokeStyle='#76b6c760';context.stroke();}
      context.fillStyle=colors[status];context.strokeStyle=colors[status];context.lineWidth=1.5/scale;context.beginPath();
      if(status==='dead'){context.moveTo(a.x-radius,a.y-radius);context.lineTo(a.x+radius,a.y+radius);context.moveTo(a.x+radius,a.y-radius);context.lineTo(a.x-radius,a.y+radius);context.stroke();}
      else if(a.type==='Zombie'){context.moveTo(a.x,a.y-radius*1.3);context.lineTo(a.x+radius,a.y+radius);context.lineTo(a.x-radius,a.y+radius);context.closePath();context.fill();}
      else{context.arc(a.x,a.y,radius,0,Math.PI*2);context.fill();if(status==='infected'){context.strokeStyle='#f4bc65';context.beginPath();context.arc(a.x,a.y,radius+2/scale,0,Math.PI*2);context.stroke();}}
      if(String(a.id)===selected){context.strokeStyle='#fff';context.beginPath();context.arc(a.x,a.y,radius+4/scale,0,Math.PI*2);context.stroke();}
      if(layers?.labels&&(camera.scale>2||String(a.id)===selected)){context.fillStyle='#d9e4e7';context.font=`${11/scale}px system-ui`;context.save();context.translate(a.x,a.y);context.scale(1,-1);context.fillText(`${a.id}${a.role?' · '+a.role:''}`,8/scale,-7/scale);context.restore();}
      if(layers?.actions&&a.active_action){context.strokeStyle='#d9e4e7';context.beginPath();context.moveTo(a.x-radius,a.y+radius+4/scale);context.lineTo(a.x+radius,a.y+radius+4/scale);context.stroke();}
    }
    context.strokeStyle='#4a626d';context.strokeRect(0,0,world.length,world.width);context.restore();
    context.fillStyle='#8fa3b0';context.font='11px system-ui';context.fillText(`${world.length} × ${world.width} m · ${agents.length.toLocaleString()} identities`,16,size.height-16);
    this.onFrame({at:performance.now(),selected,camera:{...camera},time:state.time,revision:String(state.revision)});
 }
}
