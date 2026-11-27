type Obj = Record<string, any>;
export type RoleKind = 'Human' | 'Zombie';
export type Ratio = {numerator: string; denominator: string};
type Fraction = {n: bigint; d: bigint};
export const roleKinds: RoleKind[] = ['Human', 'Zombie'];
export const roleOrder: Record<RoleKind, string[]> = {
  Human: ['unassigned', 'DOCTOR', 'WARRIOR', 'SCOUT', 'ENGINEER'],
  Zombie: ['unassigned', 'TYRANT', 'RUNNER', 'SPITTER', 'SCREAMER'],
};
export const roleLabel = (role: string) => role === 'unassigned' ? 'No active role' : role[0] + role.slice(1).toLowerCase();
const populationKey = {Human:'humans', Zombie:'zombies'};
const rolesKey = {Human:'human_roles', Zombie:'zombie_roles'};
export type RoleGroup = {total:number; counts:Record<string,number>; targets:Record<string,Ratio>};
export type RoleGroups = Record<RoleKind, RoleGroup>;
const own = (value:Obj, key:string) => Object.prototype.hasOwnProperty.call(value,key);
const object = (value:any) => value !== null && typeof value === 'object' && !Array.isArray(value);
function fail(path:string,message:string,label=path):never {
  throw Object.assign(new Error(`${label}: ${message}`),{code:'INVALID_DOMAIN',issues:[{path,code:'INVALID_DOMAIN',message:`${label}: ${message}`} ]});
}
const gcd = (a:bigint,b:bigint):bigint => {while(b){const remainder=a%b;a=b;b=remainder;}return a<0n?-a:a;};
const fraction = (n:bigint,d:bigint):Fraction => {const divisor=gcd(n,d);return {n:n/divisor,d:d/divisor};};
const ratio = ({n,d}:Fraction):Ratio => ({numerator:String(n),denominator:String(d)});
const unpack = (value:Ratio):Fraction => ({n:BigInt(value.numerator),d:BigInt(value.denominator)});
const add = (a:Fraction,b:Fraction) => fraction(a.n*b.d+b.n*a.d,a.d*b.d);
const same = (a:Fraction,b:Fraction) => a.n*b.d===b.n*a.d;
function exactCount(count:bigint,kind:RoleKind):number {
  const value=Number(count);
  if(!Number.isFinite(value)||BigInt(value)!==count)fail(`population.${populationKey[kind]}`,'this allocation exceeds exact browser integer precision; use smaller population counts.');
  return value;
}
function readRatio(value:any,path:string):Ratio {
  if(!object(value)||Object.keys(value).sort().join()!=='denominator,numerator'||typeof value.numerator!=='string'||typeof value.denominator!=='string'
      ||! /^(0|[1-9]\d*)$/.test(value.numerator)||! /^[1-9]\d*$/.test(value.denominator))fail(path,'expected a nonnegative rational share.');
  const result=unpack(value);
  if(result.n>result.d)fail(path,'share must not exceed 100%.');
  if(gcd(result.n,result.d)!==1n)fail(path,'fraction must be reduced to canonical form.');
  return ratio(result);
}
export const hasExplicitAgents = (config:Obj) => own(config,'agents');
function effectiveConfiguration(config:Obj):Obj {
  if(config.semantic===undefined)return config;
  if(!object(config.semantic))fail('semantic','expected an object.');
  const merge=(base:Obj,update:Obj):Obj=>{const result={...base};for(const [key,value] of Object.entries(update))result[key]=object(value)&&object(base[key])?merge(base[key],value):value;return result;};
  return merge(config,config.semantic);
}
export function roleEditingBlock(config:Obj):string|undefined {
  if(object(config.semantic)&&(own(config.semantic,'population')||own(config.semantic,'agents')||config.semantic.gui?.role_allocation!==undefined))return 'Population or role settings come from the semantic configuration; edit those records in Advanced JSON.';
  if(hasExplicitAgents(config))return 'Population and roles come from explicit agent records; edit those records in Advanced JSON.';
}
/** Match resolver population defaults and explicit-agent authority for display only. */
export function effectivePopulation(config:Obj,presets:Obj):Obj {
  config=effectiveConfiguration(config);
  if(hasExplicitAgents(config)){
    const agents=Array.isArray(config.agents)?config.agents:object(config.agents)?Object.values(config.agents):fail('agents','expected an array or object of agent records.');
    const population:Obj={humans:0,zombies:0,infected:0,human_roles:{},zombie_roles:{}};
    for(const agent of agents){
      if(!object(agent))fail('agents','expected agent objects.');
      const kind=agent.type??'Human';if(kind!=='Human'&&kind!=='Zombie')fail('agents','each biological type must be Human or Zombie.');
      population[kind==='Human'?'humans':'zombies']++;
      if(kind==='Human'&&(agent.infected||agent.infection_episode))population.infected++;
      if(agent.role){const key=kind==='Human'?'human_roles':'zombie_roles';population[key][agent.role]=(population[key][agent.role]??0)+1;}
    }
    return population;
  }
  if(config.population!==undefined&&!object(config.population))fail('population','expected an object.');
  const baseline=config.preset==='baseline'||config.preset==='baseline_v0.1'||config.scenario==='baseline_v0.1';
  const defaults=presets[baseline?'baseline':'small']?.population;
  if(!object(defaults))fail('population','configuration defaults are not available yet.');
  const supplied=config.population??{};const result={...defaults,...supplied};
  for(const key of ['human_roles','zombie_roles'])if(object(defaults[key])&&object(supplied[key]))result[key]={...defaults[key],...supplied[key]};
  return result;
}
function totalFor(population:Obj,kind:RoleKind):number {
  const value=population[populationKey[kind]];
  if(typeof value!=='number'||!Number.isFinite(value)||!Number.isInteger(value)||value<0)fail(`population.${populationKey[kind]}`,'enter a nonnegative whole population before allocating roles.');
  return value;
}

