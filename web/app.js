/* Employmaxing v1.1 — Zero-CLI Onboarding + Single-Provider OAuth2 Mail Controller (GPL-3.0) */
let STATE = {
  onboarding: null,
  mailCfg: null,
  selectedProvider: 'google',
  wizardFiles: { resume: null, linkedin: null },
  initialRouted: false,
  dashboard: null,
  facts: [],
  factFilter: 'all',
  jobs: [],
  jobFilter: 'all',
  emails: [],
  emailFilter: 'all',
  forms: [],
};

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(() => el.classList.remove('show'), 4000);
}

function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const res = String(reader.result || '');
      resolve(res.includes(',') ? res.split(',')[1] : res);
    };
    reader.onerror = () => reject(new Error('Could not read selected file.'));
    reader.readAsDataURL(file);
  });
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function switchView(viewName) {
  document.querySelectorAll('.view-section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  const target = document.getElementById(`view-${viewName}`);
  const btn = document.querySelector(`.nav-btn[data-view="${viewName}"]`);
  if (target) target.classList.add('active');
  if (btn) btn.classList.add('active');
}

document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => switchView(btn.dataset.view));
});

// Listen for OAuth2 popup completion from /api/oauth/<provider>/callback
window.addEventListener('message', (ev) => {
  if (ev.data && ev.data.type === 'employmaxing_oauth_ok') {
    toast(`Connected ${ev.data.provider.toUpperCase()} (${ev.data.email}) via 2FA-safe OAuth2!`);
    refreshAll();
  }
});

/* ==================== FIRST-TIME SETUP WIZARD ==================== */

function goWizardStep(stepNum) {
  document.querySelectorAll('.wizard-panel').forEach(p => p.classList.remove('active'));
  const panel = document.getElementById(`wizard-step-${stepNum}`);
  if (panel) panel.classList.add('active');
  document.querySelectorAll('#wizard-stepper .step-pill').forEach(pill => {
    const n = parseInt(pill.dataset.step, 10);
    pill.classList.remove('active', 'done');
    if (n === stepNum) pill.classList.add('active');
    else if (n < stepNum) pill.classList.add('done');
  });
}

function handleFilePick(input, kind) {
  const file = input.files && input.files[0];
  if (!file) return;
  STATE.wizardFiles[kind] = file;
  const lbl = document.getElementById(kind === 'resume' ? 'dz-resume-label' : 'dz-linkedin-label');
  if (lbl) lbl.innerHTML = `<span class="tag tag-lime">SELECTED: ${esc(file.name)} (${Math.round(file.size / 1024)} KB)</span>`;
}

// Enable drag-and-drop on both wizard dropzones
['dz-resume', 'dz-linkedin'].forEach((id) => {
  const dz = document.getElementById(id);
  if (!dz) return;
  const kind = id === 'dz-resume' ? 'resume' : 'linkedin';
  dz.addEventListener('dragover', (e) => { e.preventDefault(); dz.classList.add('dragover'); });
  dz.addEventListener('dragleave', () => dz.classList.remove('dragover'));
  dz.addEventListener('drop', (e) => {
    e.preventDefault();
    dz.classList.remove('dragover');
    const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) {
      STATE.wizardFiles[kind] = file;
      const lbl = document.getElementById(kind === 'resume' ? 'dz-resume-label' : 'dz-linkedin-label');
      lbl.innerHTML = `<span class="tag tag-lime">DROPPED: ${esc(file.name)} (${Math.round(file.size / 1024)} KB)</span>`;
    }
  });
});

function populateWizardStep2(defaults, facts) {
  if (!defaults) return;
  const setVal = (id, v) => { const el = document.getElementById(id); if (el && v) el.value = v; };
  setVal('w2-name', defaults.full_name);
  setVal('w2-email', defaults.email);
  setVal('w2-phone', defaults.phone);
  setVal('w2-city', defaults.city);
  setVal('w2-country', defaults.country);
  setVal('w2-linkedin', defaults.linkedin);
  setVal('w2-github', defaults.github);
  setVal('w2-website', defaults.website);
  setVal('w2-roles', defaults.target_roles);
  setVal('w2-loc-pref', defaults.location_pref);
  setVal('w2-salary', defaults.min_salary);
  setVal('w2-dealbreakers', defaults.dealbreakers);
  setVal('w2-work-auth', defaults.work_auth);
  setVal('w2-sponsorship', defaults.sponsorship);
  setVal('w2-notice', defaults.notice_period);
  setVal('w2-eeo', defaults.eeo_default);

  const preview = document.getElementById('wiz-facts-preview');
  if (preview && facts && facts.length) {
    const top = facts.slice(0, 8);
    preview.innerHTML = `
      <div style="font-weight:900;text-transform:uppercase;font-size:0.82rem;margin-bottom:6px;">Auto-Extracted Facts (${facts.length} total — reviewable anytime in 02 // Info &amp; Consent):</div>
      <div style="display:flex;flex-wrap:wrap;gap:6px;">
        ${top.map(f => `<span class="tag ${f.consent_status === 'approved' ? 'tag-lime' : 'tag-yellow'}">${esc(f.fact_key)}: ${esc(String(f.fact_value).slice(0, 36))}</span>`).join('')}
        ${facts.length > 8 ? `<span class="tag tag-black">+${facts.length - 8} more</span>` : ''}
      </div>
    `;
  }
}

async function wizardExtractStep1() {
  toast('Extracting all info from your resume & links...');
  try {
    const payload = {
      linkedin_url: document.getElementById('wiz-linkedin-url').value.trim(),
      github: document.getElementById('wiz-github').value.trim(),
      website: document.getElementById('wiz-website').value.trim(),
      resume_text: document.getElementById('wiz-resume-text').value.trim(),
    };
    if (STATE.wizardFiles.resume) {
      payload.resume_filename = STATE.wizardFiles.resume.name;
      payload.resume_b64 = await fileToBase64(STATE.wizardFiles.resume);
    }
    if (STATE.wizardFiles.linkedin) {
      payload.linkedin_filename = STATE.wizardFiles.linkedin.name;
      payload.linkedin_b64 = await fileToBase64(STATE.wizardFiles.linkedin);
    }
    const res = await api('/api/onboarding/upload-and-extract', { method: 'POST', body: JSON.stringify(payload) });
    populateWizardStep2(res.onboarding.defaults, res.facts);
    document.getElementById('wiz-extract-banner').innerHTML = `
      <div class="banner ok">
        <span>AUTO-EXTRACTED ${(res.facts || []).length} FACT(S) FROM YOUR RESUME &amp; LINKS! Review the pre-filled fields below and click Save.</span>
      </div>
    `;
    toast(`Pulled ${(res.facts || []).length} facts automatically!`);
    goWizardStep(2);
    refreshAll();
  } catch (e) {
    toast(`Extract error: ${e.message}`);
  }
}

