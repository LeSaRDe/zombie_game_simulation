import PopulationChart from './PopulationChart';
import {TimeValue} from './TimeValue';
import {timeLabel} from './timeFormat';
import {MetricCursor,MetricRead,sameCursor} from './useStatisticsReader';

export default function StatisticsPanel({read,selected,mode,visible,waitingForView,onRetry,onSeek,colors,onChartState}:{
  read:MetricRead;selected:MetricCursor;mode:'live'|'replay';visible:boolean;waitingForView:boolean;
  onRetry:()=>void;onSeek:(time:string,revision?:string)=>void;colors:Record<string,string>;
  onChartState:(state:Record<string,any>)=>void;
}) {
  const samples=read.data?.samples||[];
  const stale=waitingForView||!sameCursor(read.cursor,selected);
  const lastResources=samples.at(-1)?.resources;
  const map=(value:any)=>value!==null&&typeof value==='object'&&!Array.isArray(value);
  const resources=lastResources&&map(lastResources.available_and_reserved)&&map(lastResources.reserved_subset)?lastResources:undefined;
  const source=read.cursor?`${timeLabel(read.cursor.time)} s · revision ${read.cursor.revision}`:'not loaded';
  return <div className="statistics" aria-busy={read.phase==='loading'||read.phase==='refreshing'}>
    <h2>Population through time</h2>
    <span className={`tag ${stale?'statistics-stale':''}`} data-testid="statistics-cursor">{read.cursor
      ? stale?`Statistics through ${timeLabel(read.cursor.time)} s`:`Metric cursor r${read.cursor.revision} · synchronized`
      :'Statistics not loaded yet'}</span>
    {read.cursor&&<span className="statistics-source" data-testid="statistics-source" data-exact-time={read.cursor.time} data-revision={read.cursor.revision}>Source <TimeValue value={read.cursor.time}/> · revision {read.cursor.revision}{stale?' · selected view differs':''}</span>}
    <p>Counts of persistent identities. Conversion changes type; remains never add to the population. Click a chart or table sample to inspect recorded history at its exact time and revision. Simulation execution continues in its current state.</p>
    <div className={`statistics-status ${read.phase==='failed'?'statistics-error':''}`} data-testid="statistics-status" role={read.phase==='failed'?'alert':'status'}>
      {read.phase==='failed'?<><span>Could not refresh Statistics. {read.error}{read.data&&` Showing the last verified data through ${source}.`}</span><button data-testid="statistics-retry" onClick={onRetry}>Retry Statistics</button></>
        :waitingForView?<span>Waiting for the selected history view. {read.data&&`Last verified statistics: ${source}.`}</span>
        :read.phase==='loading'||read.phase==='idle'?<span>Loading Statistics for the selected time and revision…</span>
        :read.phase==='refreshing'||stale?<span>Refreshing Statistics. {read.data&&`Showing the last verified data through ${source}.`}</span>
        :!samples.length?<><span>No population samples were returned for this cursor.</span><button data-testid="statistics-retry" onClick={onRetry}>Retry Statistics</button></>
        :<span>Population samples and recorded outcomes share the source cursor shown above.</span>}
    </div>
    <PopulationChart samples={samples} cursor={read.cursor} selected={selected} mode={mode} visible={visible} colors={colors} onSeek={onSeek} onState={onChartState}/>
    <div className="two-columns"><section><h3>Resources at the metric cursor</h3><p data-testid="statistics-resource-cursor">Source: {source}</p>
      {resources?<table><thead><tr><th>Resource</th><th>Stock + carried</th><th>Reserved subset</th></tr></thead><tbody>{Object.entries(resources.available_and_reserved).map(([resource,quantity])=><tr key={resource}><td>{resource}</td><td>{String(quantity)}</td><td>{resources.reserved_subset[resource]||0}</td></tr>)}</tbody></table>:<p>No verified resource sample is available yet.</p>}
    </section><section><h3>Recorded outcomes</h3><p>Exact event totals through {source}. These totals are distinct from the sampled population curves.</p>
      {read.data&&Object.entries(read.data.event_counts).map(([kind,count])=><div className="measure" key={kind}><span>{kind.replaceAll('_',' ')}</span><strong>{count}</strong></div>)}
    </section></div>
    <details><summary data-testid="population-table-toggle">Accessible population table</summary><div className="table-scroll"><table tabIndex={0} data-testid="population-table"><thead><tr><th>Time (s)</th><th>Healthy humans</th><th>Infected humans</th><th>Zombies</th><th>Dead identities</th></tr></thead><tbody>{samples.map((sample,index)=><tr key={`${sample.time}:${sample.revision}:${index}`}><td><button className="link" data-exact-time={String(sample.time)} data-revision={String(sample.revision)} aria-label={`Inspect time ${timeLabel(sample.time).replace("≈","approximately ")} seconds, revision ${sample.revision}`} aria-description="Inspect recorded history. Simulation execution is unchanged." title={`Inspect recorded time ${sample.time} s, revision ${sample.revision}`} onClick={()=>onSeek(String(sample.time),String(sample.revision))}>{timeLabel(sample.time)}</button><small className="population-sample-revision" data-testid="population-sample-revision">revision {sample.revision}</small></td><td>{sample.healthy}</td><td>{sample.infected}</td><td>{sample.zombies}</td><td>{sample.dead}</td></tr>)}</tbody></table></div></details>
  </div>;
}
