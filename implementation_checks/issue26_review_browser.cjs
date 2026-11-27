/* I26 pre-fix reproduction only. No run is launched or production code changed. */
const {chromium,firefox}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
  const [base,output,engine='chromium']=process.argv.slice(2);
  const report={passed:false,purpose:'pre-fix I26 review reproduction',engine,cases:[],errors:[],mutating_run_requests:[]};
  const browser=await(engine==='firefox'?firefox:chromium).launch({headless:true,...(engine==='firefox'?{}:{executablePath:'/usr/bin/google-chrome'})});
  try{
    const page=await browser.newPage({baseURL:base,viewport:{width:1440,height:1100}});
    page.on('pageerror',error=>report.errors.push(String(error)));
    page.on('request',request=>{if(request.method()==='POST'&&/\/api\/runs(?:\/|$)/.test(new URL(request.url()).pathname))report.mutating_run_requests.push(request.url());});
    await page.goto(base);await page.getByRole('button',{name:/New experiment/}).click();
    await page.waitForFunction(()=>window.__zombieInspection.configuration.load_state?.phase==='ready');
    report.assets=await page.locator('script[src]').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('src')));
    const draft=async()=>JSON.parse(await page.getByLabel('Advanced configuration JSON').inputValue());
    for(const [label,length,width] of [['length-only',200,1000],['width-only',1000,200],['both-dimensions',200,200]]){
      await page.getByTestId('config-preset').selectOption('small');await page.getByTestId('config-preset').selectOption('baseline');
      const before=await draft();
      assert.equal(before.world.length,1000);assert.equal(before.world.width,1000);
      await page.getByTestId('config-world.length').fill(String(length));
      await page.getByTestId('config-world.width').fill(String(width));
      const responsePromise=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/config/validate'&&response.request().method()==='POST');
      await page.getByTestId('config-validate').click();
      const response=await responsePromise,body=await response.json();
      await page.getByTestId('config-result').waitFor();
      const after=await draft(),feedback=await page.getByTestId('config-result').innerText();
      assert.equal(after.world.length,length);assert.equal(after.world.width,width);
      for(const field of ['barriers','shelters','stockpiles','population','placement'])assert.deepEqual(after[field],before[field]);
      assert.equal(response.status(),422);assert.match(feedback,/barriers\[0\]: rectangle must have positive area and lie inside world bounds/);
      report.cases.push({label,world_before:before.world,world_after:after.world,first_barrier_before:before.barriers[0],first_barrier_after:after.barriers[0],environment_counts:{barriers:after.barriers.length,shelters:after.shelters.length,stockpiles:after.stockpiles.length},population:after.population,placement:after.placement,http_status:response.status(),response:body,feedback,submitted_config:response.request().postDataJSON(),geometry_unchanged:true});
      if(label==='both-dimensions')await page.screenshot({path:path.join(output,'resize-validation-error.png'),fullPage:true});
    }
    assert.deepEqual(report.errors,[]);assert.deepEqual(report.mutating_run_requests,[]);report.passed=true;
  }catch(error){report.error=String(error.stack||error);throw error;}
  finally{fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify(report,null,2)+'\n');await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