async function wizardSaveStep2() {
  try {
    const payload = {
      full_name: document.getElementById('w2-name').value.trim(),
      email: document.getElementById('w2-email').value.trim(),
      phone: document.getElementById('w2-phone').value.trim(),
      city: document.getElementById('w2-city').value.trim(),
      country: document.getElementById('w2-country').value.trim(),
      linkedin: document.getElementById('w2-linkedin').value.trim(),
      github: document.getElementById('w2-github').value.trim(),
      website: document.getElementById('w2-website').value.trim(),
      target_roles: document.getElementById('w2-roles').value.trim(),
      location_pref: document.getElementById('w2-loc-pref').value,
      min_salary: document.getElementById('w2-salary').value.trim(),
      dealbreakers: document.getElementById('w2-dealbreakers').value.trim(),
      work_auth: document.getElementById('w2-work-auth').value,
      sponsorship: document.getElementById('w2-sponsorship').value,
      notice_period: document.getElementById('w2-notice').value.trim(),
      eeo_default: document.getElementById('w2-eeo').value.trim(),
      approve_all_extracted: document.getElementById('w2-approve-all').checked,
    };
    await api('/api/onboarding/complete', { method: 'POST', body: JSON.stringify(payload) });
    toast('Profile, preferences & form defaults saved!');
    goWizardStep(3);
    refreshAll();
  } catch (e) {
    toast(`Save error: ${e.message}`);
  }
}

/* ==================== SINGLE-PROVIDER MAIL CONNECTOR (OAUTH2 + CUSTOM API) ==================== */

const MAIL_PROVIDERS = [
  { id: 'google', name: 'Google', sub: 'Sign in w/ Google (OAuth2 + 2FA)' },
  { id: 'microsoft', name: 'Microsoft', sub: 'Sign in w/ Microsoft (OAuth2 + 2FA)' },
  { id: 'yahoo', name: 'Yahoo', sub: 'Yahoo OAuth2 or 2FA App Pass' },
  { id: 'proton', name: 'Proton', sub: 'Proton Mail Bridge (2FA Native)' },
  { id: 'custom_api', name: 'Custom API', sub: 'Resend / Postmark / REST API' },
];

function selectMailProvider(pid) {
  STATE.selectedProvider = pid;
  renderSingleProviderWidgets();
}

