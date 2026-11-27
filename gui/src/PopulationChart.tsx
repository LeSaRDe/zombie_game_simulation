import {useEffect, useLayoutEffect, useRef, useState} from 'react';
import Plotly from 'plotly.js-dist-min';
import {MetricCursor} from './useStatisticsReader';

type Obj=Record<string,any>;
type Props={samples:Obj[];cursor?:MetricCursor;selected:MetricCursor;mode:'live'|'replay';visible:boolean;colors:Record<string,string>;
  onSeek:(time:string,revision?:string)=>void;onState:(state:Obj)=>void};

function recordedTimeError(value:string):string {
  const text=value.trim();
  if(!text)return 'Enter a recorded time in seconds. This field is empty.';
  const fraction=/^([+-]?\d+)\/(\d+)$/.exec(text);
  if(fraction){
    if(BigInt(fraction[2])===0n)return 'The denominator must be greater than zero.';
    return BigInt(fraction[1])<0n?'Enter zero or a positive recorded time.':'';
  }
  if(!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(text))return 'Enter a complete time, such as 0, 2.5 or 5/2 seconds.';
  if(!Number.isFinite(Number(text)))return 'Enter a finite recorded time.';
  if(text.startsWith('-')&&/[1-9]/.test(text.split(/[eE]/)[0]))return 'Enter zero or a positive recorded time.';
  return '';
}

export default function PopulationChart(props:Props) {
  const element=useRef<HTMLDivElement>(null);
  const latest=useRef(props);latest.current=props;
  const work=useRef<Promise<unknown>>(Promise.resolve());
  const controller=useRef<{active:boolean;pending:boolean;queued:boolean;draw:()=>void}|undefined>(undefined);
  // An untouched editor follows the selected view, independently of a slower
  // metrics response. Once edited, its exact text belongs to this run only.
  const [timeDraft,setTimeDraft]=useState<{runId:string;text:string}>();
  const [timeError,setTimeError]=useState('');
  const edited=timeDraft?.runId===props.selected.run_id;
  const chartTime=edited?timeDraft!.text:props.selected.time;
  useLayoutEffect(()=>{setTimeDraft(undefined);setTimeError('');},[props.selected.run_id]);
  const inspectTime=()=>{
    const problem=recordedTimeError(chartTime);setTimeError(problem);
    if(!problem)props.onSeek(chartTime.trim(),edited?undefined:props.selected.revision);
  };
  const [error,setError]=useState('');
  const [retry,setRetry]=useState(0);
  const [following,setFollowing]=useState(true);
  const [drawnCursor,setDrawnCursor]=useState<MetricCursor>();
  const axes=useRef<{following:boolean;x?:number[];y?:number[]}>({following:true});
  const chartContext=`${props.cursor?.run_id||''}:${props.mode}:${props.mode==='replay'?`${props.cursor?.time||''}:${props.cursor?.revision||''}`:''}`;
  const contextRef=useRef(chartContext);contextRef.current=chartContext;
  const reset=()=>{axes.current={following:true};setFollowing(true);controller.current?.draw();};
  useLayoutEffect(()=>{setDrawnCursor(undefined);reset();},[chartContext]);

  useEffect(()=>{
    const target=element.current!;let bound=false,renders=0,updating=0,userGesture=false;let rendered:Props|undefined;
    let gestureTimer:ReturnType<typeof setTimeout>|undefined;
    const control={active:true,pending:false,queued:false,draw:()=>{}};
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
              customdata:current.samples.map(sample=>[String(sample.time),String(sample.revision)]),
              type:'scatter' as const,mode:'lines+markers' as const,cliponaxis:false,
              name:name[0].toUpperCase()+name.slice(1),line:{color:current.colors[name],width:2.5},
              marker:{size:current.samples.length===1?9:4,color:current.colors[name]},
              hovertemplate:'%{y} identities<br>Time %{customdata[0]} s · revision %{customdata[1]}<extra>%{fullData.name}</extra>',
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
    return()=>{
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
  },[]);
  useEffect(()=>{controller.current?.draw();},[props.samples,props.cursor,props.mode,props.visible,retry]);
  return <>
    <div className="chart-controls"><span data-testid="chart-follow-state">{following?(props.mode==='live'?'Following verified live time':'Showing the verified history extent'):'Manual chart view · automatic axis movement paused'}</span><button data-testid="chart-follow-reset" onClick={reset} disabled={following}>{props.mode==='live'?'Follow latest chart samples':'Reset chart view'}</button></div>
    {props.samples.length>0&&props.samples.at(-1)!.seconds===0&&<p className="chart-note">The initial chart spans one second for visibility. The recorded simulation time is still zero.</p>}
    {error&&<p className="statistics-error" role="alert">Chart unavailable: {error} The population table remains available. <button onClick={()=>setRetry(value=>value+1)}>Retry chart</button></p>}
    <div ref={element} hidden={!props.samples.length} className="plot" data-testid="population-chart" aria-label="Population over simulated time. Click a sample to inspect its recorded time and revision."/>
    <p className="chart-note" data-testid="chart-source">{props.samples.length&&drawnCursor?`Chart through ${drawnCursor.time} s · revision ${drawnCursor.revision}`:'Waiting for population samples.'}</p>
    <label>Recorded time to inspect (s)<input data-testid="chart-time" value={chartTime} aria-invalid={Boolean(timeError)} aria-describedby={timeError?'chart-time-help chart-time-error':'chart-time-help'} onChange={event=>{setTimeDraft({runId:props.selected.run_id,text:event.target.value});setTimeError('');}} onKeyDown={event=>{if(event.key==='Enter'){event.preventDefault();inspectTime();}}}/></label>
    <p className="chart-note" id="chart-time-help">{edited?'Your edited time stays fixed as the simulation advances.':'This field follows the selected view until you edit it.'} Inspecting recorded history changes the viewer only.</p>
    {timeError&&<p className="statistics-error" id="chart-time-error" data-testid="chart-time-error" role="alert">{timeError}</p>}
    <button data-testid="chart-select" onClick={inspectTime}>Inspect recorded time</button>
    {edited&&<button data-testid="chart-time-reset" onClick={()=>{setTimeDraft(undefined);setTimeError('');}}>Use selected view time</button>}
  </>;
}
