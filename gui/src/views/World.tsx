import {useEffect,useRef,useState} from 'react';
import {Obj,values,inspection} from '../uiRuntime';
import {WorldRenderer} from '../core/WorldRenderer';
export default function World({state,selected,onSelect,follow=false,layers}: {state:Obj; selected:string; onSelect:(id:string)=>void; follow?:boolean; layers?:Obj}) {
  const canvas=useRef<HTMLCanvasElement>(null); const frame=useRef<HTMLDivElement>(null);
  const [camera,setCamera]=useState({scale:1,x:0,y:0}); const [size,setSize]=useState({width:800,height:560});
  const pointer=useRef({x:0,y:0,down:false,moved:false});
  const world=state.world||{length:100,width:100}; const agents=values(state.agents);const aggregate=agents.length>5000&&camera.scale<2;
  useEffect(()=>{if(!frame.current)return;const observer=new ResizeObserver(([entry])=>setSize({width:entry.contentRect.width,height:entry.contentRect.height})); observer.observe(frame.current); return()=>observer.disconnect();},[]);
  const base=Math.max(.001,Math.min((size.width-48)/world.length,(size.height-48)/world.width));
  const scale=base*camera.scale;
  let x=(size.width-world.length*scale)/2+camera.x, y=(size.height-world.width*scale)/2+camera.y;
  if(follow&&selected&&state.agents?.[selected]) {x=size.width/2-state.agents[selected].x*scale;y=size.height/2-(world.width-state.agents[selected].y)*scale;}
  useEffect(()=>{
    if(!canvas.current)return;
    const renderer=new WorldRenderer(canvas.current,frame=>{inspection.world_frame=frame;});
    renderer.render({state,selected,camera,layers,world,agents,aggregate,scale,x,y,size});
  },[state,selected,camera,size,follow,layers]);
  return <div className="world-frame" data-glyph-semantics="screen_symbol" ref={frame}>{aggregate&&<span data-testid="aggregation-label" className="aggregation-label">Spatial aggregation</span>}<canvas ref={canvas} aria-label="World map. Use the searchable agent table below for keyboard-accessible selection." onWheel={e=>{e.preventDefault();setCamera(c=>({...c,scale:Math.max(.4,Math.min(30,c.scale*(e.deltaY<0?1.14:.88)))}));}} onPointerDown={e=>{pointer.current={x:e.clientX,y:e.clientY,down:true,moved:false};e.currentTarget.setPointerCapture(e.pointerId);}} onPointerMove={e=>{const p=pointer.current;if(!p.down)return;const dx=e.clientX-p.x,dy=e.clientY-p.y;if(Math.abs(dx)+Math.abs(dy)>2)p.moved=true;setCamera(c=>({...c,x:c.x+dx,y:c.y+dy}));p.x=e.clientX;p.y=e.clientY;}} onPointerUp={e=>{if(!pointer.current.moved){const r=e.currentTarget.getBoundingClientRect();const px=e.clientX-r.left,py=e.clientY-r.top;let best:Obj|undefined;let distance=15;for(const a of agents){const d=Math.hypot(a.x*scale+x-px,(world.width-a.y)*scale+y-py);if(d<distance){best=a;distance=d;}}if(best)onSelect(String(best.id));}pointer.current.down=false;}}/>
    <div className="map-tools"><button title="Zoom in" aria-label="Zoom in" onClick={()=>setCamera(c=>({...c,scale:Math.min(30,c.scale*1.5)}))}>＋</button><button title="Zoom out" aria-label="Zoom out" onClick={()=>setCamera(c=>({...c,scale:Math.max(.4,c.scale/1.5)}))}>−</button><button onClick={()=>setCamera({scale:1,x:0,y:0})}>Fit world</button><button onClick={()=>{const a=document.createElement('a');a.download=`world-r${state.revision}.png`;a.href=canvas.current!.toDataURL();a.click();}}>PNG</button></div>
  </div>;
}