function renderSingleProviderHTML(prefix) {
  const cfg = STATE.mailCfg || {};
  const activeProv = cfg.configured ? cfg.provider : null;
  const sel = STATE.selectedProvider || activeProv || 'google';
  const redir = (cfg.redirect_uris || {});

  let html = '';
  if (activeProv) {
    html += `
      <div class="banner ok" style="margin-bottom:14px;">
        <span>ACTIVE PROVIDER (1 OF 1): <strong>${esc(activeProv.toUpperCase())}</strong> ${cfg.email ? `(${esc(cfg.email)})` : ''} via <strong>${esc(cfg.auth_mode || 'oauth2')}</strong></span>
        <button class="btn btn-sm btn-coral" onclick="disconnectProvider()">Disconnect / Switch</button>
      </div>
    `;
  } else {
    html += `
      <div style="margin-bottom:10px;font-family:var(--font-mono);font-size:0.78rem;font-weight:700;">
        Choose <strong>ONE</strong> mail provider below. Connecting a new provider replaces any prior connection.
      </div>
    `;
  }

  html += `<div class="provider-grid">
    ${MAIL_PROVIDERS.map(p => `
      <button type="button" class="provider-card ${sel === p.id ? 'selected' : ''}" onclick="selectMailProvider('${p.id}')">
        <div class="p-name">${esc(p.name)}</div>
        <div class="p-sub">${esc(p.sub)}</div>
      </button>
    `).join('')}
  </div>`;

  const readyMap = cfg.oauth_ready || {};

  if (sel === 'google') {
    const uri = redir.google || `${location.origin}/api/oauth/google/callback`;
    const isReady = !!readyMap.google;
    html += `
      <div style="border:2px solid #111;padding:18px;background:#FFFDF8;">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:8px;">
          <div style="font-weight:900;font-size:1.05rem;text-transform:uppercase;">Sign in with Google</div>
          <span class="tag ${isReady ? 'tag-lime' : 'tag-yellow'}">${isReady ? '1-CLICK READY' : '1-TIME APP ID NEEDED'}</span>
        </div>
        <p class="mono" style="margin-bottom:16px;color:#444;">Opens a secure Google popup to pick your account and approve Gmail access. Works natively with Google 2FA &amp; Passkeys.</p>
        <button type="button" class="oauth-btn google" onclick="startOAuth('google', '${prefix}')">
          <span style="display:inline-flex;width:24px;height:24px;align-items:center;justify-content:center;background:#111;color:#C8FF2E;font-weight:900;">G</span>
          <span>Continue with Google</span>
        </button>
        <details class="brutal-details" id="${prefix}-google-setup" ${isReady ? '' : ''}>
          <summary>Advanced: Configure Local Google OAuth App ID (One-Time Setup)</summary>
          <div class="mono" style="margin-top:10px;font-size:0.76rem;line-height:1.55;">
            Because Employmaxing runs 100% locally on your computer with no cloud middleman, Google requires an OAuth Client ID once (or set it in <code>employmaxing/oauth_defaults.json</code> for all users):<br/>
            1. <a href="https://console.cloud.google.com/apis/credentials" target="_blank"><strong>Open Google Cloud Credentials &nearr;</strong></a> &rarr; Enable <strong>Gmail API</strong> &rarr; Create <strong>OAuth Client ID (Web App)</strong>.<br/>
            2. Add Redirect URI: <code style="background:#FFE135;padding:2px 6px;">${esc(uri)}</code>
            <button type="button" class="btn btn-sm btn-yellow" style="margin-left:4px;" onclick="copyText('${esc(uri)}')">Copy</button>
          </div>
          <div class="form-grid" style="margin-top:10px;">
            <div>
              <label class="field-label">Google OAuth Client ID</label>
              <input type="text" id="${prefix}-google-cid" value="${esc(cfg.provider === 'google' ? (cfg.client_id || '') : '')}" placeholder="12345-xxxx.apps.googleusercontent.com" />
            </div>
            <div>
              <label class="field-label">Client Secret (Optional for PKCE)</label>
              <input type="password" id="${prefix}-google-csec" placeholder="GOCSPX-... (optional)" />
            </div>
          </div>
          <button type="button" class="btn btn-sm btn-lime" onclick="startOAuth('google', '${prefix}')">Save &amp; Open Google Sign-In Popup &rarr;</button>
        </details>
      </div>
    `;
  } else if (sel === 'microsoft') {
    const uri = redir.microsoft || `${location.origin}/api/oauth/microsoft/callback`;
    const isReady = !!readyMap.microsoft;
    html += `
      <div style="border:2px solid #111;padding:18px;background:#FFFDF8;">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:8px;">
          <div style="font-weight:900;font-size:1.05rem;text-transform:uppercase;">Sign in with Microsoft</div>
          <span class="tag ${isReady ? 'tag-lime' : 'tag-yellow'}">${isReady ? '1-CLICK READY' : '1-TIME APP ID NEEDED'}</span>
        </div>
        <p class="mono" style="margin-bottom:16px;color:#444;">Opens a secure Microsoft popup to pick your Outlook / Office 365 account. Works natively with Microsoft Authenticator &amp; 2FA (no client secret needed).</p>
        <button type="button" class="oauth-btn microsoft" onclick="startOAuth('microsoft', '${prefix}')">
          <span style="display:inline-flex;width:24px;height:24px;align-items:center;justify-content:center;background:#111;color:#FFFFFF;font-weight:900;">M</span>
          <span>Continue with Microsoft</span>
        </button>
        <details class="brutal-details" id="${prefix}-microsoft-setup">
          <summary>Advanced: Configure Local Microsoft App ID (One-Time, No Secret)</summary>
          <div class="mono" style="margin-top:10px;font-size:0.76rem;line-height:1.55;">
            1. <a href="https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade" target="_blank"><strong>Open Azure App Registrations &nearr;</strong></a> &rarr; New Registration (Personal + Work accounts).<br/>
            2. Add Public Client Redirect URI: <code style="background:#FFE135;padding:2px 6px;">${esc(uri)}</code>
            <button type="button" class="btn btn-sm btn-yellow" style="margin-left:4px;" onclick="copyText('${esc(uri)}')">Copy</button><br/>
            3. Add Delegated Permissions: <code>Mail.Read</code>, <code>Mail.Send</code>, <code>User.Read</code> (or bundle Client ID once in <code>employmaxing/oauth_defaults.json</code>).
          </div>
          <div class="form-grid" style="margin-top:10px;">
            <div>
              <label class="field-label">Microsoft Application (Client) ID</label>
              <input type="text" id="${prefix}-microsoft-cid" value="${esc(cfg.provider === 'microsoft' ? (cfg.client_id || '') : '')}" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" />
            </div>
          </div>
          <button type="button" class="btn btn-sm btn-lime" onclick="startOAuth('microsoft', '${prefix}')">Save &amp; Open Microsoft Sign-In Popup &rarr;</button>
        </details>
      </div>
    `;
  } else if (sel === 'yahoo') {
    const uri = redir.yahoo || `${location.origin}/api/oauth/yahoo/callback`;
    const isReady = !!readyMap.yahoo;
    html += `
      <div style="border:2px solid #111;padding:18px;background:#FFFDF8;">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:8px;">
          <div style="font-weight:900;font-size:1.05rem;text-transform:uppercase;">Sign in with Yahoo Mail</div>
          <span class="tag ${isReady ? 'tag-lime' : 'tag-yellow'}">${isReady ? '1-CLICK READY' : 'OAUTH2 / 2FA'}</span>
        </div>
        <p class="mono" style="margin-bottom:14px;color:#444;">Sign in via Yahoo OAuth2 popup or connect using a Yahoo 2FA App Password.</p>
        <button type="button" class="oauth-btn yahoo" onclick="startOAuth('yahoo', '${prefix}')">
          <span style="display:inline-flex;width:24px;height:24px;align-items:center;justify-content:center;background:#111;color:#FFE135;font-weight:900;">Y!</span>
          <span>Continue with Yahoo</span>
        </button>
        <details class="brutal-details" id="${prefix}-yahoo-setup">
          <summary>Advanced: Yahoo OAuth Client ID or 2FA App Password</summary>
          <div class="form-grid" style="margin-top:10px;">
            <div>
              <label class="field-label">Yahoo OAuth Client ID (Redirect: ${esc(uri)})</label>
              <input type="text" id="${prefix}-yahoo-cid" placeholder="dj0yJmk9..." />
            </div>
            <div>
              <label class="field-label">Yahoo OAuth Secret (Optional)</label>
              <input type="password" id="${prefix}-yahoo-csec" placeholder="Optional" />
            </div>
          </div>
          <div style="border-top:2px solid #111;padding-top:10px;margin-top:8px;">
            <div class="form-grid">
              <div>
                <label class="field-label">Or Yahoo Email</label>
                <input type="email" id="${prefix}-yahoo-email" value="${esc(cfg.provider === 'yahoo' ? (cfg.email || '') : '')}" placeholder="you@yahoo.com" />
              </div>
              <div>
                <label class="field-label">Yahoo 2FA App Password</label>
                <input type="password" id="${prefix}-yahoo-pass" placeholder="Generated in Yahoo Account Security" />
              </div>
            </div>
            <button type="button" class="btn btn-sm btn-lime" onclick="saveDirectProvider('yahoo', '${prefix}')">Connect via 2FA App Password</button>
          </div>
        </details>
      </div>
    `;
  } else if (sel === 'proton') {
    html += `
      <div style="border:2px solid #111;padding:16px;background:#FFFDF8;">
        <div style="font-weight:900;text-transform:uppercase;margin-bottom:6px;">Proton Mail (via Local Proton Mail Bridge — 2FA Native)</div>
        <p class="mono" style="margin-bottom:12px;color:#444;">Proton's end-to-end encryption connects locally through Proton Mail Bridge (<code>127.0.0.1:1143</code> / <code>1025</code>) using the Bridge password shown in your Proton Bridge app.</p>
        <div class="form-grid">
          <div>
            <label class="field-label">Proton Email</label>
            <input type="email" id="${prefix}-proton-email" value="${esc(cfg.provider === 'proton' ? (cfg.email || '') : '')}" placeholder="you@proton.me" />
          </div>
          <div>
            <label class="field-label">Proton Bridge Password</label>
            <input type="password" id="${prefix}-proton-pass" placeholder="Paste Bridge password" />
          </div>
        </div>
        <button type="button" class="btn btn-black" onclick="saveDirectProvider('proton', '${prefix}')">Connect Proton Bridge</button>
      </div>
    `;
  } else {
    html += `
      <div style="border:2px solid #111;padding:16px;background:#FFFDF8;">
        <div style="font-weight:900;text-transform:uppercase;margin-bottom:6px;">Custom Mail Provider API (Resend / Postmark / Custom REST)</div>
        <div class="form-grid">
          <div>
            <label class="field-label">API Preset</label>
            <select id="${prefix}-api-preset" onchange="applyCustomApiPreset('${prefix}', this.value)">
              <option value="custom">Custom HTTP REST API</option>
              <option value="resend">Resend (api.resend.com)</option>
              <option value="postmark">Postmark (api.postmarkapp.com)</option>
            </select>
          </div>
          <div>
            <label class="field-label">Sender From Email</label>
            <input type="email" id="${prefix}-api-from" value="${esc(cfg.provider === 'custom_api' ? (cfg.from_email || cfg.email || '') : '')}" placeholder="you@yourdomain.com" />
          </div>
          <div>
            <label class="field-label">Send Endpoint URL (POST JSON)</label>
            <input type="url" id="${prefix}-api-send-url" value="${esc(cfg.provider === 'custom_api' ? (cfg.send_url || '') : '')}" placeholder="https://api.resend.com/emails" />
          </div>
          <div>
            <label class="field-label">Inbox Endpoint URL (Optional GET)</label>
            <input type="url" id="${prefix}-api-inbox-url" value="${esc(cfg.provider === 'custom_api' ? (cfg.inbox_url || '') : '')}" placeholder="https://api.yourmail.com/v1/inbox" />
          </div>
          <div>
            <label class="field-label">API Key / Bearer Token</label>
            <input type="password" id="${prefix}-api-key" placeholder="re_xxxxxxxx..." />
          </div>
          <div>
            <label class="field-label">Auth Header</label>
            <input type="text" id="${prefix}-api-header" value="${esc(cfg.auth_header || 'Authorization')}" />
          </div>
        </div>
        <button type="button" class="btn btn-black" onclick="saveDirectProvider('custom_api', '${prefix}')">Connect Custom Mail API</button>
      </div>
    `;
  }
  return html;
}

