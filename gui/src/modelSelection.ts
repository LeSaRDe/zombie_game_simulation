type Obj = Record<string, any>;
export type ModelKind = 'Human' | 'Zombie';
export type ModelField = 'human_model' | 'zombie_model';
export type ModelChoice = {
  model_id:string; label:string; version:string; aliases:string[];
  applicable_types:ModelKind[]; description:string;
};
export type ModelCatalog = {
  schema_version:'zombie-sim/model-catalog-v1';
  defaults:Record<ModelKind,string>; choices:ModelChoice[]; registered_names:string[];
};
export const modelKinds:ModelKind[] = ['Human','Zombie'];
export const modelField = (kind:ModelKind):ModelField => kind==='Human'?'human_model':'zombie_model';
const object = (value:unknown):value is Obj => value!==null&&typeof value==='object'&&!Array.isArray(value);
const own = (value:Obj,key:string) => Object.prototype.hasOwnProperty.call(value,key);
const text = (value:unknown):value is string => typeof value==='string'&&Boolean(value.trim());
const uniqueText = (value:unknown):value is string[] => Array.isArray(value)&&value.every(text)&&new Set(value).size===value.length;
const mergeObjects = (base:Obj,update:Obj):Obj => Object.fromEntries(Object.entries({...base,...update}).map(([key,value])=>[
  key,object(base[key])&&object(update[key])?mergeObjects(base[key],update[key]):value,
]));

/** A metadata read never loads a policy. Reject incomplete transport data visibly. */
export function modelCatalog(value:unknown):ModelCatalog {
  const fail=():never=>{throw Error('The service returned incomplete or unsupported decision-model metadata. Retry loading configuration.');};
  if(!object(value)||value.schema_version!=='zombie-sim/model-catalog-v1'||!object(value.defaults)
      ||!modelKinds.every(kind=>text(value.defaults[kind]))||!uniqueText(value.registered_names)
      ||!Array.isArray(value.choices))return fail();
  const identities=new Set<string>(),aliases=new Set<string>();
  for(const choice of value.choices){
    if(!object(choice)||!text(choice.model_id)||!text(choice.label)||!text(choice.version)
      ||!uniqueText(choice.aliases)||!choice.aliases.length||!uniqueText(choice.applicable_types)
      ||!choice.applicable_types.length||!choice.applicable_types.every(kind=>modelKinds.includes(kind as ModelKind))
      ||typeof choice.description!=='string'||identities.has(choice.model_id))return fail();
    identities.add(choice.model_id);
    for(const alias of choice.aliases){if(aliases.has(alias)||!value.registered_names.includes(alias))return fail();aliases.add(alias);}
  }
  return value as ModelCatalog;
}

export function modelRequestId(choice:ModelChoice,kind:ModelKind,catalog:ModelCatalog):string {
  const preferred=catalog.defaults[kind];
  return choice.aliases.includes(preferred)?preferred:choice.aliases.includes(choice.model_id)?choice.model_id:choice.aliases[0];
}

/** Only display effective settings here; never materialize defaults in a draft. */
export function readModelSetting(config:Obj,kind:ModelKind,catalog:ModelCatalog){
  const field=modelField(kind);
  if(config.semantic!==undefined&&config.semantic!==null&&!object(config.semantic))throw Error('semantic must be an object. Correct it in Advanced JSON before editing decision models.');
  const semantic=object(config.semantic)?config.semantic:{};
  const overridden=own(semantic,field);
  const supplied=overridden?semantic:config;
  const omitted=!own(supplied,field);
  const request=omitted?catalog.defaults[kind]:supplied[field];
  const choice=typeof request==='string'?catalog.choices.find(item=>item.aliases.includes(request)):undefined;
  const compatible=choice?.applicable_types.includes(kind)??false;
  const explicitAgents=own(config,'agents')||own(semantic,'agents');
  const agents=own(semantic,'agents')?(object(config.agents)&&object(semantic.agents)?mergeObjects(config.agents,semantic.agents):semantic.agents):config.agents;
  let assignments:string[]=[];
  if(explicitAgents){
    const records=Array.isArray(agents)?agents:object(agents)?Object.values(agents):[];
    assignments=[...new Set<string>(records.filter(agent=>object(agent)&&(agent.type??'Human')===kind).map(agent=>{
      const assignment=agent.model_assignment;
      if(!assignment)return `${catalog.defaults[kind]} (per-agent default)`;
      if(!object(assignment))return JSON.stringify(assignment);
      return `${String(assignment.model_id??'Missing model ID')}${assignment.version!==undefined?` · requested version ${String(assignment.version)}`:''}`;
    }))];
  }
  const blocked=explicitAgents?'Initial model assignments come from individual agent records. Edit agents[].model_assignment in Advanced JSON; these population defaults do not replace those assignments.'
    :overridden?`This setting comes from semantic.${field}. Edit that value in Advanced JSON.`:undefined;
  return {field,request,omitted,choice,compatible,explicitAgents,assignments,blocked,overridden};
}
