import {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {ComparisonPresenter} from './core/ComparisonPresenter';
import {PlotlyHost} from './core/PlotlyHost';
import {timeLabel} from './timeFormat';
import {ComparisonData, ComparisonMetadata, comparisonSeconds} from './useComparisonReader';

type Obj=Record<string,any>;
type Props={data?:ComparisonData;metadata?:ComparisonMetadata;sourceKey?:string;context:string;metric:string;visible:boolean;
  colors:Record<string,string>;onState:(state:Obj)=>void};

export default function ComparisonChart(props:Props) {
  const element=useRef<HTMLDivElement>(null),latest=useRef(props);latest.current=props;
  const [host]=useState(()=>new PlotlyHost());const {controller,axes}=host;
  const [following,setFollowing]=useState(true),[error,setError]=useState(''),[retry,setRetry]=useState(0);
  const [drawn,setDrawn]=useState<{sourceKey?:string;metric:string}>();
  const reset=()=>{axes.current={following:true};setFollowing(true);controller.current?.draw();};
  useLayoutEffect(()=>{setDrawn(undefined);setError('');reset();},[props.context]);
  useEffect(()=>{
    const presenter=new ComparisonPresenter(element.current!,latest,host,reset,setFollowing,setError,setDrawn);
    return()=>presenter.dispose();
  },[]);  useEffect(()=>{controller.current?.draw();},[props.data,props.metadata,props.sourceKey,props.metric,props.visible,props.context,retry]);
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
