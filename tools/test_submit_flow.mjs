// Exercise the actual submit script against a fake CDP endpoint; no website/tokens/network.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { EventEmitter } from 'node:events';
import { installVerificationObserver, verificationFailure } from './verification_state.mjs';
import { isReportUrl } from './url_rules.mjs';

const source = fs.readFileSync(new URL('./submit_auto.mjs', import.meta.url), 'utf8')
  .replace(/^import .*;\s*$/gm, '');
const HOME = 'https://mjai.ekyu.moe/';
async function scenario(mode, cfg = {}) {
  const calls = [], logs = [], input = new EventEmitter();
  input.setEncoding = () => {};
  let nav = 0, sentReload = false;
  let finish;
  const finished = new Promise(resolve => { finish = resolve; });
  const exitError = new Error('exit');
  class FakeSocket {
    constructor() { queueMicrotask(() => this.onopen()); }
    close() {}
    send(json) {
      const m = JSON.parse(json);
      calls.push(m);
      let value;
      if (m.method === 'Page.navigate') nav++;
      if (m.method === 'Runtime.evaluate') {
        const e = m.params.expression;
        if (e.includes('for (const el of els)')) {
          value = mode === 'verified' || (mode === 'reload' && nav) ? 'test-only-response'.repeat(5) : '';
        } else if (e.includes('failure: window.__mcVerification')) {
          value = JSON.stringify({ url: mode === 'progress' ? HOME + 'progress?task=x' : HOME,
            form: mode !== 'progress', ready: 'complete',
            failure: mode === 'failed' ? { code: '600010' } : null });
        } else if (e.includes('getBoundingClientRect')) value = '';
        else if (e === 'location.href') value = HOME;
        else value = null;
      }
      const result = m.method === 'Runtime.evaluate' ? { result: { value } }
        : m.method === 'Browser.getWindowForTarget' ? { windowId: 1 } : {};
      queueMicrotask(() => this.onmessage({ data: JSON.stringify({ id: m.id, result }) }));
    }
  }
  const context = {
    console: { log: (...args) => logs.push(args.join(' ')) },
    process: { argv: ['node', 'script', JSON.stringify({ url: 'https://tenhou.net/0/?log=test',
      show: true, wait: 60, ...cfg })], stdin: input, env: { MC_TOKEN_ONLY: '1' },
      exit: code => { finish({ code, calls, logs }); throw exitError; } },
    fetch: async () => ({ json: async () => [{ type: 'page', url: HOME, id: 'review', webSocketDebuggerUrl: 'ws://fake' }] }),
    WebSocket: FakeSocket, URL, installVerificationObserver, verificationFailure, isReportUrl,
    setTimeout: (fn, ms) => {
      if (ms >= 20000) return setTimeout(fn, ms);
      if (mode === 'reload' && ms === 1000 && !sentReload) {
        sentReload = true;
        input.emit('data', 'reload-verification\n');
      }
      queueMicrotask(fn);
      return null;
    }, clearTimeout, queueMicrotask,
  };
  vm.runInNewContext(`(async () => {${source}\n})()`, context).catch(e => {
    if (e !== exitError) finish({ error: String(e), calls, logs });
  });
  const result = await finished;
  assert.equal(result.error, undefined, result.error);
  return result;
}

const verified = await scenario('verified');
assert.equal(verified.code, 0);
assert.equal(verified.calls.filter(c => c.method === 'Page.navigate').length, 0,
  'reuse settings verification without resetting document');
assert(verified.logs.some(l => l.startsWith('TOKEN_ONLY_OK')));
const failed = await scenario('failed');
assert.equal(failed.code, 2);
assert(failed.logs.includes('VERIFICATION_FAILED 600010'));
assert(failed.logs.some(l => l.startsWith('VERIFICATION_PENDING')));
assert(!failed.calls.some(c => c.method === 'Page.navigate'), 'failure does not auto-refresh');
assert(!failed.logs.some(l => l.startsWith('SUBMIT ')), 'never submit on failed verification');
const reloaded = await scenario('reload');
assert.equal(reloaded.code, 0);
assert.equal(reloaded.calls.filter(c => c.method === 'Page.navigate').length, 1,
  'explicit user request refreshes once before submission');
const progress = await scenario('progress', { reload: true, resume: true });
assert.equal(progress.code, 4);
assert(!progress.calls.some(c => c.method === 'Page.navigate'), 'do not reload progress/report');
const timeout = await scenario('waiting');
assert.equal(timeout.code, 2);
assert(timeout.logs.some(l => l.startsWith('VERIFICATION_TIMEOUT')));
assert(!timeout.logs.some(l => l.startsWith('VERIFICATION_FAILED')));
assert(!timeout.calls.some(c => c.method === 'Page.navigate'), 'no automatic refresh on timeout');
console.log('submit flow: 5 CDP scenarios passed');
