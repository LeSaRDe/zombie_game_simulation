const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');

(async()=>{
  const output=path.resolve('artifacts/runtime_controls');fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true});
  const failures=[],errors=[],runs=[];const batch=Date.now();
  try {
    const page=await browser.newPage({baseURL:process.argv[2]||'http://127.0.0.1:8766',viewport:{width:1440,height:1100}});
    page.on('pageerror',error=>errors.push(String(error)));
    page.on('response',async response=>{
      if(response.url().includes('/api/')&&response.status()>=400){
        let data;try{data=await response.json();}catch{data={error:await response.text()};}
        if(data.code!=='RUN_INITIALIZING')failures.push({url:response.url(),status:response.status(),data});
      }
    });
    await page.goto(process.argv[2]||'http://127.0.0.1:8766');
    for(let index=0;index<3;index++){
      await page.getByRole('button',{name:/New experiment/}).click();
      await page.getByRole('dialog').waitFor();
      await page.getByText('Advanced configuration · JSON',{exact:true}).click();
      const config={scenario:`runtime_ui_${batch}_${index}`,seed:40+index,horizon:120,incubation_duration:20,
        population:{humans:3,zombies:1,infected:1},execution:{workers:1},checkpoint_interval:1000};
      await page.getByLabel('Advanced configuration JSON').fill(JSON.stringify(config));
      await page.getByRole('button',{name:'Launch run ↗',exact:true}).click();
      await page.locator('.topbar h1').filter({hasText:config.scenario}).waitFor();
      await page.getByTestId('run-pause').waitFor();
      const rows=await page.request.get('/api/runs').then(r=>r.json());
      const identity=rows.find(r=>r.config.scenario===config.scenario).id;runs.push(identity);
      for(let cycle=0;cycle<3;cycle++){
        await page.getByTestId('run-pause').click();
        await page.locator('.topbar .tag').filter({hasText:/^paused$/}).waitFor();
        await page.waitForFunction(()=>!document.querySelector('[data-testid="run-start"]').disabled);
        const before=await page.request.get(`/api/runs/${identity}/view`).then(r=>r.json());
        await page.waitForTimeout(200);
        const after=await page.request.get(`/api/runs/${identity}/view`).then(r=>r.json());
        if(before.revision!==after.revision)throw Error(`Paused run advanced ${before.revision} -> ${after.revision}`);
        await page.getByTestId('run-start').click();
        await page.getByTestId('run-pause').waitFor();
      }
      await page.getByTestId('run-terminate').click();
      await page.locator('.topbar .tag').filter({hasText:/^terminated$/}).waitFor();
      await page.waitForFunction(()=>!window.__zombieInspection.app.pending);
      if(!await page.getByTestId('run-start').isDisabled())throw Error('Terminated run remains resumable in GUI');
      if(await page.getByRole('alert').count())throw Error(await page.getByRole('alert').allTextContents());
    }
    await page.screenshot({path:path.join(output,'terminated.png'),fullPage:true});
    if(errors.length||failures.length)throw Error(JSON.stringify({errors,failures}));
    // An upstream failure should remain an intelligible HTTP failure, never a
    // JavaScript JSON.parse error. This intercept tests the browser transport.
    await page.route('**/api/runs',async route=>{
      await route.fulfill({status:500,contentType:'text/plain',body:'Internal Server Error'});
      await page.unroute('**/api/runs');
    });
    await page.getByRole('alert').filter({hasText:/server returned 500 without a valid JSON response/i}).waitFor();
    fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify({passed:true,browser:browser.version(),runs,
      create_cycles:3,pause_resume_cycles:9,unknown_run_errors:0,stale_generation_errors:0,
      pause_revisions_unchanged:true,termination_terminal:true,non_json_error_readable:true,page_errors:errors},null,2));
    console.log('Runtime browser controls PASS');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
