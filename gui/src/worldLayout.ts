/** Explicit form-driven world resizing; parsing/loading a configuration never resizes it. */
type Obj = Record<string, any>;
type Dimensions = {length:number; width:number};
type SpatialEntry = {key:string; coordinates:number[]};
type Projection = {barriers:SpatialEntry[]; shelters:SpatialEntry[]; stockpiles:SpatialEntry[]; agents:SpatialEntry[]};
type Reference = {world:Dimensions; layout:Projection};
export type WorldResizeSummary = {
  text:string; customizedBaseline:boolean; from:Dimensions; to:Dimensions;
  counts:{barriers:number; shelters:number; stockpiles:number; agents:number};
};

const own = (value:Obj, key:string) => Object.prototype.hasOwnProperty.call(value,key);
const object = (value:any):value is Obj => value !== null && typeof value === 'object' && !Array.isArray(value);
const copy = <T,>(value:T):T => structuredClone(value);
const spatialKeys = ['world','barriers','shelters','stockpiles','agents'];
const collections = ['barriers','shelters','stockpiles','agents'] as const;

function fail(path:string,message:string):never {
  const text=`${path}: ${message}`;
  throw Object.assign(new Error(text),{code:'INVALID_GEOMETRY',issues:[{path,code:'INVALID_GEOMETRY',message:text}]});
}

function merge(base:Obj,update:Obj):Obj {
  const result=copy(base);
  for(const [key,value] of Object.entries(update)) {
    const next=object(value)&&object(result[key])?merge(result[key],value):copy(value);
    Object.defineProperty(result,key,{value:next,enumerable:true,writable:true,configurable:true});
  }
  return result;
}

function effective(config:Obj,presets:Obj):Obj {
  if(!object(config))fail('configuration','expected a configuration object.');
  if(config.semantic!==undefined&&!object(config.semantic))fail('semantic','expected an object before editing world dimensions.');
  const supplied=config.semantic===undefined?copy(config):merge(config,config.semantic);
  const baseline=supplied.preset==='baseline'||supplied.preset==='baseline_v0.1'||supplied.scenario==='baseline_v0.1';
  const defaults=presets[baseline?'baseline':'small'];
  if(!object(defaults))fail('world','configuration defaults are not available yet.');
  return merge(defaults,supplied);
}

function finite(value:any,path:string):number {
  if(typeof value!=='number'||!Number.isFinite(value))fail(path,'expected a finite number before resizing.');
  return value;
}

function dimensions(value:any,path='world'):Dimensions {
  if(!object(value))fail(path,'expected length and width in an object.');
  const length=finite(value.length,`${path}.length`),width=finite(value.width,`${path}.width`);
  if(length<=0||width<=0)fail(path,'length and width must be greater than zero before resizing.');
  return {length,width};
}

/** Display defaults and semantic overrides without changing the authored draft. */
export function effectiveWorld(config:Obj,presets:Obj):Obj {
  const current=effective(config,presets);
  if(!object(current.world))fail('world','expected an object.');
  return copy(current.world);
}

function entries(value:any,path:string):Array<[string,Obj]> {
  if(value===undefined&&path==='agents')return [];
  if(!Array.isArray(value)&&!(path==='agents'&&object(value)))fail(path,'expected an array of entities (agent records may also be an object).');
  const list:Array<Obj>=Array.isArray(value)?value:Object.values(value);
  const seen=new Set<string>();
  return list.map((item,index)=>{
    if(!object(item))fail(`${path}[${index}]`,'expected an entity object.');
    const key=own(item,'id')?`id:${String(item.id)}`:`index:${index}`;
    if(seen.has(key))fail(`${path}[${index}].id`,'duplicate identity; correct it before resizing.');
    seen.add(key);return [key,item];
  });
}

function rectangle(value:any,path:string):number[] {
  if(object(value)&&own(value,'footprint'))return rectangle(value.footprint,`${path}.footprint`);
  const raw=Array.isArray(value)?value:object(value)?['xmin','ymin','xmax','ymax'].map(key=>value[key]):[];
  if(raw.length!==4)fail(path,'expected [xmin, ymin, xmax, ymax] or a rectangle object.');
  // The backend rectangle parser also accepts finite decimal strings.
  const coordinates=raw.map((v,i)=>finite(typeof v==='string'&&v.trim()?Number(v):v,`${path}[${i}]`));
  if(coordinates[0]>=coordinates[2]||coordinates[1]>=coordinates[3])fail(path,'rectangle must have positive area before resizing.');
  return coordinates;
}

