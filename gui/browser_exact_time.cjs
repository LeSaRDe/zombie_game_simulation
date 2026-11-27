/* Reveal an exact editor through its visible disclosure before filling it. */
async function openExactEditor(page,testid,log){
 const editor=page.getByTestId(testid+'-editor');
 if(await editor.count()&&!await editor.evaluate(element=>element.open)){
  await page.getByTestId(testid+'-toggle').click();
  if(log)log.push({action:'open_exact_time',testid,testid_toggle:testid+'-toggle'});
 }
}
module.exports={openExactEditor};
