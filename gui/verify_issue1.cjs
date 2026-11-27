/* Actual browser verification for the disposable I01 fixture service only. */
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const [base, identity, output] = process.argv.slice(2);
  if (!base || !identity || !output) throw Error('Pass the disposable service URL, run id, and output directory');
  const browser = await chromium.launch({executablePath:'/usr/bin/google-chrome', headless:true});
  const errors = [], streams = [], frames = [];
  const outstanding = new Set(), requests = [];
  const report = {passed:false, browser:browser.version()};
  try {
    const page = await browser.newPage({baseURL:base, viewport:{width:1440,height:1100}});
    page.on('pageerror', error => errors.push(String(error)));
    page.on('request', request => {
      if (request.url().includes('/api/')) {
        outstanding.add(request);
        requests.push({url:request.url(), method:request.method()});
      }
    });
    page.on('requestfinished', request => outstanding.delete(request));
    page.on('requestfailed', request => outstanding.delete(request));
    page.on('websocket', socket => {
      const record = {url:socket.url(), closed:false}; streams.push(record);
      socket.on('close', () => {record.closed = true;});
      socket.on('framereceived', event => {try {frames.push(JSON.parse(String(event.payload)));} catch {}});
    });
    await page.goto(base);
    const call = async (route) => {
      const response = await page.request.get(route);
      if (!response.ok()) throw Error(`${route}: ${response.status()} ${await response.text()}`);
      return response.json();
    };
    await page.locator(`button[data-run-id="${identity}"]`).click();
    await page.waitForFunction(id => window.__zombieInspection?.app?.run_id === id && window.__zombieInspection?.app?.view, identity);
    // An independent, acknowledging browser socket exercises the transport's
    // final-frame contract even when the UI learns termination first by HTTP.
    await page.evaluate(id => {
      const socket = new WebSocket(`${location.origin.replace('http', 'ws')}/api/runs/${id}/stream`);
      window.__issue1Probe = {socket, frames:0};
      socket.onmessage = event => {
        const frame = JSON.parse(event.data);
        window.__issue1Probe.frames++;
        socket.send(JSON.stringify({ack:frame.sequence}));
      };
    }, identity);
    await page.waitForFunction(() => window.__issue1Probe.frames > 0);
    await page.getByTestId('run-group-active').locator(`[data-run-id="${identity}"]`).waitFor();
    if (await page.getByTestId('run-terminate').innerText() !== 'Terminate without a new checkpoint') throw Error('Termination label is misleading');
    await page.waitForFunction(id => {
      const app = window.__zombieInspection.app;
      return !app.pending && !app.view_pending && app.metrics_cursor?.run_id === id &&
        String(app.metrics_cursor.revision) === String(app.view?.revision) &&
        String(app.metrics_cursor.time) === String(app.view?.time);
    }, identity);
    const settleDeadline = Date.now() + 30000;
    while (outstanding.size) {
      if (Date.now() > settleDeadline) throw Error(`Initial API requests did not settle: ${[...outstanding].map(request=>request.url())}`);
      await page.waitForTimeout(50);
    }
    const idleBefore = await call('/__issue1/diagnostics');
    await page.waitForTimeout(1200);
    const idleAfter = await call('/__issue1/diagnostics');
    if (idleBefore.cache.builds !== idleAfter.cache.builds || idleBefore.counters.state_at !== idleAfter.counters.state_at) {
      throw Error(`Paused subscription reconstructed unchanged history: ${JSON.stringify({idleBefore,idleAfter})}`);
    }
    const auditBefore = await call(`/__issue1/audit/${identity}`);
    const commandResponse = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith(`/api/runs/${identity}/commands`));
    await page.getByTestId('run-terminate').click();
    const accepted = await (await commandResponse).json();
    await page.getByTestId('run-lifecycle-status').filter({hasText:'Stopping / cleanup'}).waitFor({timeout:30000});
    const row = (await call('/api/runs')).find(row => row.id === identity);
    if (row.status !== 'terminated' || row.resource_status.cleanup_complete || !row.resource_status.worker_active) throw Error(`Untruthful cleanup status ${JSON.stringify(row)}`);
    const barrier = await call(`/__issue1/barrier/${identity}/cleanup/read`);
    if (!barrier) throw Error('Did not observe actual worker cleanup barrier');
    const receipt = await call(`/api/commands/${accepted.command_id}`);
    if (receipt.status !== 'applied' || receipt.run_status !== 'terminated') throw Error(`No durable termination acknowledgement ${JSON.stringify(receipt)}`);
    await page.screenshot({path:path.join(output,'stopping-cleanup.png'),fullPage:true});
    await page.waitForTimeout(500);
    const during = await call(`/__issue1/audit/${identity}`);
    if (during.frontier[0] !== auditBefore.frontier[0]) throw Error('Terminate changed the paused world revision');
    if (during.checkpoint_sha256 !== auditBefore.checkpoint_sha256) throw Error('Terminate wrote a checkpoint');
    await call(`/__issue1/barrier/${identity}/cleanup/release`);
    await page.getByTestId('run-lifecycle-status').filter({hasText:/^terminated$/i}).waitFor({timeout:30000});
    await page.locator('.ack').filter({hasText:'Worker cleanup complete.'}).waitFor();
    await page.getByTestId('run-group-terminated').locator(`[data-run-id="${identity}"]`).waitFor();
    if (await page.getByTestId('run-group-saved').locator(`[data-run-id="${identity}"]`).count()) throw Error('Terminated run remains in saved group');
    if (!await page.getByTestId('run-start').isDisabled()) throw Error('Terminated run remains resumable');
    await page.waitForTimeout(500);
    const finalBefore = await call('/__issue1/diagnostics');
    const streamCount = streams.length;
    await page.waitForTimeout(1300);
    const finalAfter = await call('/__issue1/diagnostics');
    if (streams.length !== streamCount || streams.some(stream => !stream.closed)) throw Error('Terminal browser stream remained connected or reconnected');
    if (finalBefore.cache.builds !== finalAfter.cache.builds || finalBefore.counters.state_at !== finalAfter.counters.state_at) throw Error('Terminal idle reads reconstructed history');
    const terminalFrame = frames.find(frame => frame.control?.status === 'terminated');
    if (!terminalFrame) throw Error('No terminal WebSocket frame for same-revision control transition');
    if (String(terminalFrame.revision) !== String(auditBefore.frontier[0])) throw Error('Terminal frame has wrong frontier');
    const replay = await call(`/api/runs/${identity}/view?revision=${auditBefore.frontier[0]}`);
    if (replay.mode !== 'replay' || String(replay.revision) !== String(auditBefore.frontier[0])) throw Error('Retained history cannot be replayed');
    await page.screenshot({path:path.join(output,'terminated-history.png'),fullPage:true});
    if (errors.length) throw Error(JSON.stringify(errors));
    const finalRow = (await call('/api/runs')).find(row => row.id === identity);
    Object.assign(report, {passed:true, run_id:identity,
      terminate_receipt:receipt,
      paused_idle:{before:idleBefore,after:idleAfter}, terminal_idle:{before:finalBefore,after:finalAfter},
      durable_ack_before_cleanup:true, barrier, final_resource_status:finalRow.resource_status,
      same_revision_terminal_frame:true, streams, page_errors:errors, replay_retained:true, requests});
    console.log('I01 browser lifecycle, groups, replay, and idle stream checks PASS');
  } finally {
    fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify(report,null,2));
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
