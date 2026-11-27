/* Independent pure-editor oracles. Supplied acceptance tests are unchanged. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {execFileSync}=require('node:child_process'),Module=require('node:module');
const root=path.resolve(__dirname,'..'),ts=require(path.join(root,'gui/node_modules/typescript'));
const source=path.join(root,'gui/src/worldLayout.ts');
const compiled=ts.transpileModule(fs.readFileSync(source,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const loaded=new Module(source,module);loaded.filename=source;loaded.paths=module.paths;loaded._compile(compiled,source);
const {effectiveWorld,applyWorldResize,worldResizeSummary}=loaded.exports;
const presets=JSON.parse(execFileSync(path.join(root,'.runtimeenv/bin/python'),['-c','import json; from zombie_sim.config import DEFAULTS, baseline_config; print(json.dumps({"small":DEFAULTS,"baseline":baseline_config()}))'],{cwd:root,env:{...process.env,PYTHONPATH:path.join(root,'src'),PYTHONDONTWRITEBYTECODE:'1'},encoding:'utf8'}));
const clone=value=>structuredClone(value),report={passed:false,cases:[]};
function check(name,fn){fn();report.cases.push(name);}
function resize(base,edited){const next=clone(base);next.world={...(next.world||{})};for(const [key,value] of Object.entries(edited))if(key.startsWith('world.'))next.world[key.split('.')[1]]=value;applyWorldResize(base,next,edited,presets);return next;}
const coords=(rectangle)=>Array.isArray(rectangle)?rectangle:rectangle.footprint?coords(rectangle.footprint):['xmin','ymin','xmax','ymax'].map(key=>rectangle[key]);
const layout=value=>Object.fromEntries(['barriers','shelters','stockpiles'].map(key=>[key,value[key]]));
function coordinateOracle(base,next,l,w){
 for(const key of ['barriers','shelters'])for(let i=0;i<base[key].length;i++){
  const field=key==='barriers'?'footprint':'interior';
  assert.deepEqual(coords(next[key][i][field]),coords(base[key][i][field]).map((value,index)=>value*(index%2?w:l)/1000));
  const a=clone(base[key][i]),b=clone(next[key][i]);delete a[field];delete b[field];assert.deepEqual(a,b);
 }
 for(let i=0;i<base.stockpiles.length;i++){
  assert.equal(next.stockpiles[i].x,base.stockpiles[i].x*l/1000);assert.equal(next.stockpiles[i].y,base.stockpiles[i].y*w/1000);
  const a=clone(base.stockpiles[i]),b=clone(next.stockpiles[i]);delete a.x;delete a.y;delete b.x;delete b.y;assert.deepEqual(a,b);
 }
}
const baseline=clone(presets.baseline),untouched=clone(presets);
check('No resize for unedited or unchanged dimensions',()=>{
 for(const edits of [{},{'seed':5},{'world.length':1000},{'world.width':1000}])assert.deepEqual(resize(baseline,edits),baseline);
 assert.deepEqual(effectiveWorld({preset:'baseline'},presets),baseline.world);
});
for(const [length,width] of [[200,200],[200,1000],[1000,200],[200,400],[2000,3000]])check(`Whole baseline geometry ${length} x ${width}`,()=>{
 const result=resize(baseline,{'world.length':length,'world.width':width});coordinateOracle(baseline,result,length,width);
 assert.deepEqual(result.population,baseline.population);assert.deepEqual(result.placement,baseline.placement);
 for(const key of ['profiles','seed','horizon','incubation_duration','execution','storage'])assert.deepEqual(result[key],baseline[key]);
 const summary=worldResizeSummary(result);assert(summary.customizedBaseline);assert.deepEqual(summary.counts,{barriers:28,shelters:4,stockpiles:10,agents:0});
 assert.equal(summary.to.length,length);assert.equal(summary.to.width,width);
});
check('Repeated sequential/asymmetric edits restore the original coordinates exactly',()=>{
 let value=baseline;
 for(const edits of [{'world.length':333.3333333333333},{'world.width':247.171},{'world.length':200},{'world.width':200},{'world.width':654.321},{'world.length':1000},{'world.width':1000}])value=resize(value,edits);
 assert.deepEqual(layout(value),layout(baseline));
 assert.deepEqual(value.world,baseline.world);
});
check('Serialized resized draft retains stable reference and avoids double scaling',()=>{
 const resized=resize(baseline,{'world.length':200,'world.width':200}),saved=JSON.parse(JSON.stringify(resized));
 assert.deepEqual(resize(saved,{'world.length':200,'world.width':200}),saved);
 assert.deepEqual(layout(resize(saved,{'world.length':1000,'world.width':1000})),layout(baseline));
});
for(const partial of [{preset:'baseline'},{scenario:'baseline_v0.1'}])check(`Partial baseline ${Object.keys(partial)[0]} materializes inherited layout`,()=>{
 const result=resize(partial,{'world.length':200,'world.width':200});coordinateOracle(baseline,result,200,200);
 assert.equal(result.world.length,200);assert.equal(result.world.width,200);assert.equal(result.world.boundary_policy,'CLOSED');
});
check('Semantic geometry overrides become explicit, unrelated overrides survive',()=>{
 const input={preset:'baseline',seed:123,semantic:{seed:456,horizon:99,world:{length:800,width:500},barriers:[{id:'o',type:'Obstacle',footprint:[40,50,80,100]}],shelters:[],stockpiles:[{id:'s',x:200,y:250,inventory:{FOOD:42}}],agents:{h:{id:'h',type:'Human',x:400,y:400},z:{id:'z',type:'Zombie',x:700,y:300}}}};
 const before=clone(input);assert.deepEqual(effectiveWorld(input,presets),{length:800,width:500,boundary_policy:'CLOSED'});
 const result=resize(input,{'world.length':200,'world.width':400});
 assert.deepEqual(result.barriers[0].footprint,[10,40,20,80]);assert.deepEqual(result.stockpiles[0],{id:'s',x:50,y:200,inventory:{FOOD:42}});
 assert.deepEqual([result.agents.h.x,result.agents.h.y,result.agents.z.x,result.agents.z.y],[100,320,175,240]);
 assert.deepEqual(result.semantic,{seed:456,horizon:99});assert.equal(result.seed,123);assert.deepEqual(input,before);
});
check('Rectangle object forms, nested footprint and ordinary agent maps are retained',()=>{
 const input={world:{length:100,width:100},barriers:[{id:'o',footprint:{footprint:{xmin:'20',ymin:30,xmax:40,ymax:50},tag:'custom'}}],shelters:[],stockpiles:[{id:'s',x:60,y:70,inventory:{FOOD:9}}],agents:{a:{id:'a',type:'Human',x:10,y:90,model_assignment:{model_id:'HumanDefaultModel',parameters:{look:12}}},b:{id:'b',type:'Zombie'}}};
 const result=resize(input,{'world.length':50,'world.width':200});
 assert.deepEqual(result.barriers[0].footprint,{footprint:{xmin:10,ymin:60,xmax:20,ymax:100},tag:'custom'});
 assert.equal(Array.isArray(result.agents),false);assert.deepEqual([result.agents.a.x,result.agents.a.y,result.agents.b.x,result.agents.b.y],[5,180,0,0]);
 assert.deepEqual(result.agents.a.model_assignment,input.agents.a.model_assignment);
 assert.deepEqual(worldResizeSummary(result).counts,{barriers:1,shelters:0,stockpiles:1,agents:2});
});
check('Agent arrays preserve positions, independent values and declared type',()=>{
 const input={world:{length:100,width:50},agents:[{id:1,type:'Human',x:40,y:20,life:90,inventory:{FOOD:1}},{id:2,type:'Zombie',x:90,y:40}],profiles:{Human:{base_speed:3,sensing_radius:40}},placement:{minimum_separation:2,cross_type_separation:15}};
 const result=resize(input,{'world.length':200,'world.width':100});
 assert.deepEqual(result.agents,input.agents.map(agent=>({...agent,x:agent.x*2,y:agent.y*2})));assert.deepEqual(result.profiles,input.profiles);assert.deepEqual(result.placement,input.placement);
});
check('Resource-only edits survive a later resize without resetting the spatial reference',()=>{
 const resized=resize(baseline,{'world.length':200,'world.width':200});resized.stockpiles[0].inventory.FOOD=999;
 const restored=resize(resized,{'world.length':1000,'world.width':1000});
 assert.equal(restored.stockpiles[0].inventory.FOOD,999);assert.deepEqual(restored.barriers,baseline.barriers);
 assert.equal(restored.stockpiles[0].x,baseline.stockpiles[0].x);assert.equal(restored.stockpiles[0].y,baseline.stockpiles[0].y);
 assert.deepEqual(restored.gui.world_resize.reference.world,{length:1000,width:1000});
});
check('Intentional geometry edits invalidate old anchors and stale summary',()=>{
 const resized=resize(baseline,{'world.length':200,'world.width':200});resized.stockpiles[0].x=30;
 assert.equal(worldResizeSummary(resized),undefined);
 const result=resize(resized,{'world.length':400});assert.equal(result.stockpiles[0].x,60);
 assert.deepEqual(result.gui.world_resize.reference.world,{length:200,width:200});
});
check('Tampered editor references cannot move unchanged authored coordinates',()=>{
 const resized=resize(baseline,{'world.length':200,'world.width':200});resized.gui.world_resize.reference.layout.stockpiles[0].coordinates[0]=999;
 const result=resize(resized,{'world.length':400});assert.equal(result.stockpiles[0].x,40);
 assert.deepEqual(result.gui.world_resize.reference.world,{length:200,width:200});
});
check('Tampered counts cannot produce a false adjustment summary',()=>{
 const resized=resize(baseline,{'world.length':200,'world.width':200});resized.gui.world_resize.counts.barriers=1;
 assert.equal(worldResizeSummary(resized),undefined);
 const corrected=resize(resized,{'world.length':400});assert.equal(worldResizeSummary(corrected).counts.barriers,28);
});
check('Unknown reference methods are not interpreted as supported resize provenance',()=>{
 const resized=resize(baseline,{'world.length':200,'world.width':200});resized.gui.world_resize.method='unsupported';
 assert.equal(worldResizeSummary(resized),undefined);
 const result=resize(resized,{'world.length':400});assert.equal(result.stockpiles[0].x,40);
 assert.deepEqual(result.gui.world_resize.reference.world,{length:200,width:200});
});
const invalid=[
 ['historical state import',{state_import:true}],['recorded remains',{remains:[{id:'r'}]}],['recorded signals',{signals:{s:{x:20,y:30}}}],
 ['agent private memory',{agents:[{id:'h',x:20,y:20,model_memory:{seen:[]}}]}],['model assignment state',{agents:[{id:'h',x:20,y:20,model_assignment:{state:{map:[]}}}]}],
 ['agent alternate position',{agents:[{id:'h',x:20,y:20,position:{x:10,y:10}}]}],['stockpile alternate point',{stockpiles:[{id:'s',x:20,y:20,position:[10,10]}]}],
 ['malformed rectangle',{barriers:[{id:'x',footprint:[1,2,3]}]}],['nonpositive rectangle',{barriers:[{id:'x',footprint:[2,2,2,3]}]}],
 ['invalid semantic object',{semantic:null}],['invalid GUI metadata object',{gui:[]}],['nonfinite coordinate',{stockpiles:[{id:'s',x:NaN,y:2}]}],
 ['duplicate IDs',{agents:[{id:'h',x:1,y:2},{id:'h',x:3,y:4}]}],['dead initial identity',{agents:[{id:'h',x:1,y:2,life:0}]}],
];
for(const [name,fields] of invalid)check(`Atomic rejection: ${name}`,()=>{
 const input={...clone(presets.small),...fields},next=clone(input);next.world.length=50;const before=clone(next);
 assert.throws(()=>applyWorldResize(input,next,{'world.length':50},presets),error=>error.code==='INVALID_GEOMETRY'&&error.issues.length>0);
 assert.deepEqual(next,before);
});
check('Extreme resize cannot silently collapse positive geometry or coordinates',()=>{
 const input={...clone(presets.small),world:{length:1e308,width:1e308},stockpiles:[{id:'s',x:1e-300,y:1}]};
 assert.throws(()=>resize(input,{'world.length':1e-300}),/too large or too small/);
});
check('Same-size historical input remains unchanged; parsing never triggers a transformation',()=>{
 const input={...clone(presets.small),state_import:true,signals:{s:{x:10,y:20}}};assert.deepEqual(resize(input,{'world.length':100}),input);
 const raw=JSON.stringify(resize(baseline,{'world.length':200,'world.width':200}));assert.equal(JSON.stringify(JSON.parse(raw)),raw);
});
check('Presets and source baseline remain byte-for-byte unchanged',()=>{assert.deepEqual(presets,untouched);assert.deepEqual(baseline,presets.baseline);});
report.passed=true;report.case_count=report.cases.length;
const output=process.argv[2];if(output){fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');}
console.log(JSON.stringify({passed:true,cases:report.case_count,report:output||null}));