function applyCustomApiPreset(prefix, preset) {
  const sendEl = document.getElementById(`${prefix}-api-send-url`);
  const hdrEl = document.getElementById(`${prefix}-api-header`);
  if (preset === 'resend') {
    sendEl.value = 'https://api.resend.com/emails';
    hdrEl.value = 'Authorization';
  } else if (preset === 'postmark') {
    sendEl.value = 'https://api.postmarkapp.com/email';
    hdrEl.value = 'X-Postmark-Server-Token';
  }
}

function renderSingleProviderWidgets() {
  const wizMount = document.getElementById('wiz-mail-mount');
  const mbMount = document.getElementById('mailbox-provider-mount');
  if (wizMount) wizMount.innerHTML = renderSingleProviderHTML('wiz');
  if (mbMount) mbMount.innerHTML = renderSingleProviderHTML('mb');
}

async function startOAuth(provider, prefix) {
  const cidEl = document.getElementById(`${prefix}-${provider}-cid`);
  const csecEl = document.getElementById(`${prefix}-${provider}-csec`);
  const nameEl = document.getElementById(`${prefix}-${provider}-name`);
  const hasReady = !!((STATE.mailCfg && STATE.mailCfg.oauth_ready && STATE.mailCfg.oauth_ready[provider]) || (cidEl && cidEl.value.trim()));

  // Open popup synchronously inside user click handler so browser popup blockers NEVER block it!
  let popup = null;
  if (hasReady) {
    popup = window.open('about:blank', `employmaxing_oauth_${provider}`, 'width=540,height=680');
  }

  try {
    const res = await api(`/api/oauth/${provider}/start`, {
      method: 'POST',
      body: JSON.stringify({
        client_id: cidEl ? cidEl.value.trim() : '',
        client_secret: csecEl ? csecEl.value.trim() : '',
        display_name: nameEl ? nameEl.value.trim() : '',
      }),
    });
    if (popup && !popup.closed) {
      popup.location.href = res.auth_url;
      toast(`Pick your ${provider.toUpperCase()} account in the popup to finish signing in...`);
    } else {
      window.location.href = res.auth_url;
    }
  } catch (e) {
    if (popup && !popup.closed) popup.close();
    if (String(e.message).includes('OAUTH_NOT_REGISTERED')) {
      const det = document.getElementById(`${prefix}-${provider}-setup`);
      if (det) {
        det.open = true;
        det.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
      toast(`Paste a ${provider.toUpperCase()} Client ID once (or bundle it in employmaxing/oauth_defaults.json) to enable instant 1-click popups!`);
    } else {
      toast(e.message);
    }
  }
}

async function saveDirectProvider(provider, prefix) {
  try {
    let payload = { provider };
    if (provider === 'yahoo') {
      payload = {
        provider: 'yahoo',
        auth_mode: 'app_password',
        email: document.getElementById(`${prefix}-yahoo-email`).value.trim(),
        password: document.getElementById(`${prefix}-yahoo-pass`).value,
      };
    } else if (provider === 'proton') {
      payload = {
        provider: 'proton',
        auth_mode: 'proton_bridge',
        email: document.getElementById(`${prefix}-proton-email`).value.trim(),
        password: document.getElementById(`${prefix}-proton-pass`).value,
      };
    } else if (provider === 'custom_api') {
      const preset = document.getElementById(`${prefix}-api-preset`).value;
      payload = {
        provider: 'custom_api',
        auth_mode: 'api_key',
        api_preset: preset,
        from_email: document.getElementById(`${prefix}-api-from`).value.trim(),
        email: document.getElementById(`${prefix}-api-from`).value.trim(),
        send_url: document.getElementById(`${prefix}-api-send-url`).value.trim(),
        inbox_url: document.getElementById(`${prefix}-api-inbox-url`).value.trim(),
        api_key: document.getElementById(`${prefix}-api-key`).value.trim(),
        auth_header: document.getElementById(`${prefix}-api-header`).value.trim() || 'Authorization',
        auth_prefix: preset === 'postmark' ? '' : 'Bearer ',
      };
    }
    await api('/api/mail-config', { method: 'POST', body: JSON.stringify(payload) });
    toast(`Connected ${provider.toUpperCase()} as your active mail provider!`);
    refreshAll();
  } catch (e) {
    toast(`Mail setup error: ${e.message}`);
  }
}

async function disconnectProvider() {
  try {
    await api('/api/mail-config/disconnect', { method: 'POST', body: '{}' });
    toast('Disconnected mail provider. You can now pick another provider.');
    refreshAll();
  } catch (e) { toast(e.message); }
}

/* ==================== CORE DASHBOARD STATE ==================== */

async function refreshAll() {
  try {
    const [onb, dash, factsRes, jobsRes, emailsRes, formsRes, mailCfg, profRes] = await Promise.all([
      api('/api/onboarding/status'),
      api('/api/dashboard'),
      api('/api/facts'),
      api('/api/jobs'),
      api('/api/emails'),
      api('/api/forms'),
      api('/api/mail-config'),
      api('/api/profile'),
    ]);
    STATE.onboarding = onb;
    STATE.mailCfg = mailCfg;
    if (mailCfg.configured && mailCfg.provider) STATE.selectedProvider = mailCfg.provider;
    STATE.dashboard = dash;
    STATE.facts = factsRes.facts || [];
    STATE.jobs = jobsRes.jobs || [];
    STATE.emails = emailsRes.emails || [];
    STATE.forms = formsRes.forms || [];

    const obBadge = document.getElementById('badge-onboarding');
    if (obBadge) {
      obBadge.textContent = onb.completed ? 'DONE' : 'SETUP';
      obBadge.className = `nav-badge ${onb.completed ? '' : 'alert'}`;
    }
    populateWizardStep2(onb.defaults, STATE.facts);

    // Auto-route brand-new users directly to 00 // Get Started on first visit!
    if (!STATE.initialRouted) {
      STATE.initialRouted = true;
      const params = new URLSearchParams(location.search);
      if (params.get('oauth') === 'ok') {
        switchView('mailbox');
        toast(`Connected ${(params.get('provider') || '').toUpperCase()} via OAuth2!`);
      } else if (!onb.completed && (STATE.facts.length === 0 && STATE.jobs.length === 0)) {
        switchView('onboarding');
      }
    }

    renderDashboard(dash);
    renderFacts();
    renderMasterProfile(profRes);
    renderJobs();
    renderMailConfig(mailCfg);
    renderSingleProviderWidgets();
    renderEmails();
    renderForms();
  } catch (err) {
    toast(`Sync error: ${err.message}`);
  }
}

function jumpToFacts(status) {
  switchView('consent');
  const btn = document.querySelector(`#fact-filter-tabs .subtab[data-filter="${status}"]`);
  filterFacts(status, btn);
}

function jumpToJobs(flt) {
  switchView('jobs');
  const btn = document.querySelector(`#job-filter-tabs .subtab[data-jfilter="${flt}"]`);
  filterJobs(flt, btn);
}

function jumpToEmails(flt) {
  switchView('mailbox');
  const btn = document.querySelector(`#email-filter-tabs .subtab[data-efilter="${flt}"]`);
  filterEmails(flt, btn);
}

function renderDashboard(dash) {
  const c = dash.counts || {};
  const potentialCount = Math.max(0, (c.jobs_total ?? 0) - (c.jobs_applied ?? 0));
  document.getElementById('footer-datadir').textContent = `DATA: ${dash.data_dir}`;
  document.getElementById('kpi-approved-facts').textContent = c.facts_approved ?? 0;
  document.getElementById('kpi-pending-facts').textContent = c.facts_pending_consent ?? 0;
  document.getElementById('kpi-potential-jobs').textContent = potentialCount;
  document.getElementById('kpi-applied-jobs').textContent = c.jobs_applied ?? 0;
  document.getElementById('kpi-interviews').textContent = c.jobs_interviews ?? 0;
  document.getElementById('kpi-sent').textContent = c.emails_sent ?? 0;
  document.getElementById('kpi-replies').textContent = c.inbox_replies ?? 0;
  document.getElementById('kpi-forms').textContent = c.forms_pending ?? 0;

  document.getElementById('badge-pending-facts').textContent = c.facts_pending_consent ?? 0;
  document.getElementById('badge-jobs').textContent = c.jobs_total ?? 0;
  document.getElementById('badge-mail').textContent = (c.emails_pending_approval ?? 0) + (c.inbox_replies ?? 0);
  document.getElementById('badge-forms').textContent = c.forms_pending ?? 0;

  const alerts = [];
  if (STATE.onboarding && !STATE.onboarding.completed) {
    alerts.push(`
      <div class="banner warn">
        <span>FIRST-TIME SETUP: Drop your resume, verify auto-pulled details, and connect your OAuth2 mail account in 2 minutes (zero CLI).</span>
        <button class="btn btn-sm btn-black" onclick="switchView('onboarding')">Start Guided Setup</button>
      </div>
    `);
  }
  if (c.facts_pending_consent > 0) {
    alerts.push(`
      <div class="banner warn">
        <span>TRANSPARENCY NOTICE: ${c.facts_pending_consent} discovered fact(s) are waiting for your consent before use.</span>
        <button class="btn btn-sm btn-black" onclick="switchView('consent')">Review Now</button>
      </div>
    `);
  }
  if (c.interview_invites > 0) {
    alerts.push(`
      <div class="banner ok">
        <span>INTERVIEW SIGNAL DETECTED: ${c.interview_invites} high-priority recruiter/interview reply(s) found in your mailbox!</span>
        <button class="btn btn-sm btn-black" onclick="switchView('mailbox')">Open Mailbox</button>
      </div>
    `);
  }
  document.getElementById('dashboard-alerts').innerHTML = alerts.join('');

  const events = dash.recent_events || [];
  const tbody = document.getElementById('events-tbody');
  if (!events.length) {
    tbody.innerHTML = '<tr><td colspan="3"><div class="empty-state">No events yet. Start in 00 // Get Started to upload your resume and connect your mail provider.</div></td></tr>';
    return;
  }
  tbody.innerHTML = events.map(e => `
    <tr>
      <td class="mono">${esc(e.created_at)}</td>
      <td><span class="tag tag-yellow">${esc(e.event_type)}</span></td>
      <td>${esc(e.summary)}</td>
    </tr>
  `).join('');
}

function filterFacts(status, btn) {
  STATE.factFilter = status;
  document.querySelectorAll('#fact-filter-tabs .subtab').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderFacts();
}

function renderFacts() {
  const rows = STATE.facts.filter(f => STATE.factFilter === 'all' || f.consent_status === STATE.factFilter);
  const tbody = document.getElementById('facts-tbody');
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="6"><div class="empty-state">No profile facts in this filter yet. Upload your resume in 00 // Get Started or run discovery above.</div></td></tr>';
    return;
  }
  tbody.innerHTML = rows.map(f => {
    const tagCls = f.consent_status === 'approved' ? 'tag-lime' : (f.consent_status === 'pending_review' ? 'tag-yellow' : 'tag-coral');
    return `
      <tr>
        <td class="mono">#${f.id}</td>
        <td>
          <span class="tag tag-black">${esc(f.category)}</span>
          <div class="mono" style="margin-top:4px;font-weight:700;">${esc(f.fact_key)}</div>
        </td>
        <td><input type="text" id="fact-val-${f.id}" value="${esc(f.fact_value)}" /></td>
        <td class="mono">
          <div><strong>SRC:</strong> ${esc(f.source)}</div>
          <div><strong>USE:</strong> ${esc(f.planned_usage)}</div>
          ${f.source_url ? `<a href="${esc(f.source_url)}" target="_blank">source link &nearr;</a>` : ''}
        </td>
        <td><span class="tag ${tagCls}">${esc(f.consent_status)}</span></td>
        <td>
          <div class="btn-row">
            <button class="btn btn-sm btn-lime" onclick="updateFact(${f.id}, 'approved')">Approve</button>
            <button class="btn btn-sm btn-coral" onclick="updateFact(${f.id}, 'rejected')">Exclude</button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

async function updateFact(id, consent_status) {
  const valInput = document.getElementById(`fact-val-${id}`);
  try {
    await api(`/api/facts/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ consent_status, fact_value: valInput ? valInput.value : undefined }),
    });
    toast(`Fact #${id} marked ${consent_status.toUpperCase()}`);
    refreshAll();
  } catch (e) { toast(e.message); }
}

