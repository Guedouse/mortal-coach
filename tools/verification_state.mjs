// Passive observation only: never reset, solve or modify a Turnstile widget.
export function installVerificationObserver() {
  if (window.__mcVerification) return;
  window.__mcVerification = { failure: null };
  window.addEventListener('message', (event) => {
    if (event.origin !== 'https://challenges.cloudflare.com') return;
    const data = event.data;
    if (!data || data.source !== 'cloudflare-challenge' || typeof data.widgetId !== 'string') return;
    // Mortal has two widgets. A botForm failure must not stop reviewForm.
    const form = document.forms.reviewForm;
    const response = form && [...form.querySelectorAll('[name="cf-turnstile-response"]')]
      .find(el => el.id === `cf-chl-widget-${data.widgetId}_response`);
    if (!response) return;
    if (data.event === 'fail' || data.event === 'error') {
      const code = String(data.code || data.errorCode || '');
      window.__mcVerification.failure = { code: /^\d{6}$/.test(code) ? code : 'unknown' };
    } else if (['init', 'complete', 'refreshRequest'].includes(data.event)) {
      window.__mcVerification.failure = null;
    }
  });
}

export function verificationFailure(state) {
  const code = state && state.failure && state.failure.code;
  if (!code) return null;
  return /^\d{6}$/.test(code) ? code : 'unknown';
}
