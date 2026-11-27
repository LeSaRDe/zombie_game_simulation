import {useLayoutEffect, useRef} from 'react';
import ComparisonChart from './ComparisonChart';
import {ComparisonMetadata, ComparisonRead, ComparisonSource} from './useComparisonReader';

type Obj=Record<string,any>;
export const comparisonMeasures:Record<string,string>={healthy:'Healthy humans',infected:'Infected humans',zombies:'Living zombies',dead:'Dead identities'};
const csvValue=(value:unknown)=>`"${String(value??'').replace(/"/g,'""')}"`;
export function comparisonCSV(read:ComparisonRead):string {
  const data=read.data;if(data?.status!=='ready')return '';
  const columns=['run_id','scenario','seed','requested_time','requested_revision','common_start','common_end','sample_interval','measurement_version','definition','units','time','revision','healthy','infected','zombies','dead','total'];
  return columns.join(',')+'\n'+data.runs.flatMap(run=>run.samples.map(sample=>[
    run.run_id,read.metadata?.[run.run_id]?.scenario,read.metadata?.[run.run_id]?.seed,
    run.requested_cursor.time,run.requested_cursor.revision,data.common_interval.start,data.common_interval.end,
    data.sample_interval,data.version,data.definition,'identities',sample.time,sample.revision,sample.healthy,sample.infected,sample.zombies,sample.dead,sample.total,
  ].map(csvValue).join(','))).join('\n')+'\n';
}