async function approveAllFacts() {
  try {
    const res = await api('/api/facts/approve-all', { method: 'POST', body: '{}' });
    toast(`Approved ${res.approved_count} pending fact(s)!`);
    refreshAll();
  } catch (e) { toast(e.message); }
}

async function runEnrichment() {
  toast('Uploading & discovering facts...');
  try {
    const payload = {
      github: document.getElementById('enrich-github').value.trim(),
      website: document.getElementById('enrich-website').value.trim(),
    };
    const rInput = document.getElementById('enrich-resume-file');
    if (rInput && rInput.files && rInput.files[0]) {
      payload.resume_filename = rInput.files[0].name;
      payload.resume_b64 = await fileToBase64(rInput.files[0]);
    }
    const lInput = document.getElementById('enrich-linkedin-file');
    if (lInput && lInput.files && lInput.files[0]) {
      payload.linkedin_filename = lInput.files[0].name;
      payload.linkedin_b64 = await fileToBase64(lInput.files[0]);
    }
    const res = await api('/api/enrich', { method: 'POST', body: JSON.stringify(payload) });
    toast(`Discovery complete! ${res.pending_review_count} fact(s) queued for consent.`);
    refreshAll();
  } catch (e) { toast(`Enrich failed: ${e.message}`); }
}

