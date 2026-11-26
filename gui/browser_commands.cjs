/* Prepare research commands exclusively through the rendered controls. */
async function prepare(page,m,log){
 await page.getByTestId('command-open').click();
 await page.getByTestId('command-operation').selectOption(m.op==='intervention_form'?'intervention':m.command);
 await page.getByRole('dialog').getByText('Command reference',{exact:true}).click();
 await page.getByTestId('command-id').fill(m.command_id||m.id);
 if(m.command==='intervention'||m.op==='intervention_form'){
  await page.getByTestId('command-time').fill(m.at);
  await page.getByTestId('command-change').fill(JSON.stringify(m.change,null,2));
 }
 log.push({action:m.op,command:m.command||'intervention',command_id:m.command_id||m.id});
 return {};
}
async function click(page,m,log){
 const button=page.getByTestId(m.testid);log.push({action:'click',testid:m.testid,text:await button.innerText()});await button.click();
 await page.waitForFunction(()=>window.__zombieCommandInspection&&!window.__zombieCommandInspection.pending);
 return await page.evaluate(()=>({...window.__zombieInspection,recovery_command:window.__zombieCommandInspection}));
}
module.exports={prepare,click};