export default function ComparisonPanel({runs,chosen,onChoose,metric,onMetric,read,context,requestedSources,stale,unavailable,visible,onRetry,onExport,onChartState}:{
  runs:Obj[];chosen:string[];onChoose:(ids:string[])=>void;metric:string;onMetric:(measure:string)=>void;
  read:ComparisonRead;context:string;requestedSources:ComparisonSource[];stale:boolean;
  unavailable:{run_id:string;message:string}[];visible:boolean;onRetry:()=>void;
  onExport:(name:string,content:string,type:string)=>void;onChartState:(state:Obj)=>void;
}) {
  const colors=useRef<Record<string,string>>({});
  const palette=['#77d5c5','#f4bc65','#ef8796','#a7a2ed','#88bdee','#e6bded','#a9d07a','#e39d76'];
  for(const identity of chosen)if(!colors.current[identity]){
    const slot=Object.keys(colors.current).length;colors.current[identity]=palette[slot]||`hsl(${(slot*137.508)%360} 60% 70%)`;
  }
  const data=read.data,ready=data?.status==='ready',busy=read.phase==='loading'||read.phase==='refreshing';
  const displayedStale=Boolean(data&&(stale||read.phase==='failed'||read.phase==='refreshing'));
  const label=(identity:string,metadata:ComparisonMetadata|undefined=read.metadata)=>`${metadata?.[identity]?.scenario||runs.find(run=>run.id===identity)?.config?.scenario||'Run'} · ${identity.slice(0,8)}`;
  const requestedNames=requestedSources.map(source=>label(source.run_id,{})).join(', ');
  const change=(identity:string,checked:boolean)=>onChoose(checked?[...chosen,identity]:chosen.filter(id=>id!==identity));
  const rows=data?.status==='ready'?data.runs.flatMap(run=>run.samples.map(sample=>({run,sample}))):[];
  // An obsolete rendered chart must not remain visible as the new selection.
  useLayoutEffect(()=>{onChartState({context,source_key:undefined,metric,following:true,render_count:0,listener_sets:0,xaxis_range:[]});},[context]);
  return <section className="statistics comparison-panel" data-testid="comparison-panel" aria-busy={busy}>
    <h2>Compare independent runs</h2>
    <p>Choose two to four runs. Their observations share absolute simulation time through the earliest selected frontier. Each run keeps its own causal revisions. Comparison reads recorded history and does not change execution.</p>
    <fieldset className="comparison-selection"><legend>Runs to compare · {chosen.length} of 4 selected</legend><div className="comparison-choices">
      {runs.map(run=><label className="check" key={run.id}><input data-testid="comparison-choice" data-run-id={run.id} type="checkbox" checked={chosen.includes(run.id)} disabled={!chosen.includes(run.id)&&chosen.length>=4} onChange={event=>change(run.id,event.target.checked)}/><span><strong>{run.config.scenario||'Untitled scenario'}</strong><span>Seed {run.config.seed} · {run.status}</span><code>{run.id}</code>{run.status==='initializing'&&<small>History will be available after initialization.</small>}</span></label>)}
      {chosen.filter(identity=>!runs.some(run=>run.id===identity)).map(identity=><label className="check" key={identity}><input data-testid="comparison-choice" data-run-id={identity} type="checkbox" checked onChange={()=>change(identity,false)}/><span>Unavailable run <code>{identity}</code><small>Remove this selection or wait for it to become available.</small></span></label>)}
    </div></fieldset>
    <div className={`statistics-status ${read.phase==='failed'?'statistics-error':''}`} data-testid="comparison-status" role={read.phase==='failed'?'alert':'status'}>
      {chosen.length<2?<span>Choose at least two runs to compare. {runs.length<2?'Create another experiment with a different seed, then return here.':'For example, keep this run selected and choose a second run with a different seed.'}</span>
        :unavailable.length?<span>{unavailable.map(item=>`${label(item.run_id)}: ${item.message}`).join(' ')} The comparison will load when all selected histories are readable.</span>
        :read.phase==='failed'?<><span>Could not refresh Comparison. {read.error}{data&&' Showing the last verified complete comparison with its original sources below.'}</span><button data-testid="comparison-retry" onClick={onRetry}>Retry Comparison</button></>
        :busy||read.phase==='idle'?<span>{data?'Refreshing Comparison. The previous verified complete comparison remains below.':'Loading Comparison.'} Reading {requestedNames||'the selected histories'}.</span>
        :data?.status==='no_overlap'?<span>These histories have no common interval. The latest start is {data.common_interval.start} s, after the earliest endpoint at {data.common_interval.end} s. Choose overlapping histories or let the earlier run advance.</span>
        :<span>{stale?'New committed data is available; this complete comparison shows its previous verified sources.':'The displayed comparison is verified against every selected source.'}</span>}
    </div>
    <button className="comparison-refresh" data-testid="comparison-refresh" onClick={onRetry} disabled={chosen.length<2||Boolean(unavailable.length)||busy}>Refresh Comparison</button>
    {data&&<>
      <p className={`comparison-source ${displayedStale?'statistics-stale':''}`} data-testid="comparison-source">{displayedStale?'Previous verified comparison':'Verified comparison'} · common interval {data.common_interval.start}–{data.common_interval.end} s · {data.sample_times.length} observations per run · grid spacing {data.sample_interval} s{ready?' · exact endpoints included':''}.</p>
      <p className="comparison-help">{data.definition} Counts are raw identities, so runs with different starting populations have different totals. At most 2,000 shared observations per run are returned; grid spacing increases for longer intervals. Markers show observations; connecting lines do not add observations between them.</p>
      <div className="table-scroll"><table data-testid="comparison-sources"><caption>Captured frontier caps and actual source cursors</caption><thead><tr><th>Run / seed</th><th>History starts (s)</th><th>Captured frontier time / revision</th><th>Source at common endpoint</th></tr></thead><tbody>{data.sources.map(source=>{
        const run=data.runs.find(item=>item.run_id===source.run_id),origin=data.origins.find(item=>item.run_id===source.run_id);
        return <tr key={source.run_id} data-run-id={source.run_id}><th scope="row"><span className="comparison-swatch" style={{background:colors.current[source.run_id]}}/>{read.metadata?.[source.run_id]?.scenario}<small>Seed {read.metadata?.[source.run_id]?.seed}</small><code>{source.run_id}</code></th><td>{origin?.time}</td><td>{source.time} s · r{source.revision}</td><td>{run?`${run.cursor.time} s · r${run.cursor.revision}`:'No shared observation'}</td></tr>;
      })}</tbody></table></div>
    </>}
    <label>Population measure<select data-testid="comparison-metric" value={metric} onChange={event=>onMetric(event.target.value)}>{Object.entries(comparisonMeasures).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
    <ComparisonChart data={data} metadata={read.metadata} sourceKey={read.source_key} context={context} metric={metric} visible={visible} colors={colors.current} onState={onChartState}/>
    {ready&&<>
      <div className="table-scroll"><table data-testid="comparison-samples"><caption>All verified observations · {comparisonMeasures[metric]} selected in the chart</caption><thead><tr><th>Run / seed</th><th>Time (s)</th><th>Source revision</th><th>Healthy</th><th>Infected</th><th>Zombies</th><th>Dead</th><th>Total</th></tr></thead><tbody>{rows.map(({run,sample})=><tr key={`${run.run_id}:${sample.time}`} data-run-id={run.run_id} data-time={sample.time} data-revision={sample.revision}><th scope="row">{label(run.run_id)}<small>Seed {read.metadata?.[run.run_id]?.seed}</small></th><td>{sample.time}</td><td>{sample.revision}</td>{['healthy','infected','zombies','dead','total'].map(name=><td key={name}>{sample[name]}</td>)}</tr>)}</tbody></table></div>
      <button data-testid="comparison-export" onClick={()=>onExport('run-comparison.csv',comparisonCSV(read),'text/csv')}>Export displayed comparison CSV</button>
      <p className="comparison-help">The CSV contains exactly these verified observations and their run, seed, captured frontier, source revision, measurement version, definition and identity units. It remains tied to this displayed comparison even while newer data is loading.</p>
    </>}
  </section>;
}