function projection(config:Obj):Projection {
  const output={} as Projection;
  for(const name of collections)output[name]=entries(config[name],name).map(([key,item])=>{
    const path=`${name}.${item.id??key}`;
    if((name==='stockpiles'||name==='agents')&&['position','footprint','xmin','ymin','xmax','ymax'].some(field=>own(item,field)))
      fail(path,'alternate position or footprint overrides cannot be resized alongside x/y. Use one ordinary x/y coordinate pair for this initial point before resizing.');
    const coordinates=name==='barriers'?rectangle(item.footprint,`${path}.footprint`)
      :name==='shelters'?rectangle(item.interior,`${path}.interior`)
      :[finite(item.x??(name==='agents'?0:undefined),`${path}.x`),finite(item.y??(name==='agents'?0:undefined),`${path}.y`)];
    return {key,coordinates};
  }).sort((a,b)=>a.key<b.key?-1:a.key>b.key?1:0);
  return output;
}

function rational(value:number):{n:bigint;d:bigint} {
  const [mantissa,power='0']=String(value).toLowerCase().split('e');
  const decimals=(mantissa.split('.')[1]||'').length;
  const exponent=Number(power)-decimals,n=BigInt(mantissa.replace('.',''));
  return exponent>=0?{n:n*10n**BigInt(exponent),d:1n}:{n,d:10n**BigInt(-exponent)};
}

/** Decimal-rational scaling avoids overflow and repeated binary-rounding drift. */
function scale(value:number,oldSize:number,newSize:number,path:string):number {
  if(oldSize===newSize||value===0)return value;
  const v=rational(value),a=rational(oldSize),b=rational(newSize);
  let n=v.n*b.n*a.d;const d=v.d*b.d*a.n;
  const negative=n<0n;if(negative)n=-n;
  let exponent=n.toString().length-d.toString().length;
  if(exponent>=0?n<d*10n**BigInt(exponent):n*10n**BigInt(-exponent)<d)exponent--;
  const places=24-exponent;
  const significant=(places>=0?n*10n**BigInt(places)/d:n/(d*10n**BigInt(-places))).toString();
  const result=Number(`${negative?'-':''}${significant[0]}.${significant.slice(1)}e${exponent}`);
  if(!Number.isFinite(result)||result===0)fail(path,'these dimensions make a coordinate too large or too small to represent; choose less extreme dimensions.');
  return result;
}

function transform(layout:Projection,from:Dimensions,to:Dimensions):Projection {
  const output={} as Projection;
  for(const name of collections)output[name]=layout[name].map(entry=>({key:entry.key,coordinates:entry.coordinates.map((v,index)=>scale(v,index%2?from.width:from.length,index%2?to.width:to.length,`${name}.${entry.key}`))}));
  for(const name of ['barriers','shelters'] as const)for(const entry of output[name]){
    const [x0,y0,x1,y1]=entry.coordinates;
    if(x0>=x1||y0>=y1)fail(`${name}.${entry.key}`,'these dimensions collapse a rectangle; choose less extreme dimensions.');
  }
  return output;
}

function same(a:unknown,b:unknown):boolean {return JSON.stringify(a)===JSON.stringify(b);}

function readReference(value:any,current:Projection,currentWorld:Dimensions):Reference|undefined {
  try {
    if(!object(value)||value.schema_version!==1||value.method!=='axis_scale'||!object(value.reference))return;
    const world=dimensions(value.reference.world,'gui.world_resize.reference.world');
    const layout=value.reference.layout;
    if(!object(layout))return;
    for(const name of collections){
      if(!Array.isArray(layout[name])||layout[name].length!==current[name].length)return;
      for(const entry of layout[name])if(!object(entry)||typeof entry.key!=='string'||!Array.isArray(entry.coordinates)
          ||entry.coordinates.length!==(name==='barriers'||name==='shelters'?4:2)
          ||entry.coordinates.some((v:any)=>typeof v!=='number'||!Number.isFinite(v)))return;
    }
    const reference={world,layout:copy(layout) as Projection};
    return same(transform(reference.layout,world,currentWorld),current)?reference:undefined;
  }catch{return;}
}

function writeRectangle(value:any,coordinates:number[]):any {
  if(Array.isArray(value))return [...coordinates];
  const result=copy(value);
  if(own(result,'footprint'))result.footprint=writeRectangle(result.footprint,coordinates);
  else ['xmin','ymin','xmax','ymax'].forEach((key,index)=>result[key]=coordinates[index]);
  return result;
}

function hasContent(value:any):boolean {
  return value!==undefined&&value!==null&&value!==false&&(typeof value!=='object'||Object.keys(value).length>0);
}