async function addCustomFact() {
  try {
    await api('/api/facts', {
      method: 'POST',
      body: JSON.stringify({
        category: document.getElementById('new-fact-cat').value,
        fact_key: document.getElementById('new-fact-key').value.trim(),
        fact_value: document.getElementById('new-fact-val').value.trim(),
        planned_usage: document.getElementById('new-fact-usage').value.trim(),
        consent_status: 'approved',
      }),
    });
    document.getElementById('new-fact-key').value = '';
    document.getElementById('new-fact-val').value = '';
    toast('Custom approved fact saved!');
    refreshAll();
  } catch (e) { toast(e.message); }
}

function renderMasterProfile(prof) {
  document.getElementById('profile-approved-badge').textContent = `${prof.approved_count || 0} APPROVED FACTS`;
  const byCat = prof.approved_by_category || {};
  const keys = Object.keys(byCat);
  const body = document.getElementById('master-profile-body');
  if (!keys.length) {
    body.innerHTML = '<div class="empty-state">No approved profile facts yet. Complete 00 // Get Started to assemble your Master Profile.</div>';
  } else {
    body.innerHTML = keys.map(cat => `
      <div style="margin-bottom:14px;">
        <div style="margin-bottom:6px;"><span class="tag tag-black">${esc(cat.replace(/_/g, ' '))}</span></div>
        ${byCat[cat].map(f => `<div class="mono" style="padding:6px 8px;border:2px solid #111;margin-bottom:5px;background:#FFFDF8;"><strong>${esc(f.fact_key)}:</strong> ${esc(f.fact_value)}</div>`).join('')}
      </div>
    `).join('');
  }
  if (prof.linkedin_audit_md) {
    document.getElementById('li-audit-output').innerHTML = `<pre class="code-block">${esc(prof.linkedin_audit_md)}</pre>`;
  }
}

async function runLinkedInAudit() {
  toast('Running 12-point LinkedIn vs. Resume Discrepancy Audit...');
  try {
    const payload = { linkedin_text: document.getElementById('li-audit-text').value.trim() };
    const fInput = document.getElementById('li-audit-file');
    if (fInput && fInput.files && fInput.files[0]) {
      payload.linkedin_filename = fInput.files[0].name;
      payload.linkedin_b64 = await fileToBase64(fInput.files[0]);
    }
    const res = await api('/api/linkedin-audit', { method: 'POST', body: JSON.stringify(payload) });
    const a = res.audit;
    const fx = a.turnkey_fixes;
    let html = `
      <div class="banner ${a.discrepancy_count > 0 ? 'danger' : 'ok'}">
        <span>SEO SCORE: ${a.credibility_and_seo_score}/100 // DISCREPANCIES: ${a.discrepancy_count} // TURN-OFFS: ${a.turn_off_count}</span>
      </div>
    `;
    if (a.discrepancies.length) {
      html += `<div style="margin-bottom:12px;"><strong>CRITICAL DISCREPANCIES:</strong>${a.discrepancies.map(d => `<div style="border:2px solid #111;background:#FFE5E5;padding:8px;margin-top:6px;"><strong>[${esc(d.severity)}] ${esc(d.type)}:</strong> ${esc(d.detail)}<div class="mono" style="margin-top:4px;">FIX: ${esc(d.fix)}</div></div>`).join('')}</div>`;
    }
    if (a.turn_offs.length) {
      html += `<div style="margin-bottom:12px;"><strong>RECRUITER TURN-OFFS:</strong>${a.turn_offs.map(t => `<div style="border:2px solid #111;background:#FFF4B8;padding:8px;margin-top:6px;"><strong>[${esc(t.severity)}] ${esc(t.category)}:</strong> ${esc(t.detail)}<div class="mono" style="margin-top:4px;">FIX: ${esc(t.fix)}</div></div>`).join('')}</div>`;
    }
    html += `
      <div style="margin-bottom:12px;">
        <strong>COPY-PASTEABLE 220-CHAR HEADLINES:</strong>
        ${fx.headlines_220_char.map(h => `<div style="display:flex;justify-content:space-between;gap:8px;align-items:center;border:2px solid #111;padding:8px;margin-top:6px;background:#FFF;"><span class="mono">${esc(h)}</span><button class="btn btn-sm btn-lime" onclick="copyText(${JSON.stringify(h)})">Copy</button></div>`).join('')}
      </div>
      <div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
          <strong>REWRITTEN ABOUT SECTION:</strong>
          <button class="btn btn-sm btn-lime" onclick="copyText(${JSON.stringify(fx.rewritten_about_section)})">Copy About</button>
        </div>
        <pre class="code-block">${esc(fx.rewritten_about_section)}</pre>
      </div>
    `;
    document.getElementById('li-audit-output').innerHTML = html;
    toast(`Audit done: ${a.discrepancy_count} discrepancies & ${a.turn_off_count} turn-offs surfaced.`);
  } catch (e) { toast(`Audit error: ${e.message}`); }
}

function copyText(txt) {
  navigator.clipboard.writeText(txt).then(() => toast('Copied to clipboard!'));
}

async function addJob(buildFormAfter = false) {
  try {
    const res = await api('/api/jobs', {
      method: 'POST',
      body: JSON.stringify({
        company: document.getElementById('job-company').value.trim(),
        role: document.getElementById('job-role').value.trim(),
        url: document.getElementById('job-url').value.trim(),
        location: document.getElementById('job-location').value.trim(),
        days_old: parseInt(document.getElementById('job-days').value || '1', 10),
        stage: document.getElementById('job-stage').value,
        posting_text: document.getElementById('job-posting').value.trim(),
        notes: document.getElementById('job-notes').value.trim(),
      }),
    });
    toast(`Added ${res.job.company} (${res.job.priority_tier})`);
    ['job-company', 'job-role', 'job-url', 'job-location', 'job-posting', 'job-notes'].forEach(id => {
      document.getElementById(id).value = '';
    });
    if (buildFormAfter) await planFormForJob(res.id);
    else refreshAll();
  } catch (e) { toast(e.message); }
}