/** Exact decimal input: percentages never round-trip through binary floating point. */
export function parseRolePercentage(text:string,path:string):Ratio {
  const field=/^gui\.role_allocation\.(Human|Zombie)\.targets\.([A-Z]+)$/.exec(path);
  const label=field?`${field[1]} ${roleLabel(field[2])} target`:path;
  const invalid=(message:string):never=>fail(path,message,label);
  const value=text.trim();
  if(!value)invalid('enter a percentage; this field is empty.');
  const match=/^([+-]?)(\d+(?:\.\d*)?|\.\d+)(?:[eE]([+-]?\d+))?$/.exec(value);
  if(!match)return invalid('enter a complete finite percentage.');
  if(!Number.isFinite(Number(value)))invalid('enter a finite percentage.');
  const digits=match[2].replace('.','');
  const decimalPlaces=(match[2].split('.')[1]||'').length;
  const exponent=Number(match[3]||0)-decimalPlaces-2;
  // Zero is exact regardless of its textual exponent. Nonzero finite JS input
  // has a practical exponent, while the mantissa itself remains exact here.
  let n=BigInt(digits);if(match[1]==='-')n=-n;
  if(n===0n)return {numerator:'0',denominator:'1'};
  if(!Number.isSafeInteger(exponent)||Math.abs(exponent)>10000)invalid('percentage exponent is too large to edit.');
  const result=fraction(exponent>=0?n*10n**BigInt(exponent):n,exponent<0?10n**BigInt(-exponent):1n);
  if(result.n<0n||result.n>result.d)invalid('enter a percentage from 0 through 100.');
  return ratio(result);
}

/** Largest remainders, compared exactly; array order is the stable tie break. */
export function allocateRoles(total:number,targets:Record<string,Ratio>,kind:RoleKind):Record<string,number> {
  const count=BigInt(total);
  const entries=roleOrder[kind].map((role,index)=>{
    const {n,d}=unpack(targets[role]);const quota=count*n;
    return {role,index,count:quota/d,remainder:quota%d,denominator:d};
  });
  let left=count-entries.reduce((sum,item)=>sum+item.count,0n);
  const ranked=[...entries].sort((a,b)=>{
    const comparison=a.remainder*b.denominator-b.remainder*a.denominator;
    return comparison===0n?a.index-b.index:comparison>0n?-1:1;
  });
  for(const entry of ranked){if(left===0n)break;entry.count++;left--;}
  return Object.fromEntries(entries.map(entry=>{
    return [entry.role,exactCount(entry.count,kind)];
  }));
}