function ensureOrdinaryLayout(config:Obj):void {
  if(config.state_import||['remains','signals','reservations','runtime','model_memory','model_state','pending_actions'].some(key=>hasContent(config[key]))) {
    fail('world','automatic resizing is not supported for historical/runtime state imports. Their recorded positions and private spatial state are preserved. Start an ordinary new scenario layout to resize the world.');
  }
  for(const [,agent] of entries(config.agents,'agents')){
    if(['memory','model_memory','model_state','private_state','active_action','action_state','effects','cooldowns'].some(key=>hasContent(agent[key]))||agent.life===0
        ||(object(agent.model_assignment)&&['memory','state','model_state'].some(key=>hasContent(agent.model_assignment[key])))){
      fail(`agents.${agent.id??'record'}`,'recorded runtime or model-private state cannot be partially resized. Use ordinary initial agent positions in a new scenario layout.');
    }
  }
}

/** Apply all dependent coordinates in one transaction, preserving independent fields. */
export function applyWorldResize(base:Obj,next:Obj,edited:Record<string,number>,presets:Obj):void {
  if(!own(edited,'world.length')&&!own(edited,'world.width'))return;
  const current=effective(base,presets),from=dimensions(current.world);
  const to=dimensions({length:own(edited,'world.length')?edited['world.length']:from.length,width:own(edited,'world.width')?edited['world.width']:from.width});
  if(same(from,to))return;
  ensureOrdinaryLayout(current);
  const layout=projection(current);
  const reference=readReference(current.gui?.world_resize,layout,from)||{world:from,layout};
  const adjusted=transform(reference.layout,reference.world,to),candidate=copy(next);
  const effectiveNext=effective(next,presets);
  candidate.world={...effectiveNext.world,...to};
  for(const name of collections){
    if(name==='agents'&&!own(current,'agents'))continue;
    const entityCopy=copy(current[name]);const byKey=new Map(adjusted[name].map(entry=>[entry.key,entry.coordinates]));
    for(const [key,item] of entries(entityCopy,name)){
      const coordinates=byKey.get(key)!;
      if(name==='barriers')item.footprint=writeRectangle(item.footprint,coordinates);
      else if(name==='shelters')item.interior=writeRectangle(item.interior,coordinates);
      else [item.x,item.y]=coordinates;
    }
    candidate[name]=entityCopy;
  }
  if(candidate.gui!==undefined&&!object(candidate.gui))fail('gui','expected an object; correct it before resizing.');
  if(effectiveNext.gui!==undefined&&!object(effectiveNext.gui))fail('gui','expected an object; correct it before resizing.');
  const baseline=current.preset==='baseline'||current.preset==='baseline_v0.1'||current.scenario==='baseline_v0.1';
  candidate.gui={...(effectiveNext.gui||{}),world_resize:{schema_version:1,method:'axis_scale',reference,
    from, to, customized_baseline:baseline,counts:Object.fromEntries(collections.map(name=>[name,layout[name].length]))}};
  // Spatial semantic overrides have been materialized above. Leave unrelated
  // overrides authored as they were; they retain their normal resolver priority.
  if(object(candidate.semantic)){
    for(const key of spatialKeys)delete candidate.semantic[key];
    if(object(candidate.semantic.gui))delete candidate.semantic.gui.world_resize;
  }
  // Commit only after every transformation and guard has succeeded.
  for(const key of Object.keys(next))delete next[key];
  for(const [key,value] of Object.entries(candidate))Object.defineProperty(next,key,{value,enumerable:true,writable:true,configurable:true});
}

/** A readable summary is derived only from a well-formed editor record. */
export function worldResizeSummary(config:Obj):WorldResizeSummary|undefined {
  const current=object(config.semantic)?merge(config,config.semantic):config;
  const value=current.gui?.world_resize;
  if(!object(value)||value.schema_version!==1||value.method!=='axis_scale')return;
  try {
    const from=dimensions(value.from),to=dimensions(value.to);
    const currentLayout=projection(current);
    if(!same(dimensions(current.world),to)||!readReference(value,currentLayout,to))return;
    const counts=Object.fromEntries(collections.map(name=>[name,currentLayout[name].length]));
    if(!object(value.counts)||collections.some(name=>value.counts[name]!==counts[name]))return;
    const customizedBaseline=value.customized_baseline===true;
    const text=`${customizedBaseline?'Customized baseline. ':''}Layout resized from ${from.length} × ${from.width} m to ${to.length} × ${to.width} m: ${counts.barriers} barriers, ${counts.shelters} shelters, ${counts.stockpiles} stockpiles${counts.agents?`, ${counts.agents} initial agent positions`:''}. Population, resources and physical parameters are unchanged by resizing.`;
    return {text,customizedBaseline,from,to,counts:copy(counts) as WorldResizeSummary['counts']};
  }catch{return;}
}
