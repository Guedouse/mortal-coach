import assert from 'node:assert/strict';
import vm from 'node:vm';
import { installVerificationObserver, verificationFailure } from './verification_state.mjs';

let receive;
const response = { id: 'cf-chl-widget-review_response' };
const ctx = { window: { addEventListener: (name, fn) => { receive = fn; } },
  document: { forms: { reviewForm: { querySelectorAll: () => [response] } } } };
vm.runInNewContext(`(${installVerificationObserver.toString()})()`, ctx);
const event = (widgetId, kind, code, origin = 'https://challenges.cloudflare.com') => receive({
  origin, data: { source: 'cloudflare-challenge', widgetId, event: kind, code },
});
assert.equal(verificationFailure(ctx.window.__mcVerification), null);
event('bot', 'fail', '600010');
assert.equal(verificationFailure(ctx.window.__mcVerification), null, 'ignore bot widget');
event('review', 'fail', '600010', 'https://untrusted.invalid');
assert.equal(verificationFailure(ctx.window.__mcVerification), null, 'ignore other origin');
event('review', 'fail', '600010');
assert.equal(verificationFailure(ctx.window.__mcVerification), '600010');
event('review', 'complete');
assert.equal(verificationFailure(ctx.window.__mcVerification), null, 'manual success clears failure');
event('review', 'fail', '<secret>');
assert.equal(verificationFailure(ctx.window.__mcVerification), 'unknown', 'never log arbitrary payload');
event('review', 'init');
assert.equal(verificationFailure(ctx.window.__mcVerification), null);
console.log('verification observer: 7 scenarios passed');
