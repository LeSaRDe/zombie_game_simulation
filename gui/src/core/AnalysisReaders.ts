import {QueryReader} from './QueryReader';
import {ExactCursor} from './contracts';
import type {MetricCursor,MetricData} from '../useStatisticsReader';
import type {CohortData} from '../useCohortReader';
import type {EventData,EventRequest} from '../useEventsReader';
import type {ComparisonData,ComparisonSource} from '../useComparisonReader';
type Obj=Record<string,any>;
const sameCursor=(a?:MetricCursor,b?:MetricCursor)=>Boolean(a&&b&&new ExactCursor(a).equals(b));
const plainMap=(value:any)=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const map=plainMap;
const count=(value:any)=>Number.isInteger(value)&&value>=0;
const integer=(value:any)=>/^\d+$/.test(String(value));
function timeParts(value:string):[bigint,bigint] {
  const fraction=/^(-?\d+)\/(\d+)$/.exec(value);
  if(fraction&&BigInt(fraction[2])!==0n)return [BigInt(fraction[1]),BigInt(fraction[2])];
  const decimal=/^([+-]?)(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(value);
  if(!decimal)throw Error('Invalid metric time.');
  const exponent=Number(decimal[4]||0)-(decimal[3]||'').length;
  if(!Number.isSafeInteger(exponent)||Math.abs(exponent)>10000)throw Error('Invalid metric time.');
  const numerator=BigInt((decimal[1]==='-'?'-':'')+decimal[2]+(decimal[3]||''));
  return exponent>=0?[numerator*10n**BigInt(exponent),1n]:[numerator,10n**BigInt(-exponent)];
}
export function sameTime(left:string,right:string):boolean {
  if(left===right)return true;
  try{const [a,b]=timeParts(left),[c,d]=timeParts(right);return a*d===c*b;}catch{return false;}
}
function compareTime(left:string,right:string):bigint {
  const [a,b]=timeParts(left),[c,d]=timeParts(right);return a*d-c*b;
}
export function sameMetricCursor(left?:MetricCursor,right?:MetricCursor):boolean {
  return Boolean(left&&right&&left.run_id===right.run_id&&left.revision===right.revision&&sameTime(left.time,right.time));
}


export class StatisticsReader extends QueryReader {
  validate(data:MetricData, requested:MetricCursor):MetricCursor {
        const cursor={run_id:requested.run_id,time:String(data.cursor?.time??data.time),revision:String(data.cursor?.revision??data.revision)};
        if(!sameCursor(cursor,requested))throw Error('Statistics returned a different source time or revision. Retry to load the selected cursor.');
        if(!Array.isArray(data.samples)||!plainMap(data.event_counts))throw Error('The service returned incomplete statistics.');
        let previousTime='0';
        for(const sample of data.samples){
          if(!plainMap(sample)||sample.time===undefined||!/^\d+$/.test(String(sample.revision))||!Number.isFinite(sample.seconds)||sample.seconds<0
            ||['healthy','infected','zombies','dead'].some(key=>!Number.isInteger(sample[key])||sample[key]<0)
            ||sample.healthy+sample.infected+sample.zombies+sample.dead!==sample.total
            ||compareTime(String(sample.time),previousTime)<0||compareTime(String(sample.time),cursor.time)>0
            ||BigInt(sample.revision)>BigInt(cursor.revision)
            ||!plainMap(sample.resources?.available_and_reserved)||!plainMap(sample.resources?.reserved_subset))throw Error('The service returned an invalid population or resource sample.');
          previousTime=String(sample.time);
        }
        const endpoint=data.samples.at(-1);
        if(endpoint&&!sameCursor({run_id:requested.run_id,time:String(endpoint.time),revision:String(endpoint.revision)},cursor))throw Error('Statistics are missing the selected frontier sample. Retry to load the complete cursor.');
    return cursor;
  }
}
export class CohortReader extends QueryReader {
  validate(data:CohortData, requested:MetricCursor):MetricCursor {
        const cursor={run_id:data.run_id,time:String(data.cursor?.time),revision:String(data.cursor?.revision)};
        if(!sameCursor(cursor,requested))throw Error('Cohorts returned a different source time, revision or run. Retry to load the selected cursor.');
        if(!Array.isArray(data.cohorts))throw Error('The service returned an incomplete cohort collection.');
        const ids=new Set<string>();
        for(const cohort of data.cohorts){
          const definition=cohort?.definition;
          if(!map(cohort)||!map(definition)||typeof definition.id!=='string'||ids.has(definition.id)
            ||!['fixed','dynamic'].includes(definition.mode)||(definition.name!==undefined&&typeof definition.name!=='string')
            ||definition.reference_time===undefined||!/^\d+$/.test(String(definition.reference_revision))
            ||(definition.predicate!==undefined&&!map(definition.predicate))||!Array.isArray(cohort.members)||cohort.members.some((identity:any)=>typeof identity!=='string')
            ||new Set(cohort.members).size!==cohort.members.length||cohort.denominator!==cohort.members.length
            ||!count(cohort.present)||cohort.present>cohort.denominator||!map(cohort.populations)
            ||['healthy','infected','zombies','dead'].some(key=>!count(cohort.populations[key]))
            ||['healthy','infected','zombies','dead'].reduce((sum,key)=>sum+cohort.populations[key],0)!==cohort.present
            ||cohort.populations.total!==cohort.present)throw Error('The service returned an invalid cohort definition or membership summary.');
          for(const metric of ['life','stamina']){
            const denominator=cohort[`mean_${metric}_denominator`],mean=cohort[`mean_${metric}`];
            if(!count(denominator)||denominator!==cohort.present||(denominator===0?mean!==null:!Number.isFinite(mean)))throw Error('The service returned an invalid cohort average or denominator.');
          }
          ids.add(definition.id);
        }
    return cursor;
  }
}
export class EventsReader extends QueryReader {
  validate(data:EventData, request:EventRequest):MetricCursor {
        const cursor=request.cursor,selectedAgent=request.agent;
        const source={run_id:data.run_id,time:String(data.cursor?.time),revision:String(data.cursor?.revision)};
        if(!sameCursor(source,cursor)||(data.agent??null)!==selectedAgent)throw Error('Events returned a different source cursor or identity filter. Retry to load the requested page.');
        if(!Array.isArray(data.records)||!map(data.occurrences)||!map(data.page)
          ||data.page.limit!==request.limit||data.page.loaded_count!==data.records.length||data.records.length>request.limit
          ||typeof data.page.has_older!=='boolean'||typeof data.page.has_newer!=='boolean')throw Error('The service returned an incomplete event page.');
        let previous=-1n;const references=new Set<string>();
        for(const record of data.records){
          if(!map(record)||!integer(record.ledger_sequence)||!integer(record.ledger_revision)
            ||!integer(record.revision_before)||!integer(record.revision_after))throw Error('The service returned an invalid event cursor.');
          const sequence=BigInt(record.ledger_sequence),revision=BigInt(record.ledger_revision);
          if(sequence<=0n||sequence<=previous||revision>BigInt(source.revision)
            ||BigInt(record.revision_after)!==revision||BigInt(record.revision_before)!==(revision>0n?revision-1n:0n)
            ||(request.before_sequence&&sequence>=BigInt(request.before_sequence))
            ||(request.after_sequence&&sequence<=BigInt(request.after_sequence)))throw Error('The service returned events outside the requested causal page or order.');
          previous=sequence;
          for(const value of [record.occurrence,record.action_id])if(value!=null)references.add(String(value));
        }
        if(data.page.first_sequence!==(data.records.length?String(data.records[0].ledger_sequence):null)
          ||data.page.last_sequence!==(data.records.length?String(data.records.at(-1)!.ledger_sequence):null)
          ||Object.keys(data.occurrences).some(identity=>!references.has(identity)))throw Error('The service returned inconsistent event page boundaries or unrelated occurrence details.');
    return source;
  }
}
export function comparisonTime(value:string):[bigint,bigint] {
  if(typeof value!=='string')throw Error('Comparison times must be exact strings.');
  const fraction=/^(-?\d+)\/(\d+)$/.exec(value);
  if(fraction&&BigInt(fraction[2])>0n)return [BigInt(fraction[1]),BigInt(fraction[2])];
  const decimal=/^([+-]?)(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(value);
  if(!decimal)throw Error('Invalid comparison time.');
  const exponent=Number(decimal[4]||0)-(decimal[3]||'').length;
  if(!Number.isSafeInteger(exponent)||Math.abs(exponent)>10000)throw Error('Invalid comparison time.');
  const numerator=BigInt((decimal[1]==='-'?'-':'')+decimal[2]+(decimal[3]||''));
  return exponent>=0?[numerator*10n**BigInt(exponent),1n]:[numerator,10n**BigInt(-exponent)];
}
export function compareComparisonTime(left:string,right:string):bigint {
  const [a,b]=comparisonTime(left),[c,d]=comparisonTime(right);return a*d-c*b;
}
export function comparisonSeconds(value:string):number {
  let [a,b]=comparisonTime(value);let x=a<0n?-a:a,y=b;
  while(y){const remainder=x%y;x=y;y=remainder;}if(x){a/=x;b/=x;}
  return Number(a)/Number(b);
}
const exactEqual=(left:string,right:string)=>compareComparisonTime(left,right)===0n;
const comparisonInteger=(value:any)=>typeof value==='string'&&/^\d+$/.test(value);
const object=(value:any)=>value!==null&&typeof value==='object'&&!Array.isArray(value);
export const comparisonSourceKey=(sources:ComparisonSource[])=>JSON.stringify(sources);
const sameSource=(a:ComparisonSource,b:ComparisonSource)=>a?.run_id===b.run_id&&a.revision===b.revision&&exactEqual(a.time,b.time);

export class ComparisonReader extends QueryReader {
  validate(data:Obj,requested:ComparisonSource[]):ComparisonData {
  if(!object(data)||!Array.isArray(data.sources)||data.sources.length!==requested.length
    ||data.sources.some((source:ComparisonSource,index:number)=>!sameSource(source,requested[index])))throw Error('Comparison returned a different selection or source cursor. Retry to load the requested histories.');
  if(data.status==='failed'){
    if(!Array.isArray(data.errors)||!data.errors.length||data.errors.some((error:Obj)=>!requested.some(source=>source.run_id===error.run_id)||typeof error.message!=='string'))throw Error('The service returned an incomplete comparison failure.');
    throw Object.assign(Error(data.errors.map((error:Obj)=>`Run ${error.run_id}: ${error.message}`).join(' ')),{failures:data.errors});
  }
  if(!['ready','no_overlap'].includes(data.status)||!object(data.common_interval)||!Array.isArray(data.origins)
    ||data.origins.length!==requested.length||!Array.isArray(data.sample_times)||!Array.isArray(data.runs)
    ||data.sample_limit!==2000||typeof data.definition!=='string'||typeof data.version!=='string'
    ||compareComparisonTime(data.sample_interval,'1')<0n)throw Error('The service returned an incomplete comparison.');
  let start='0',end=requested[0].time;
  for(let index=0;index<requested.length;index++){
    const origin=data.origins[index],source=requested[index];
    if(!origin||origin.run_id!==source.run_id||compareComparisonTime(origin.time,'0')<0n||compareComparisonTime(origin.time,source.time)>0n)throw Error('Comparison returned an invalid history origin.');
    if(compareComparisonTime(origin.time,start)>0n)start=origin.time;
    if(compareComparisonTime(source.time,end)<0n)end=source.time;
  }
  if(!exactEqual(data.common_interval.start,start)||!exactEqual(data.common_interval.end,end))throw Error('Comparison returned a different common interval.');
  if(data.status==='no_overlap'){
    if(compareComparisonTime(start,end)<=0n||data.sample_times.length||data.runs.length)throw Error('The service incorrectly reported no common interval.');
    return data as ComparisonData;
  }
  if(compareComparisonTime(start,end)>0n||data.sample_times.length<1||data.sample_times.length>2000
    ||!exactEqual(data.sample_times[0],start)||!exactEqual(data.sample_times.at(-1),end)||data.runs.length!==requested.length)throw Error('Comparison is missing its shared endpoints or selected runs.');
  const [spacingN,spacingD]=comparisonTime(data.sample_interval);
  for(let index=0;index<data.sample_times.length;index++){
    const time=data.sample_times[index];
    if(compareComparisonTime(time,start)<0n||compareComparisonTime(time,end)>0n)throw Error('Comparison sample lies outside the shared interval.');
    if(index){
      const [a,b]=comparisonTime(time),[c,d]=comparisonTime(data.sample_times[index-1]);
      const delta=a*d-c*b,grid=spacingN*b*d;
      if(delta<=0n||delta*spacingD>grid||(index<data.sample_times.length-1&&delta*spacingD!==grid))throw Error('Comparison sample times are not a common ordered grid.');
    }
  }
  for(let index=0;index<requested.length;index++){
    const run=data.runs[index],source=requested[index];
    if(!object(run)||run.run_id!==source.run_id||!sameSource({run_id:run.run_id,...run.requested_cursor},source)
      ||!exactEqual(run.origin,data.origins[index].time)||!object(run.cursor)||!comparisonInteger(run.cursor.revision)
      ||!exactEqual(run.cursor.time,end)||BigInt(run.cursor.revision)>BigInt(source.revision)
      ||!Array.isArray(run.samples)||run.samples.length!==data.sample_times.length)throw Error('Comparison returned mismatched run sources.');
    let previousRevision=-1n;
    for(let point=0;point<run.samples.length;point++){
      const sample=run.samples[point],time=data.sample_times[point];
      if(!object(sample)||!exactEqual(sample.time,time)||!comparisonInteger(sample.revision)||!Number.isFinite(sample.seconds)
        ||Math.abs(sample.seconds-comparisonSeconds(time))>Number.EPSILON*Math.max(1,Math.abs(sample.seconds))*4
        ||['healthy','infected','zombies','dead','total'].some(name=>!Number.isSafeInteger(sample[name])||sample[name]<0)
        ||sample.healthy+sample.infected+sample.zombies+sample.dead!==sample.total
        ||BigInt(sample.revision)<previousRevision||BigInt(sample.revision)>BigInt(run.cursor.revision))throw Error(`Run ${source.run_id} returned an invalid population sample.`);
      previousRevision=BigInt(sample.revision);
    }
    if(run.samples.at(-1).revision!==run.cursor.revision)throw Error('Comparison is missing a run endpoint revision.');
  }
  return data as ComparisonData;
}

}