async function loadDorks() {
  const roles = encodeURIComponent(document.getElementById('dork-roles').value.trim());
  const loc = encodeURIComponent(document.getElementById('dork-loc').value.trim());
  try {
    const data = await api(`/api/dorks?roles=${roles}&location=${loc}&hours=48`);
    document.getElementById('dorks-output').innerHTML = data.queries.map(q => `
      <div style="border:2px solid #111;padding:8px 10px;margin-bottom:8px;background:#FFFDF8;display:flex;justify-content:space-between;align-items:center;gap:10px;">
        <div>
          <div style="font-weight:800;font-size:0.85rem;">${esc(q.board)}</div>
          <div class="mono" style="font-size:0.74rem;color:#444;">${esc(q.query)}</div>
        </div>
        <a class="btn btn-sm btn-lime" href="${esc(q.fresh_google_url)}" target="_blank">Open &lt;48h &nearr;</a>
      </div>
    `).join('');
  } catch (e) { toast(e.message); }
}

const STAGES = ['Discovered', 'Saved', 'Tailored', 'Applied', 'Phone Screen', 'Technical', 'Onsite / Final', 'Offer', 'Accepted', 'Rejected', 'Withdrawn'];
const POTENTIAL_STAGES = new Set(['Discovered', 'Saved', 'Tailored']);
const INTERVIEW_STAGES = new Set(['Phone Screen', 'Technical', 'Onsite / Final', 'Offer', 'Accepted']);

function filterJobs(flt, btn) {
  STATE.jobFilter = flt;
  document.querySelectorAll('#job-filter-tabs .subtab').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderJobs();
}

function renderJobs() {
  const allJobs = STATE.jobs || [];
  const potentialJobs = allJobs.filter(j => POTENTIAL_STAGES.has(j.stage));
  const appliedJobs = allJobs.filter(j => !POTENTIAL_STAGES.has(j.stage));
  const interviewJobs = allJobs.filter(j => INTERVIEW_STAGES.has(j.stage));

  document.getElementById('cnt-jobs-all').textContent = allJobs.length;
  document.getElementById('cnt-jobs-potential').textContent = potentialJobs.length;
  document.getElementById('cnt-jobs-applied').textContent = appliedJobs.length;
  document.getElementById('cnt-jobs-interviews').textContent = interviewJobs.length;

  const visible = STATE.jobFilter === 'potential'
    ? potentialJobs
    : STATE.jobFilter === 'applied'
      ? appliedJobs
      : STATE.jobFilter === 'interviews'
        ? interviewJobs
        : allJobs;

  const tbody = document.getElementById('jobs-tbody');
  if (!visible.length) {
    tbody.innerHTML = '<tr><td colspan="5"><div class="empty-state">No jobs in this bucket yet. Add a custom job above or adjust filter tabs.</div></td></tr>';
    return;
  }
  tbody.innerHTML = visible.map(j => {
    const ghostCls = j.ghost_risk === 'HIGH' ? 'tag-coral' : (j.ghost_risk === 'LOW' ? 'tag-lime' : 'tag-yellow');
    const stageOpts = STAGES.map(s => `<option value="${s}" ${j.stage === s ? 'selected' : ''}>${s}</option>`).join('');
    return `
      <tr>
        <td>
          <strong>${esc(j.company)}</strong> — ${esc(j.role)}
          <div class="mono" style="margin-top:4px;font-size:0.74rem;">ID: ${esc(j.id)} ${j.url ? `| <a href="${esc(j.url)}" target="_blank">Posting &nearr;</a>` : ''}</div>
        </td>
        <td>
          <div><span class="tag tag-black">${esc(j.priority_tier)}</span></div>
          <div style="margin-top:4px;"><span class="tag ${ghostCls}">GHOST: ${esc(j.ghost_risk)}</span></div>
        </td>
        <td><select onchange="updateJobStage('${esc(j.id)}', this.value)">${stageOpts}</select></td>
        <td class="mono"><div>${esc(j.ats_type || 'auto')}</div><div>${esc(j.salary_band || '-')}</div></td>
        <td>
          <div class="btn-row">
            <button class="btn btn-sm btn-yellow" onclick="inspectJob('${esc(j.id)}')">Inspect App</button>
            <button class="btn btn-sm btn-blue" onclick="planFormForJob('${esc(j.id)}')">Form Plan</button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

async function updateJobStage(id, stage) {
  try {
    await api(`/api/jobs/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ stage }) });
    toast(`Updated ${id} -> ${stage}`);
    refreshAll();
  } catch (e) { toast(e.message); }
}

async function inspectJob(id) {
  try {
    const res = await api(`/api/jobs/${encodeURIComponent(id)}/artifacts`);
    const card = document.getElementById('job-inspector-card');
    card.style.display = 'block';
    document.getElementById('inspector-title').textContent = `Custom Application // ${res.job.company} — ${res.job.role}`;
    document.getElementById('inspector-downloads').innerHTML = (res.downloads || [])
      .map(d => `<a class="btn btn-sm btn-lime" href="${esc(d.url)}" target="_blank">Download ${esc(d.name)}</a>`)
      .join('');

    let html = '';
    if (res.resume_audit) {
      const sc = res.resume_audit.total_score;
      html += `<div class="banner ${sc >= 85 ? 'ok' : 'warn'}"><span>EMPIRICAL RESUME SCORE: ${sc}/100 (${res.resume_audit.ready_to_ship ? 'READY TO SHIP' : 'NEEDS POLISH'})</span></div>`;
    }
    const entries = Object.entries(res.artifacts || {});
    if (!entries.length) {
      html += '<div class="empty-state">No tailored artifacts saved in this job folder yet.</div>';
    } else {
      html += entries.map(([fname, text]) => `
        <div style="margin-bottom:14px;">
          <div style="margin-bottom:6px;"><span class="tag tag-black">${esc(fname)}</span></div>
          <pre class="code-block">${esc(text)}</pre>
        </div>
      `).join('');
    }
    document.getElementById('inspector-body').innerHTML = html;
    card.scrollIntoView({ behavior: 'smooth' });
  } catch (e) { toast(e.message); }
}

async function planFormForJob(job_id) {
  try {
    await api('/api/forms/plan', { method: 'POST', body: JSON.stringify({ job_id }) });
    toast(`Created knockout-safe form plan for ${job_id}`);
    await refreshAll();
    switchView('forms');
  } catch (e) { toast(e.message); }
}

function renderMailConfig(cfg) {
  const badge = document.getElementById('mail-cfg-status');
  if (!badge) return;
  badge.textContent = cfg.configured ? `${(cfg.provider || '').toUpperCase()} CONNECTED` : 'NOT CONNECTED';
  badge.className = `tag ${cfg.configured ? 'tag-lime' : 'tag-coral'}`;
}

