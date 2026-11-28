import {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {PopulationPresenter} from './core/PopulationPresenter';
import {PlotlyHost} from './core/PlotlyHost';
import {MetricCursor} from './useStatisticsReader';
import {ExactTimeInput, TimeValue} from './TimeValue';
import {timeLabel} from './timeFormat';

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
  const [host]=useState(()=>new PlotlyHost());const {controller,axes}=host;
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
  const chartContext=`${props.cursor?.run_id||''}:${props.mode}:${props.mode==='replay'?`${props.cursor?.time||''}:${props.cursor?.revision||''}`:''}`;
  const contextRef=useRef(chartContext);contextRef.current=chartContext;
  const reset=()=>{axes.current={following:true};setFollowing(true);controller.current?.draw();};
  useLayoutEffect(()=>{setDrawnCursor(undefined);reset();},[chartContext]);

  useEffect(()=>{
    const presenter=new PopulationPresenter(element.current!,latest,host,reset,setFollowing,setError,setDrawnCursor,contextRef);
    return()=>presenter.dispose();
  },[]);  useEffect(()=>{controller.current?.draw();},[props.samples,props.cursor,props.mode,props.visible,retry]);
  return <>
    <div className="chart-controls"><span data-testid="chart-follow-state">{following?(props.mode==='live'?'Following verified live time':'Showing the verified history extent'):'Manual chart view · automatic axis movement paused'}</span><button data-testid="chart-follow-reset" onClick={reset} disabled={following}>{props.mode==='live'?'Follow latest chart samples':'Reset chart view'}</button></div>
    {props.samples.length>0&&props.samples.at(-1)!.seconds===0&&<p className="chart-note">The initial chart spans one second for visibility. The recorded simulation time is still zero.</p>}
    {error&&<p className="statistics-error" role="alert">Chart unavailable: {error} The population table remains available. <button onClick={()=>setRetry(value=>value+1)}>Retry chart</button></p>}
    <div ref={element} hidden={!props.samples.length} className="plot" data-testid="population-chart" aria-label="Population over simulated time. Click a sample to inspect its recorded time and revision."/>
    <p className="chart-note" data-testid="chart-source" data-exact-time={drawnCursor?.time} data-revision={drawnCursor?.revision}>{props.samples.length&&drawnCursor?<>Chart through <TimeValue value={drawnCursor.time}/> · revision {drawnCursor.revision}</>:'Waiting for population samples.'}</p>
    <ExactTimeInput label="Recorded time to inspect (s)" data-testid="chart-time" value={chartTime} aria-invalid={Boolean(timeError)} aria-describedby={timeError?'chart-time-help chart-time-error':'chart-time-help'} onChange={event=>{setTimeDraft({runId:props.selected.run_id,text:event.target.value});setTimeError('');}} onKeyDown={event=>{if(event.key==='Enter'){event.preventDefault();inspectTime();}}}/>
    <p className="chart-note" id="chart-time-help">{edited?'Your edited time stays fixed as the simulation advances.':'This field follows the selected view until you edit it.'} Inspecting recorded history changes the viewer only.</p>
    {timeError&&<p className="statistics-error" id="chart-time-error" data-testid="chart-time-error" role="alert">{timeError}</p>}
    <button data-testid="chart-select" onClick={inspectTime}>Inspect recorded time</button>
    {edited&&<button data-testid="chart-time-reset" onClick={()=>{setTimeDraft(undefined);setTimeError('');}}>Use selected view time</button>}
  </>;
}