/** Read legacy counts without rewriting them; imported ratios remain exact. */
export function readRoleGroups(config:Obj,presets:Obj):RoleGroups {
  config=effectiveConfiguration(config);
  const population=effectivePopulation(config,presets);
  const saved=config.gui?.role_allocation;
  if(saved!==undefined&&(!object(saved)||Object.keys(saved).sort().join()!=='Human,Zombie,method,schema_version'||saved.schema_version!==1||saved.method!=='largest_remainder'))fail('gui.role_allocation','unsupported role-allocation metadata.');
  return Object.fromEntries(roleKinds.map(kind=>{
    const total=totalFor(population,kind);const path=`population.${rolesKey[kind]}`;
    const source=population[rolesKey[kind]];
    if(!object(source))fail(path,'expected integer role counts.');
    for(const [role,value] of Object.entries(source)){
      if(!roleOrder[kind].slice(1).includes(role))fail(`${path}.${role}`,`role is not compatible with ${kind}.`);
      if(typeof value!=='number'||!Number.isFinite(value)||!Number.isInteger(value)||value<0)fail(`${path}.${role}`,'expected a nonnegative integer.');
    }
    const counts:Record<string,number>=Object.fromEntries(roleOrder[kind].slice(1).map(role=>[role,source[role]??0]));
    const assigned=Object.values(counts).reduce((sum,count)=>sum+BigInt(count),0n);
    if(assigned>BigInt(total))fail(path,'role counts exceed the population. Correct the imported counts before changing their percentages.');
    counts.unassigned=exactCount(BigInt(total)-assigned,kind);
    let targets:Record<string,Ratio>;
    if(saved!==undefined){
      const entry=saved[kind];const targetPath=`gui.role_allocation.${kind}`;
      if(!object(entry)||Object.keys(entry).sort().join()!=='targets,tie_order'||JSON.stringify(entry.tie_order)!==JSON.stringify(roleOrder[kind])||!object(entry.targets)
          ||Object.keys(entry.targets).sort().join()!==[...roleOrder[kind]].sort().join())fail(targetPath,'expected all compatible shares and the recorded ontology tie order.');
      targets=Object.fromEntries(roleOrder[kind].map(role=>[role,readRatio(entry.targets[role],`${targetPath}.targets.${role}`)]));
      if(!same(Object.values(targets).reduce((sum,value)=>add(sum,unpack(value)),{n:0n,d:1n}),{n:1n,d:1n}))fail(targetPath,'target shares must total exactly 100%.');
      const allocated=allocateRoles(total,targets,kind);
      if(roleOrder[kind].some(role=>allocated[role]!==counts[role]))fail(targetPath,'targets and integer role counts disagree. Correct the configuration before editing.');
    }else{
      targets=Object.fromEntries(roleOrder[kind].map(role=>[role,ratio(total?fraction(BigInt(counts[role]),BigInt(total)):{n:role==='unassigned'?1n:0n,d:1n})]));
    }
    return [kind,{total,counts,targets}];
  })) as RoleGroups;
}

/** Merge all valid role and population edits in one draft transaction. */
export function applyRoleEdits(base:Obj,next:Obj,pending:Record<string,string>,populationChanges:Set<string>,presets:Obj):void {
  if(!Object.keys(pending).length&&!populationChanges.size)return;
  const blocked=roleEditingBlock(base);if(blocked)fail('population',blocked);
  const groups=readRoleGroups(base,presets);
  for(const kind of roleKinds){
    let changed=populationChanges.has(populationKey[kind]);
    for(const role of roleOrder[kind].slice(1)){
      const key=`${kind}.${role}`;
      if(own(pending,key)){groups[kind].targets[role]=parseRolePercentage(pending[key],`gui.role_allocation.${kind}.targets.${role}`);changed=true;}
    }
    const assigned=roleOrder[kind].slice(1).reduce((sum,role)=>add(sum,unpack(groups[kind].targets[role])),{n:0n,d:1n});
    if(assigned.n>assigned.d)fail(`gui.role_allocation.${kind}`,'total exceeds 100%; reduce the requested shares.',`${kind} role percentages`);
    groups[kind].targets.unassigned=ratio(fraction(assigned.d-assigned.n,assigned.d));
    if(changed){
      const total=totalFor(effectivePopulation(next,presets),kind);const counts=allocateRoles(total,groups[kind].targets,kind);
      // Metadata-only edits that yield identical counts must not change the
      // representation of an imported role map or its semantic fingerprint.
      if(roleOrder[kind].slice(1).some(role=>counts[role]!==groups[kind].counts[role])){
        const originalOrder=Object.keys(effectivePopulation(base,presets)[rolesKey[kind]]);
        const order=[...originalOrder,...roleOrder[kind].slice(1).filter(role=>!originalOrder.includes(role))];
        next.population??={};next.population[rolesKey[kind]]=Object.fromEntries(order.map(role=>[role,counts[role]]));
      }
    }
  }
  if(next.gui!==undefined&&!object(next.gui))fail('gui','expected an object to store role-allocation settings.');
  // A partial imported draft may inherit these fields. Store the complete
  // population alongside its new provenance so raw import/export can verify it,
  // while leaving omitted unrelated settings (including seed) untouched.
  next.population=effectivePopulation(next,presets);
  next.gui??={};next.gui.role_allocation={schema_version:1,method:'largest_remainder',...Object.fromEntries(roleKinds.map(kind=>[kind,{tie_order:roleOrder[kind],targets:groups[kind].targets}]))};
}

/** Display rounding is clearly marked and is never an input to allocation. */
export function percentageLabel(value:Ratio):{text:string;approximate:boolean} {
  const {n,d}=unpack(value);const scaled=n*10000n;const rounded=(scaled*2n+d)/(d*2n);
  const whole=rounded/100n;const decimal=String(rounded%100n).padStart(2,'0').replace(/0+$/,'');
  return {text:`${whole}${decimal?'.'+decimal:''}`,approximate:scaled%d!==0n};
}
export function realizedLabel(count:number,total:number):string {
  if(!total)return '—';
  const label=percentageLabel(ratio(fraction(BigInt(count),BigInt(total))));
  return `${label.approximate?'≈ ':''}${label.text}%`;
}
export function targetMatchesCount(target:Ratio,count:number,total:number):boolean {
  return total>0&&same(unpack(target),fraction(BigInt(count),BigInt(total)));
}
