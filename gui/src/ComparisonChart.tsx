import {useEffect, useLayoutEffect, useRef, useState} from 'react';
import Plotly from 'plotly.js-dist-min';
import {timeLabel} from './timeFormat';
import {ComparisonData, ComparisonMetadata, comparisonSeconds} from './useComparisonReader';

type Obj=Record<string,any>;
type Props={data?:ComparisonData;metadata?:ComparisonMetadata;sourceKey?:string;context:string;metric:string;visible:boolean;
  colors:Record<string,string>;onState:(state:Obj)=>void};

export default function ComparisonChart(props:Props) {
  const element=useRef<HTMLDivElement>(null),latest=useRef(props);latest.current=props;
  const work=useRef<Promise<unknown>>(Promise.resolve());
  const controller=useRef<{active:boolean;pending:boolean;queued:boolean;draw:()=>void}|undefined>(undefined);
  const axes=useRef<{following:boolean;x?:number[];y?:number[]}>({following:true});
  const [following,setFollowing]=useState(true),[error,setError]=useState(''),[retry,setRetry]=useState(0);
  const [drawn,setDrawn]=useState<{sourceKey?:string;metric:string}>();
  const reset=()=>{axes.current={following:true};setFollowing(true);controller.current?.draw();};
  useLayoutEffect(()=>{setDrawn(undefined);setError('');reset();},[props.context]);
  useEffect(()=>{
    const target=element.current!;let bound=false,renders=0,updating=0,userGesture=false;let rendered:Props|undefined;
    let gestureTimer:ReturnType<typeof setTimeout>|undefined;
    const control={active:true,pending:false,queued:false,draw:()=>{}};controller.current=control;
    const publish=()=>{
      if(!control.active||!rendered)return;
      latest.current.onState({context:rendered.context,source_key:rendered.sourceKey,metric:rendered.metric,
        following:axes.current.following,render_count:renders,listener_sets:bound?1:0,
        xaxis_range:[...((target as any)._fullLayout?.xaxis?.range||[])]});
    };
    const relayout=(event:any)=>{
      if(!control.active||(updating&&!userGesture))return;
      if(event['xaxis.autorange']===true){reset();return;}
      if(!Object.keys(event).some(key=>/^([xy]axis\.range|[xy]axis\.autorange)/.test(key)))return;
      const layout=(target as any)._fullLayout;axes.current={following:false,x:[...layout.xaxis.range],y:[...layout.yaxis.range]};
      setFollowing(false);publish();control.draw();
    };
    const gestureStart=()=>{clearTimeout(gestureTimer);userGesture=true;};
    const gestureEnd=()=>{clearTimeout(gestureTimer);gestureTimer=setTimeout(()=>{userGesture=false;},0);};
    const briefGesture=()=>{gestureStart();gestureEnd();};
    target.addEventListener('pointerdown',gestureStart,true);target.addEventListener('click',briefGesture,true);target.addEventListener('wheel',briefGesture,true);window.addEventListener('pointerup',gestureEnd,true);
    control.draw=()=>{
      control.pending=true;if(control.queued)return;control.queued=true;
      work.current=work.current.catch(()=>{}).then(async()=>{
        try{
          while(control.active&&controller.current===control&&control.pending){
            control.pending=false;const current=latest.current,data=current.data;
            if(!current.visible||data?.status!=='ready'||!data.sample_times.length)continue;
            const traces=data.runs.map(run=>({x:run.samples.map(sample=>sample.seconds),y:run.samples.map(sample=>sample[current.metric]),
              customdata:run.samples.map(sample=>[String(sample.time),String(sample.revision),timeLabel(sample.time)]),meta:{run_id:run.run_id},
              type:'scatter' as const,mode:'lines+markers' as const,cliponaxis:false,
              name:`seed ${current.metadata?.[run.run_id]?.seed} · ${run.run_id.slice(0,8)}`,
              line:{color:current.colors[run.run_id],width:2.5},marker:{size:run.samples.length===1?9:4,color:current.colors[run.run_id]},
              hovertemplate:'%{y} identities<br>Time %{customdata[2]} s · revision %{customdata[1]}<extra>%{fullData.name}</extra>'}));
            const start=comparisonSeconds(data.common_interval.start),end=comparisonSeconds(data.common_interval.end);
            const extent=start===end?[Math.max(0,start-.5),end+.5+(start===0?.5:0)]:[start,end];
            updating++;
            try{
              await Plotly.react(target,traces,{paper_bgcolor:'#15212c',plot_bgcolor:'#15212c',font:{color:'#9aafb9',family:'Inter, system-ui'},margin:{t:20,r:20,b:50,l:50},legend:{orientation:'h',y:1.2},
                xaxis:{title:{text:'Absolute simulation time (s)'},gridcolor:'#283743',range:axes.current.following?extent:axes.current.x,autorange:false},
                yaxis:{title:{text:`${current.metric} identities`},gridcolor:'#283743',rangemode:'tozero',...(axes.current.following?{autorange:true}:{range:axes.current.y,autorange:false})},
                uirevision:current.context,width:Math.max(1,target.clientWidth),height:Math.max(1,target.clientHeight),autosize:true},
                {responsive:true,displaylogo:false,toImageButtonOptions:{format:'svg',filename:'run-comparison'}});
            }finally{updating--;}
            if(!control.active||controller.current!==control)break;
            if(current.context!==latest.current.context){control.pending=true;continue;}
            if(!bound){(target as any).on('plotly_relayout',relayout);bound=true;}
            rendered=current;renders++;setError('');setDrawn({sourceKey:current.sourceKey,metric:current.metric});publish();
          }
        }catch(error:any){if(control.active)setError(error.message||'The comparison chart could not be drawn.');}
        finally{control.queued=false;if(control.active&&control.pending)control.draw();}
      });
    };
    const observer=new ResizeObserver(()=>control.draw());observer.observe(target);control.draw();
    return()=>{
      control.active=false;observer.disconnect();clearTimeout(gestureTimer);
      target.removeEventListener('pointerdown',gestureStart,true);target.removeEventListener('click',briefGesture,true);target.removeEventListener('wheel',briefGesture,true);window.removeEventListener('pointerup',gestureEnd,true);
      if(bound)(target as any).removeAllListeners('plotly_relayout');
      work.current=work.current.catch(()=>{}).then(()=>{if(controller.current===control){Plotly.purge(target);controller.current=undefined;}});
    };
  },[]);
  useEffect(()=>{controller.current?.draw();},[props.data,props.metadata,props.sourceKey,props.metric,props.visible,props.context,retry]);
  const ready=props.data?.status==='ready',current=drawn?.sourceKey===props.sourceKey&&drawn?.metric===props.metric;
  return <>
    <div className="chart-controls"><span data-testid="comparison-follow-state">{following?'Showing the common available interval':'Manual chart view · automatic axis movement paused'}</span><button data-testid="comparison-reset" onClick={reset} disabled={!ready||following}>Reset comparison view</button></div>
    {error&&<p className="statistics-error" role="alert">Chart unavailable: {error} The verified table and CSV remain available. <button onClick={()=>setRetry(value=>value+1)}>Retry chart</button></p>}
    <div className="comparison-plot-frame" hidden={!ready} aria-busy={!current}>
      <div ref={element} className="plot" data-testid="comparison-chart" style={{visibility:current?'visible':'hidden'}} aria-label="Selected population measure at shared simulation times for each run."/>
      {!current&&<p className="comparison-plot-pending">Drawing the verified comparison…</p>}
    </div>
    {ready&&props.data!.sample_times.length===1&&<p className="chart-note">One common observation is available. The wider axis only makes that point visible.</p>}
  </>;
}
