/* Test adapter for editing the reviewed I27 exact-time disclosure controls. */
const {openExactEditor} = require('./browser_exact_time.cjs');
async function fillExact(page, testId, value) {
  await openExactEditor(page, testId);
  await page.getByTestId(testId).fill(String(value));
}
module.exports = {fillExact};
