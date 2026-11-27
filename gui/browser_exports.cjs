const {openExactEditor}=require('./browser_exact_time.cjs');
/* Export acceptance actions use the same visible controls and downloads as users. */
const fs=require('node:fs');const path=require('node:path');
async function executeExport(page,step){
  const operation=step.op.replace(/^browser\./,'');
  if(operation==='export_form'){
    const details=page.locator('[data-testid="export-open"]');
    if(!await details.evaluate(el=>el.parentElement.open))await details.click();
    await page.getByTestId('export-format').selectOption(step.format);
    if(step.time!==undefined){await openExactEditor(page,'export-time');await page.getByTestId('export-time').fill(String(step.time));}
    if(step.interval){await openExactEditor(page,'export-interval-start');await openExactEditor(page,'export-interval-end');await page.getByTestId('export-interval-start').fill(String(step.interval[0]));await page.getByTestId('export-interval-end').fill(String(step.interval[1]));}
    if(step.sample_interval!==undefined){await openExactEditor(page,'export-sample-interval');await page.getByTestId('export-sample-interval').fill(String(step.sample_interval));}
    if(step.cohort)await page.getByTestId('export-cohort').selectOption(step.cohort);
    return await page.evaluate(()=>window.__zombieExportInspection);
  }
  if(operation==='await_export'){
    await page.waitForFunction(()=>['COMPLETED','FAILED','CANCELLED'].includes(window.__zombieExportInspection?.job?.status),null,{timeout:60000});
    const job=await page.evaluate(()=>window.__zombieExportInspection.job);
    if(job.status!=='COMPLETED')throw Error(`Export ${job.status}: ${job.error||''}`);
    const directory=step.artifacts||step.directory;if(!directory)throw Error('Export downloads require an artifact directory');fs.mkdirSync(directory,{recursive:true});
    const download=async(testid)=>{const event=page.waitForEvent('download');await page.getByTestId(testid).click();const item=await event;const destination=path.join(directory,item.suggestedFilename());await item.saveAs(destination);return destination;};
    return {...job,path:await download('export-artifact'),provenance_path:await download('export-provenance')};
  }
  if(operation==='export_job'){
    await page.waitForFunction(()=>window.__zombieExportInspection?.job?.active_tasks===0,null,{timeout:20000});
    return await page.evaluate(()=>window.__zombieExportInspection.job);
  }
  throw Error(`Unknown export browser operation: ${operation}`);
}
module.exports={executeExport};