async function queueEmail() {
  try {
    const res = await api('/api/emails/queue', {
      method: 'POST',
      body: JSON.stringify({
        recipient_email: document.getElementById('mail-to').value.trim(),
        recipient_name: document.getElementById('mail-name').value.trim(),
        subject: document.getElementById('mail-subject').value.trim(),
        body: document.getElementById('mail-body').value.trim(),
        job_id: document.getElementById('mail-job-id').value.trim(),
      }),
    });
    toast(`Queued #${res.email_id} — Score ${res.mail_score}/100 | MX: ${res.mx.gateway}`);
    refreshAll();
  } catch (e) { toast(e.message); }
}

async function approveEmail(id) {
  try {
    await api(`/api/emails/${id}/approve`, { method: 'POST', body: '{}' });
    toast(`Email #${id} approved for sending.`);
    refreshAll();
  } catch (e) { toast(e.message); }
}

async function sendApprovedNow(dry_run) {
  try {
    const res = await api('/api/emails/send', { method: 'POST', body: JSON.stringify({ dry_run }) });
    toast(res.message || `${dry_run ? 'DRY-RUN' : 'SENT'}: ${(res.sent || []).length} email(s).`);
    refreshAll();
  } catch (e) { toast(e.message); }
}

async function scanInboxNow() {
  toast('Scanning connected mailbox for recruiter & interview replies...');
  try {
    const res = await api('/api/emails/scan-inbox', { method: 'POST', body: JSON.stringify({ days: 14 }) });
    toast(res.message || `Inbox scanned: ${(res.new_replies || []).length} job message(s) found.`);
    refreshAll();
  } catch (e) { toast(e.message); }
}

function filterEmails(flt, btn) {
  STATE.emailFilter = flt;
  document.querySelectorAll('#email-filter-tabs .subtab').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderEmails();
}

function renderEmails() {
  const rows = STATE.emails.filter(e => {
    if (STATE.emailFilter === 'all') return true;
    if (STATE.emailFilter === 'pending_approval') return e.status === 'pending_approval';
    return e.direction === STATE.emailFilter;
  });
  const tbody = document.getElementById('emails-tbody');
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="5"><div class="empty-state">No emails in this view yet.</div></td></tr>';
    return;
  }
  tbody.innerHTML = rows.map(e => {
    const clsTag = ['interview_invite', 'recruiter_screen', 'offer'].includes(e.classification) ? 'tag-lime' : (e.classification === 'rejection' ? 'tag-coral' : 'tag-blue');
    const dirTag = e.direction === 'inbound_reply' ? 'tag-violet' : (e.status === 'sent' ? 'tag-lime' : 'tag-yellow');
    return `
      <tr>
        <td class="mono">#${e.id}<div style="margin-top:4px;"><span class="tag ${dirTag}">${esc(e.direction)}</span></div></td>
        <td>
          <strong>${esc(e.direction === 'inbound_reply' ? e.sender_email : e.recipient_email)}</strong>
          <div>${esc(e.subject)}</div>
          <div class="mono" style="font-size:0.72rem;color:#555;">${esc(e.sent_or_received_at)}</div>
        </td>
        <td class="mono">
          <span class="tag ${clsTag}">${esc(e.classification)}</span>
          ${e.mail_score != null ? `<div style="margin-top:4px;">SCORE: <strong>${e.mail_score}/100</strong></div>` : ''}
          ${e.mx_gateway ? `<div>MX: ${esc(e.mx_gateway)}</div>` : ''}
        </td>
        <td>
          <div class="mono" style="max-width:340px;white-space:pre-wrap;font-size:0.76rem;">${esc((e.body || '').slice(0, 260))}</div>
          ${(e.facts_used || []).length ? `<div style="margin-top:6px;"><span class="tag tag-black">FACTS USED: #${e.facts_used.join(', #')}</span></div>` : ''}
        </td>
        <td>
          <span class="tag">${esc(e.status)}</span>
          ${e.status === 'pending_approval' ? `<div style="margin-top:6px;"><button class="btn btn-sm btn-lime" onclick="approveEmail(${e.id})">Approve</button></div>` : ''}
        </td>
      </tr>
    `;
  }).join('');
}

async function createFormPlan() {
  const job_id = document.getElementById('form-job-id').value.trim();
  const form_url = document.getElementById('form-url').value.trim();
  if (!job_id) return toast('Enter a Job ID first.');
  try {
    await api('/api/forms/plan', { method: 'POST', body: JSON.stringify({ job_id, form_url }) });
    toast('Transparent form plan built!');
    refreshAll();
  } catch (e) { toast(e.message); }
}

async function executeFormCDP(id) {
  toast(`Executing CDP auto-fill for Form #${id}...`);
  try {
    const res = await api(`/api/forms/${id}/execute`, { method: 'POST', body: '{}' });
    toast(res.message || res.note || `Form #${id}: ${res.status}`);
    refreshAll();
  } catch (e) { toast(e.message); }
}

function renderForms() {
  const container = document.getElementById('forms-container');
  if (!STATE.forms.length) {
    container.innerHTML = '<div class="card"><div class="empty-state">No ATS form plans created yet. Pick a tracked job and click "Form Plan".</div></div>';
    return;
  }
  container.innerHTML = STATE.forms.map(fm => `
    <div class="card">
      <div class="card-header">
        <div>
          <h2 class="card-title">Form #${fm.id} // ${esc(fm.job_id)} <span class="tag tag-blue">${esc(fm.ats_type)}</span></h2>
          <div class="mono" style="margin-top:4px;font-size:0.76rem;">${esc(fm.form_url)} | STATUS: <strong>${esc(fm.status)}</strong> | FACTS USED: #${(fm.facts_used || []).join(', #') || 'none'}</div>
        </div>
        <button class="btn btn-black" onclick="executeFormCDP(${fm.id})">Execute CDP Auto-Fill</button>
      </div>
      ${(fm.knockout_warnings || []).map(w => `<div class="banner danger"><span>${esc(w)}</span></div>`).join('')}
      <div class="table-wrap">
        <table>
          <thead><tr><th>Field</th><th>Planned Answer</th><th>Type / Fact Source</th></tr></thead>
          <tbody>
            ${(fm.field_plan || []).map(fld => `
              <tr>
                <td><strong>${esc(fld.field)}</strong></td>
                <td class="mono">${esc(fld.value)}</td>
                <td class="mono">${esc(fld.type)} ${fld.fact_id ? `<span class="tag tag-lime">FACT #${fld.fact_id}</span>` : ''}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
      ${(fm.files_attached || []).length ? `<div style="margin-top:12px;" class="mono"><strong>AUTO-ATTACHED FILES (CDP DOM.setFileInputFiles):</strong> ${fm.files_attached.map(f => `<span class="tag tag-yellow">${esc(f.label)}: ${esc(f.path)}</span>`).join(' ')}</div>` : ''}
      ${fm.screenshot_path ? `<img class="screenshot-preview" src="/api/files/screenshots/${esc(fm.screenshot_path.split('/').pop())}" alt="Form Review Screenshot" />` : ''}
    </div>
  `).join('');
}

refreshAll();
