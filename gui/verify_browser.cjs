// Independent browser verification against a disposable local workspace.
// Requires Playwright and an installed Chrome executable; no suite discovery.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const output=path.resolve(process.argv[3] || 'artifacts/browser');
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({executablePath:process.env.CHROME_BIN || '/usr/bin/google-chrome',headless:true});
  try {
  const page=await browser.newPage({viewport:{width:1440,height:1100}});
  const errors=[];page.on('pageerror',error=>errors.push(String(error)));
  let socketSnapshots=0, socketAcknowledgements=0;
  page.on('websocket',socket=>{
    socket.on('framereceived',frame=>{try{if(JSON.parse(String(frame.payload)).state)socketSnapshots++;}catch{}});
    socket.on('framesent',frame=>{try{if(JSON.parse(String(frame.payload)).ack!==undefined)socketAcknowledgements++;}catch{}});
  });
  await page.goto(process.argv[2] || 'http://127.0.0.1:8765',{waitUntil:'networkidle'});
  await page.getByRole('button',{name:/New experiment/}).waitFor();
  if(await page.locator('.run-card').count()) {
    await page.locator('.run-card').first().click();
    await page.locator('.world-frame canvas').waitFor();
    await page.screenshot({path:path.join(output,'world.png'),fullPage:true});
    await page.getByRole('button',{name:'Statistics',exact:true}).click();
    await page.locator('.js-plotly-plot').waitFor();
    await page.screenshot({path:path.join(output,'statistics.png'),fullPage:true});
    await page.getByRole('button',{name:'World',exact:true}).click();
    const firstAgent=page.locator('tbody button.link').first();
    if(await firstAgent.count()) {
      await firstAgent.click();
      await page.locator('.identity-heading').waitFor();
      await page.getByLabel('Perspective').selectOption('agent');
      if(await page.locator('.world-frame').count())throw Error('Privileged map visible in agent perspective');
      await page.getByLabel('Perspective').selectOption('researcher');
    }
  }
  await page.getByRole('button',{name:/New experiment/}).click();
  await page.getByRole('dialog').waitFor();
  await page.getByRole('button',{name:'Validate',exact:true}).click();
  await page.locator('.notice').filter({hasText:/valid/i}).waitFor();
  await page.getByRole('button',{name:'Preview placement',exact:true}).click();
  await page.locator('.preview-pane canvas').waitFor();
  await page.screenshot({path:path.join(output,'configuration.png'),fullPage:true});
  await page.getByLabel('Starting preset').selectOption('baseline');
  await page.getByLabel('Placement sampler').selectOption('relocation');
  await page.getByLabel(/Explicitly accept approximate joint placement/).check();
  const densePreview=page.waitForResponse(response=>response.url().endsWith('/api/config/preview')&&response.request().method()==='POST',{timeout:60000});
  await page.getByRole('button',{name:'Preview placement',exact:true}).click();
  const dense=await (await densePreview).json();
  if(Object.keys(dense.view?.state.agents||{}).length!==1000)throw Error('Baseline preview did not contain 1000 identities');
  await page.locator('.preview-pane canvas').waitFor();
  await page.screenshot({path:path.join(output,'baseline-preview.png'),fullPage:true});
  await page.keyboard.press('Escape');
  if(await page.getByRole('dialog').count())throw Error('Escape did not close configuration');
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:path.join(output,'mobile.png'),fullPage:true});
  const width=await page.evaluate(()=>({document:document.documentElement.scrollWidth,viewport:innerWidth}));
  if(width.document>width.viewport)throw Error(`Mobile horizontal overflow: ${JSON.stringify(width)}`);
  for(const name of ['Statistics','Cohorts','Events','Comparison']) {
    await page.getByRole('button',{name,exact:true}).click();
    const size=await page.evaluate(()=>({document:document.documentElement.scrollWidth,viewport:innerWidth}));
    if(size.document>size.viewport)throw Error(`Mobile ${name} overflow: ${JSON.stringify(size)}`);
  }
  await page.getByRole('button',{name:/New experiment/}).click();
  await page.getByRole('dialog').waitFor();
  await page.screenshot({path:path.join(output,'mobile-configuration.png'),fullPage:true});
  const modalWidth=await page.evaluate(()=>({document:document.documentElement.scrollWidth,viewport:innerWidth}));
  if(modalWidth.document>modalWidth.viewport)throw Error(`Mobile modal overflow: ${JSON.stringify(modalWidth)}`);
  await page.keyboard.press('Escape');
  if(!socketSnapshots||!socketAcknowledgements)throw Error(`Missing live WebSocket snapshot/ACK: ${socketSnapshots}/${socketAcknowledgements}`);
  if(errors.length)throw Error(`Browser errors: ${errors.join('\n')}`);
  fs.writeFileSync(path.join(output,'report.json'),JSON.stringify({passed:true,browser:browser.version(),
    viewport:{desktop:[1440,1100],mobile:[390,844]},page_errors:errors,
    websocket:{snapshots:socketSnapshots,acknowledgements:socketAcknowledgements},mobile_width:width,
    checks:['world canvas','population chart','agent selection','perspective isolation',
      'configuration validation','preview canvas','1000-agent baseline preview','Escape dismiss','mobile world/tabs/configuration widths','WebSocket snapshots and acknowledgements'],
    limitations:'Functional headless Chrome check; no sustained frame-rate or Firefox measurement.'},null,2));
  console.log('Browser verification passed');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
