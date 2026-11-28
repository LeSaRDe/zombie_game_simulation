import Plotly from 'plotly.js-dist-min';
import {timeLabel} from '../timeFormat';
import type {MetricCursor} from '../useStatisticsReader';
import {ComparisonData,ComparisonMetadata,comparisonSeconds} from '../useComparisonReader';
import {PlotlyHost,Ref} from './PlotlyHost';
type Obj=Record<string,any>;
export type PopulationChartProps={samples:Obj[];cursor?:MetricCursor;selected:MetricCursor;mode:'live'|'replay';visible:boolean;colors:Record<string,string>;
  onSeek:(time:string,revision?:string)=>void;onState:(state:Obj)=>void};

type Props=PopulationChartProps;
/** Owns Plotly drawing, interaction listeners, resizing and queued teardown. */
export class PopulationPresenter {
 active=true;pending=false;queued=false;draw:()=>void=()=>{};dispose:()=>void=()=>{};
 constructor(element:HTMLDivElement,latest:Ref<Props>,host:PlotlyHost,reset:()=>void,setFollowing:(value:boolean)=>void,setError:(value:string)=>void,setDrawnCursor:(value:MetricCursor|undefined)=>void,contextRef:Ref<string>){
 const {work,controller,axes}=host;
    const target=element;let bound=false,renders=0,updating=0,userGesture=false;let rendered:Props|undefined;
    let gestureTimer:ReturnType<typeof setTimeout>|undefined;
    const control=this;
    controller.current=control;
    const click=(event:any)=>{
      const source=event.points?.[0]?.customdata;
      if(control.active&&source)latest.current.onSeek(String(source[0]),String(source[1]));
    };
    const publish=()=>{
      if(!rendered||!control.active)return;
      latest.current.onState({run_id:rendered.cursor?.run_id,time:rendered.cursor?.time,revision:rendered.cursor?.revision,
        mode:rendered.mode,following:axes.current.following,render_count:renders,listener_sets:bound?1:0,
        xaxis_range:[...((target as any)._fullLayout?.xaxis?.range||[])]});
    };
    const relayout=(event:any)=>{
      if(!control.active||(updating&&!userGesture))return;
      if(event['xaxis.autorange']===true){reset();return;}
      if(!Object.keys(event).some(key=>/^([xy]axis\.range|[xy]axis\.autorange)/.test(key)))return;
      const layout=(target as any)._fullLayout;
      axes.current={following:false,x:[...layout.xaxis.range],y:[...layout.yaxis.range]};
      setFollowing(false);publish();control.draw();
    };
    const gestureStart=()=>{clearTimeout(gestureTimer);userGesture=true;};
    const gestureEnd=()=>{clearTimeout(gestureTimer);gestureTimer=setTimeout(()=>{userGesture=false;},0);};
    const briefGesture=()=>{gestureStart();gestureEnd();};
    target.addEventListener('pointerdown',gestureStart,true);
    target.addEventListener('click',briefGesture,true);
    target.addEventListener('wheel',briefGesture,true);
    window.addEventListener('pointerup',gestureEnd,true);
    control.draw=()=>{
      control.pending=true;
      if(control.queued)return;control.queued=true;
      work.current=work.current.catch(()=>{}).then(async()=>{
        try{
          while(control.active&&controller.current===control&&control.pending){
            control.pending=false;const current=latest.current;const renderContext=contextRef.current;
            if(!current.visible||!current.samples.length)continue;
            const traces=Object.keys(current.colors).map(name=>({
              x:current.samples.map(sample=>sample.seconds),y:current.samples.map(sample=>sample[name]),
              customdata:current.samples.map(sample=>[String(sample.time),String(sample.revision),timeLabel(sample.time)]),
              type:'scatter' as const,mode:'lines+markers' as const,cliponaxis:false,
              name:name[0].toUpperCase()+name.slice(1),line:{color:current.colors[name],width:2.5},
              marker:{size:current.samples.length===1?9:4,color:current.colors[name]},
              hovertemplate:'%{y} identities<br>Time %{customdata[2]} s · revision %{customdata[1]}<extra>%{fullData.name}</extra>',
            }));
            const lastTime=current.samples.at(-1)!.seconds;
            const xRange=axes.current.following?[0,lastTime>0?lastTime:1]:axes.current.x;
            updating++;
            try{await Plotly.react(target,traces,{paper_bgcolor:'#15212c',plot_bgcolor:'#15212c',font:{color:'#9aafb9',family:'Inter, system-ui'},margin:{t:20,r:20,b:45,l:45},legend:{orientation:'h',y:1.2},
              xaxis:{title:{text:'Simulation time (s)'},gridcolor:'#283743',range:xRange,autorange:false},
              yaxis:{title:{text:'Identities'},gridcolor:'#283743',rangemode:'tozero',...(axes.current.following?{autorange:true}:{range:axes.current.y,autorange:false})},
              uirevision:renderContext,width:Math.max(1,target.clientWidth),height:Math.max(1,target.clientHeight),autosize:true},
              {responsive:true,displaylogo:false,toImageButtonOptions:{format:'svg',filename:'population'}});}
            finally{updating--;}
            if(!control.active||controller.current!==control)break;
            if(renderContext!==contextRef.current){control.pending=true;continue;}
            if(!bound){(target as any).on('plotly_click',click);(target as any).on('plotly_relayout',relayout);bound=true;}
            rendered=current;renders++;setError('');setDrawnCursor(current.cursor);publish();
          }
        }catch(error:any){if(control.active)setError(error.message||'The population chart could not be drawn.');}
        finally{control.queued=false;if(control.active&&control.pending)control.draw();}
      });
    };
    const observer=new ResizeObserver(()=>control.draw());observer.observe(target);
    control.draw();
    this.dispose=()=>{
      control.active=false;observer.disconnect();clearTimeout(gestureTimer);
      target.removeEventListener('pointerdown',gestureStart,true);
      target.removeEventListener('click',briefGesture,true);
      target.removeEventListener('wheel',briefGesture,true);
      window.removeEventListener('pointerup',gestureEnd,true);
      if(bound){(target as any).removeAllListeners('plotly_click');(target as any).removeAllListeners('plotly_relayout');}
      // Serialise teardown with pending renders. Strict Mode may immediately
      // mount a new owner of the same element; do not purge that owner's chart.
      work.current=work.current.catch(()=>{}).then(()=>{if(controller.current===control){Plotly.purge(target);controller.current=undefined;}});
    };
 }
}
