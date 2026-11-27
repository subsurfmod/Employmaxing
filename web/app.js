/* Employmaxing v1.5 — Guided Zero-CLI Onboarding + Universal Autofill + Single-Provider Mail Controller (GPL-3.0) */
let STATE = {
  onboarding: null,
  mailCfg: null,
  selectedProvider: 'thunderbird',
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
  browserCdpAvailable: false,
  detectedBrowser: '',
  formResults: {},
};

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(() => el.classList.remove('show'), 4500);
}

function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function safeUrl(u) {
  const s = String(u || '').trim();
  if (!s) return '';
  if (/^https?:\/\//i.test(s) || s.startsWith('/')) return s;
  return 'https://' + s;
}

function setInlineResult(elId, kind, html) {
  const el = document.getElementById(elId);
  if (!el) return;
  if (!html) {
    el.innerHTML = '';
    return;
  }
  el.innerHTML = `<div class="inline-result ${kind}">${html}</div>`;
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
  { id: 'thunderbird', name: 'Thunderbird ★', sub: 'Easiest! Zero API Setup (Gmail/Outlook 2FA)' },
  { id: 'google', name: 'Google', sub: 'Gmail API OAuth2' },
  { id: 'microsoft', name: 'Microsoft', sub: 'Outlook Graph OAuth2' },
  { id: 'yahoo', name: 'Yahoo', sub: 'Yahoo OAuth2 / 2FA' },
  { id: 'proton', name: 'Proton', sub: 'Proton Mail Bridge' },
  { id: 'custom_api', name: 'Custom API', sub: 'Resend / Postmark / REST' },
];

function selectMailProvider(pid) {
  STATE.selectedProvider = pid;
  renderSingleProviderWidgets();
}

function renderSingleProviderHTML(prefix) {
  const cfg = STATE.mailCfg || {};
  const activeProv = cfg.configured ? cfg.provider : null;
  const sel = STATE.selectedProvider || activeProv || 'thunderbird';
  const redir = (cfg.redirect_uris || {});
  const tb = cfg.thunderbird || {};

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
        Choose <strong>ONE</strong> mail provider below. <strong>Thunderbird</strong> is the simplest — sign into Gmail, Outlook, Yahoo, or Proton inside Thunderbird once, then click Connect below!
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

  if (sel === 'thunderbird') {
    const accounts = tb.accounts || [];
    const bridge = tb.bridge || {};
    const bridgeOnline = !!bridge.online;
    const bridgeBadge = bridgeOnline
      ? `<span class="tag tag-lime">AUTO-SEND BRIDGE: ONLINE &#9679; (100% HANDS-FREE)</span>`
      : (tb.addon_installed_in_profile
          ? `<span class="tag tag-yellow">ADD-ON COPIED — RESTART THUNDERBIRD TO ACTIVATE</span>`
          : `<span class="tag tag-yellow">ADD-ON OPTIONAL (ENABLES 100% HANDS-FREE SEND)</span>`);

    const accountPicker = accounts.length
      ? `
        <div style="margin-bottom:12px;">
          <label class="field-label">Step 3: Pick Your Signed-In Thunderbird Account (1 Active Account)</label>
          <select id="${prefix}-tb-account">
            ${accounts.map(a => `<option value="${esc(a.email)}" ${cfg.email === a.email ? 'selected' : ''}>${esc(a.email)} ${a.hostname ? `(${esc(a.hostname)})` : ''}</option>`).join('')}
          </select>
        </div>
      `
      : `
        <div style="border:2px solid #111;background:#FFF4B8;padding:10px 12px;margin-bottom:12px;" class="mono">
          <strong>Step 1:</strong> ${tb.installed ? 'Open <strong>Mozilla Thunderbird</strong> and sign in to your Gmail / Outlook / Yahoo / Proton account once (official 2FA login popups built in!).' : `Install Mozilla Thunderbird: <code>${esc(tb.install_hint || 'sudo dnf install thunderbird')}</code> <button type="button" class="btn btn-sm btn-yellow" onclick="copyText(${JSON.stringify(tb.install_hint || 'sudo dnf install thunderbird')})">Copy</button>`}
        </div>
      `;

    html += `
      <div style="border:2px solid #111;padding:18px;background:#FFFDF8;">
        <div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:8px;margin-bottom:10px;">
          <div style="font-weight:900;font-size:1.05rem;text-transform:uppercase;">Mozilla Thunderbird (Zero API Keys / Zero Passwords)</div>
          ${bridgeBadge}
        </div>
        <p class="mono" style="margin-bottom:14px;color:#444;">
          Sign in to Gmail, Outlook, Yahoo, or Proton inside Thunderbird once. Employmaxing automatically reads your inbox replies in &lt;0.2s and — with the tiny 1-file Bridge Add-on below — sends approved emails <strong>100% automatically in the background</strong>!
        </p>

        ${accountPicker}

        <div style="border:2px solid #111;background:${bridgeOnline ? '#ECFFB3' : '#F4EFE6'};padding:14px;margin-bottom:14px;">
          <div style="font-weight:900;text-transform:uppercase;font-size:0.86rem;margin-bottom:6px;">
            ${bridgeOnline ? '✓ Step 2 Complete: Auto-Send Bridge Add-on Is Live!' : 'Step 2 (30 Seconds): Install the Thunderbird Auto-Send Add-on (v1.5)'}
          </div>
          ${bridgeOnline ? `
            <div class="mono" style="font-size:0.78rem;">
              Thunderbird Companion Add-on v${esc(bridge.version || '1.5.0')} is actively synced (last heartbeat ${esc(bridge.last_seen_seconds ?? 0)}s ago). Clicking <strong>Send Approved Mail</strong> will now send automatically with zero extra clicks!
            </div>
          ` : `
            <div class="mono" style="font-size:0.77rem;line-height:1.6;margin-bottom:10px;">
              <strong>Recommended (Guaranteed on Thunderbird 115 / 128+):</strong><br/>
              1. Click <strong>Download employmaxing-bridge.xpi</strong> below.<br/>
              2. Open Thunderbird &rarr; <strong>&#9776; Menu &rarr; Add-ons and Themes &rarr; &#9881; Gear Icon &rarr; Install Add-on From File...</strong> &rarr; pick <code>employmaxing-bridge.xpi</code> &rarr; click <strong>Add</strong>.<br/>
              3. Click the <strong>EMPLOY</strong> button in Thunderbird's top toolbar &rarr; click <strong>Test &amp; Sync Now</strong>. The badge above will turn green immediately!
            </div>
            <div class="btn-row">
              <a class="btn btn-sm btn-lime" href="/api/thunderbird/addon.xpi" download="employmaxing-bridge.xpi">1. Download employmaxing-bridge.xpi</a>
              <button type="button" class="btn btn-sm btn-black" onclick="installThunderbirdAddon()">Copy Into Profile Folder</button>
            </div>
            <div class="mono" style="font-size:0.72rem;color:#555;margin-top:6px;">
              Note: Thunderbird 115+ disables folder-copied add-ons by default until you install via Add-ons Manager above.
            </div>
          `}
        </div>

        <div class="btn-row">
          <button type="button" class="btn btn-lime" onclick="connectThunderbird('${prefix}')">Auto-Detect &amp; Connect Thunderbird</button>
          <button type="button" class="btn" onclick="refreshAll()">Re-Scan Status</button>
        </div>
      </div>
    `;
  } else if (sel === 'google') {
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
        if (!det.querySelector('.oauth-hint-box')) {
          const hint = document.createElement('div');
          hint.className = 'inline-result warn oauth-hint-box';
          hint.innerHTML = `<strong>Direct ${provider.toUpperCase()} OAuth needs a 1-time Client ID</strong> (because Employmaxing runs 100% locally with no cloud server). Don't want to create an API key? <button type="button" class="btn btn-sm btn-lime" style="margin-left:6px;" onclick="selectMailProvider('thunderbird')">Use Thunderbird ★ Instead (Zero API Setup)</button>`;
          det.prepend(hint);
        }
        det.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
      toast(`Paste a ${provider.toUpperCase()} Client ID once — or click Thunderbird ★ for zero-API setup!`);
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

async function installThunderbirdAddon() {
  try {
    const res = await api('/api/thunderbird/install-addon', { method: 'POST', body: '{}' });
    toast(res.message || 'Add-on installed!');
    refreshAll();
  } catch (e) { toast(e.message); }
}

async function connectThunderbird(prefix) {
  try {
    const accEl = document.getElementById(`${prefix}-tb-account`);
    const email = accEl ? accEl.value : '';
    const res = await api('/api/thunderbird/connect', {
      method: 'POST',
      body: JSON.stringify({ email }),
    });
    const info = res.thunderbird || {};
    toast(`Connected Thunderbird (${res.email || 'local profile'}) — ${info.inbox_files ? info.inbox_files.length : 0} inbox file(s) synced!`);
    refreshAll();
  } catch (e) { toast(e.message); }
}

async function markEmailSent(id) {
  try {
    await api(`/api/emails/${id}/mark-sent`, { method: 'POST', body: '{}' });
    toast(`Confirmed email #${id} as SENT!`);
    refreshAll();
  } catch (e) { toast(e.message); }
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
    STATE.browserCdpAvailable = !!formsRes.browser_cdp_available;
    STATE.detectedBrowser = formsRes.detected_browser || '';

    const obBadge = document.getElementById('badge-onboarding');
    if (obBadge) {
      obBadge.textContent = onb.completed ? 'DONE' : 'SETUP';
      obBadge.className = `nav-badge ${onb.completed ? '' : 'alert'}`;
    }
    populateWizardStep2(onb.defaults, STATE.facts);
    populateJobDropdowns();
    renderNextStepBar();

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
          ${f.source_url ? `<a href="${esc(safeUrl(f.source_url))}" target="_blank" rel="noopener noreferrer">source link &nearr;</a>` : ''}
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

async function fetchJobUrl() {
  const rawUrl = document.getElementById('job-url').value.trim();
  if (!rawUrl) {
    setInlineResult('job-fetch-result', 'warn', 'Paste a job posting URL first (e.g. https://jobs.ashbyhq.com/... or Greenhouse/Lever URL).');
    return toast('Paste a job posting URL first.');
  }
  const url = safeUrl(rawUrl);
  document.getElementById('job-url').value = url;
  setInlineResult('job-fetch-result', 'warn', 'Fetching job posting metadata & description...');
  try {
    const res = await api('/api/jobs/fetch-url', { method: 'POST', body: JSON.stringify({ url }) });
    if (res.company) document.getElementById('job-company').value = res.company;
    if (res.role) document.getElementById('job-role').value = res.role;
    if (res.location) document.getElementById('job-location').value = res.location;
    if (res.posting_text) document.getElementById('job-posting').value = res.posting_text;
    setInlineResult('job-fetch-result', 'ok', `Fetched <strong>${esc(res.company || 'Company')}</strong> — ${esc(res.role || 'Role')} (${esc((res.ats_type || 'web').toUpperCase())}). Review fields below and click <strong>Add &amp; Build Form Plan</strong>.`);
    toast(`Fetched ${res.company} — ${res.role}!`);
  } catch (e) {
    setInlineResult('job-fetch-result', 'err', `Could not auto-fetch URL (${esc(e.message)}). Some sites block automated scrapers — you can still fill Company, Role &amp; paste the Job Description below.`);
    toast(`Fetch failed: ${e.message}`);
  }
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
        <a class="btn btn-sm btn-lime" href="${esc(safeUrl(q.fresh_google_url))}" target="_blank" rel="noopener noreferrer">Open &lt;48h &nearr;</a>
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
          <div class="mono" style="margin-top:4px;font-size:0.74rem;">ID: ${esc(j.id)} ${j.url ? `| <a href="${esc(safeUrl(j.url))}" target="_blank" rel="noopener noreferrer">Posting &nearr;</a>` : ''}</div>
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
    const dlHtml = (res.downloads || [])
      .map(d => `<a class="btn btn-sm btn-lime" href="${esc(d.url)}" target="_blank">Download ${esc(d.name)}</a>`)
      .join('');
    document.getElementById('inspector-downloads').innerHTML = `
      <button class="btn btn-sm btn-blue" onclick="exportJobDocs('${esc(id)}')">Compile ATS PDF &amp; DOCX</button>
      ${dlHtml}
    `;

    let html = '';
    if (res.resume_audit) {
      const sc = res.resume_audit.total_score;
      const missing = (res.resume_audit.breakdown && res.resume_audit.breakdown.jd_keywords_25 && res.resume_audit.breakdown.jd_keywords_25.missing) || [];
      html += `
        <div class="banner ${sc >= 85 ? 'ok' : 'warn'}">
          <span>EMPIRICAL RESUME SCORE: ${sc}/100 (${res.resume_audit.ready_to_ship ? 'READY TO SHIP' : 'NEEDS POLISH <85'})</span>
        </div>
      `;
      if (missing.length) {
        html += `<div style="margin-bottom:10px;" class="mono"><strong>MISSING JD KEYWORDS TO WEAVE IN (IF TRUTHFUL):</strong> ${missing.slice(0, 10).map(k => `<span class="tag tag-yellow">${esc(k)}</span>`).join(' ')}</div>`;
      }
      if ((res.resume_audit.priority_fixes || []).length) {
        html += `<div style="border:2px solid #111;background:#FFFDF0;padding:10px;margin-bottom:12px;" class="mono"><strong>TOP FIXES:</strong><br/>${res.resume_audit.priority_fixes.slice(0, 5).map((f, i) => `${i + 1}. ${esc(f)}`).join('<br/>')}</div>`;
      }
    }

    const resText = (res.artifacts && res.artifacts['resume.md']) || '';
    html += `
      <div style="margin-bottom:16px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
          <span class="tag tag-black">LIVE RESUME EDITOR (resume.md)</span>
          <div class="btn-row">
            <button class="btn btn-sm btn-lime" onclick="saveAndScoreJobResume('${esc(id)}')">Save, Auto-Fix &amp; Re-Score</button>
            <button class="btn btn-sm btn-blue" onclick="exportJobDocs('${esc(id)}')">Compile PDF &amp; DOCX</button>
          </div>
        </div>
        <textarea id="live-resume-editor" style="min-height:240px;">${esc(resText)}</textarea>
      </div>
    `;

    const otherEntries = Object.entries(res.artifacts || {}).filter(([k]) => k !== 'resume.md');
    if (otherEntries.length) {
      html += otherEntries.map(([fname, text]) => `
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

async function saveAndScoreJobResume(id) {
  const ed = document.getElementById('live-resume-editor');
  try {
    const res = await api(`/api/jobs/${encodeURIComponent(id)}/resume`, {
      method: 'POST',
      body: JSON.stringify({ content: ed ? ed.value : undefined, autofix: true }),
    });
    toast(`Resume saved & scored: ${res.audit.total_score}/100!`);
    inspectJob(id);
  } catch (e) { toast(e.message); }
}

async function exportJobDocs(id) {
  toast('Compiling ATS single-column PDF & DOCX...');
  try {
    const res = await api(`/api/jobs/${encodeURIComponent(id)}/export`, { method: 'POST', body: '{}' });
    toast(`Compiled ${(res.exported || []).length} ATS file(s)!`);
    inspectJob(id);
  } catch (e) { toast(e.message); }
}

async function findHiringManagerEmail() {
  try {
    const res = await api('/api/email-find', {
      method: 'POST',
      body: JSON.stringify({
        first: document.getElementById('ef-first').value.trim(),
        last: document.getElementById('ef-last').value.trim(),
        domain: document.getElementById('ef-domain').value.trim(),
      }),
    });
    const mx = res.mx || {};
    document.getElementById('ef-output').innerHTML = `
      <div class="mono" style="margin-bottom:6px;"><strong>MX GATEWAY:</strong> <span class="tag ${mx.valid_mx ? 'tag-lime' : 'tag-coral'}">${esc(mx.gateway)}</span> — ${esc(mx.deliverability_advice)}</div>
      <div class="btn-row">
        ${(res.permutations || []).map(p => `<button type="button" class="btn btn-sm btn-yellow" onclick="document.getElementById('mail-to').value='${esc(p.email)}';toast('Selected ${esc(p.email)}');">${esc(p.email)}</button>`).join('')}
      </div>
    `;
  } catch (e) { toast(e.message); }
}

async function runFollowupCheck() {
  toast('Checking inbox & due Day 3 / Day 7 follow-ups...');
  try {
    const res = await api('/api/automation/run-now', { method: 'POST', body: '{}' });
    const fup = (res.followups && res.followups.queued_followups) || [];
    toast(`Check complete! Drafted ${fup.length} due follow-up(s) into Outbox Pending.`);
    refreshAll();
  } catch (e) { toast(e.message); }
}

function renderNextStepBar() {
  const bar = document.getElementById('next-step-bar');
  if (!bar) return;
  const onb = STATE.onboarding || {};
  const mailCfg = STATE.mailCfg || {};
  const pendingFacts = (STATE.facts || []).filter(f => f.consent_status === 'pending_review').length;
  const jobs = STATE.jobs || [];
  const forms = STATE.forms || [];

  let label = 'YOUR NEXT STEP';
  let text = '';
  let btnLabel = '';
  let btnAction = '';

  if (!onb.has_resume && (STATE.facts || []).length === 0) {
    label = 'STEP 1 OF 4 // START HERE';
    text = 'Upload your resume so Employmaxing can auto-fill your profile, preferences, and application forms.';
    btnLabel = 'Go to Step 1: Upload Resume →';
    btnAction = "switchView('onboarding');goWizardStep(1);";
  } else if (pendingFacts > 0) {
    label = 'STEP 2 OF 4 // APPROVE YOUR INFO';
    text = `${pendingFacts} extracted fact(s) are waiting for your OK before they can be used in resumes or forms.`;
    btnLabel = `Review & Approve (${pendingFacts}) →`;
    btnAction = "jumpToFacts('pending_review');";
  } else if (!mailCfg.configured) {
    label = 'STEP 3 OF 4 // CONNECT MAIL';
    text = 'Connect ONE mail provider so Employmaxing can track recruiter replies and send approved outreach. Thunderbird is fastest!';
    btnLabel = 'Connect Mail Provider →';
    btnAction = "switchView('onboarding');goWizardStep(3);";
  } else if (jobs.length === 0) {
    label = 'STEP 4 OF 4 // ADD FIRST TARGET JOB';
    text = 'Paste any Greenhouse, Lever, Ashby, or company job URL to score it, tailor your resume, and generate 1-click autofill.';
    btnLabel = 'Add a Target Job →';
    btnAction = "switchView('jobs');";
  } else if (forms.length === 0) {
    label = 'READY TO APPLY';
    text = `You have ${jobs.length} tracked job(s). Build a 1-click Autofill Plan to fill forms in Firefox, Chrome, Edge, or Safari.`;
    btnLabel = 'Build Autofill Plan →';
    btnAction = "switchView('forms');";
  } else {
    label = 'ALL SYSTEMS READY';
    text = `${jobs.length} tracked job(s) · ${forms.length} autofill plan(s) ready · ${mailCfg.provider ? mailCfg.provider.toUpperCase() + ' connected' : 'Mail ready'}.`;
    btnLabel = 'Open Autofill Forms →';
    btnAction = "switchView('forms');";
  }

  bar.innerHTML = `
    <div>
      <div class="ns-label">${label}</div>
      <div class="ns-text">${text}</div>
    </div>
    <button type="button" class="btn btn-sm btn-lime" onclick="${btnAction}">${btnLabel}</button>
  `;
}

function populateJobDropdowns() {
  const jobs = STATE.jobs || [];
  ['form-job-id', 'mail-job-id'].forEach((id) => {
    const sel = document.getElementById(id);
    if (!sel || sel.tagName !== 'SELECT') return;
    const prev = sel.value;
    const placeholder = id === 'form-job-id'
      ? (jobs.length ? '— Select a tracked job —' : '— No tracked jobs yet (add one in 04 // Jobs & Apps) —')
      : '— No linked job (optional) —';
    sel.innerHTML = `<option value="">${placeholder}</option>` + jobs.map(j =>
      `<option value="${esc(j.id)}">${esc(j.company)} — ${esc(j.role)} (${esc(j.stage)})</option>`
    ).join('');
    if (prev && jobs.some(j => j.id === prev)) sel.value = prev;
    else if (id === 'form-job-id' && jobs.length === 1) sel.value = jobs[0].id;
  });
}

async function launchCDPBrowser() {
  setInlineResult('form-action-result', 'warn', 'Checking for Chrome / Chromium / Brave / Edge on port 9222...');
  toast('Checking for Chrome CDP browser...');
  try {
    const res = await api('/api/forms/launch-browser', { method: 'POST', body: '{}' });
    if (res.ready) {
      setInlineResult('form-action-result', 'ok', `<strong>Chrome CDP Window READY!</strong> (${esc(res.browser || 'Connected on port 9222')}). Click <strong>Run Chrome CDP Auto-Fill</strong> on any form plan below.`);
      toast('Automated Chrome CDP window is READY!');
    } else {
      setInlineResult('form-action-result', 'warn', `<strong>Chrome CDP unavailable:</strong> ${esc(res.error || 'Could not launch Chrome')}<br/><strong>Good news:</strong> You do NOT need Chrome! Use the green <strong>⚡ DRAG TO BOOKMARKS: FILL FORM</strong> button on any form card below — it works in Firefox, Safari, Edge, and Chrome.`);
      toast(res.error || 'Chrome not found — use Universal Bookmarklet!');
    }
  } catch (e) {
    setInlineResult('form-action-result', 'err', `Launch error: ${esc(e.message)}`);
    toast(e.message);
  }
}

async function planFormForJob(job_id) {
  try {
    await api('/api/forms/plan', { method: 'POST', body: JSON.stringify({ job_id }) });
    toast(`Created autofill plan for ${job_id}`);
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
    setInlineResult('mail-action-result', 'ok', `Queued Email #${res.email_id} (Score: <strong>${res.mail_score}/100</strong> | MX: <strong>${esc(res.mx.gateway)}</strong>). Click <strong>Approve</strong> in the table below, then click <strong>Send Approved Mail</strong>.`);
    toast(`Queued #${res.email_id} — Score ${res.mail_score}/100 | MX: ${res.mx.gateway}`);
    refreshAll();
  } catch (e) {
    setInlineResult('mail-action-result', 'err', `Queue error: ${esc(e.message)}`);
    toast(e.message);
  }
}

async function approveEmail(id) {
  try {
    await api(`/api/emails/${id}/approve`, { method: 'POST', body: '{}' });
    toast(`Email #${id} approved for sending.`);
    refreshAll();
  } catch (e) { toast(e.message); }
}

async function sendApprovedNow(dry_run) {
  setInlineResult('mail-action-result', 'warn', dry_run ? 'Running dry-run on approved emails...' : 'Sending approved emails via your connected provider...');
  try {
    const res = await api('/api/emails/send', { method: 'POST', body: JSON.stringify({ dry_run }) });
    const msg = res.message || `${dry_run ? 'DRY-RUN' : 'SENT'}: ${(res.sent || []).length} email(s).`;
    setInlineResult('mail-action-result', (res.errors && res.errors.length) ? 'err' : 'ok', esc(msg));
    toast(msg);
    refreshAll();
  } catch (e) {
    setInlineResult('mail-action-result', 'err', `Send error: ${esc(e.message)}`);
    toast(e.message);
  }
}

async function scanInboxNow() {
  setInlineResult('mail-action-result', 'warn', 'Scanning connected mailbox for recruiter & interview replies...');
  toast('Scanning connected mailbox for recruiter & interview replies...');
  try {
    const res = await api('/api/emails/scan-inbox', { method: 'POST', body: JSON.stringify({ days: 14 }) });
    const msg = res.message || `Inbox scanned: ${(res.new_replies || []).length} job message(s) found.`;
    setInlineResult('mail-action-result', res.status === 'not_configured' ? 'warn' : 'ok', esc(msg));
    toast(msg);
    refreshAll();
  } catch (e) {
    setInlineResult('mail-action-result', 'err', `Inbox scan error: ${esc(e.message)}`);
    toast(e.message);
  }
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
          ${e.status === 'opened_in_thunderbird' ? `<div style="margin-top:6px;"><button class="btn btn-sm btn-lime" onclick="markEmailSent(${e.id})">Mark Sent</button></div>` : ''}
        </td>
      </tr>
    `;
  }).join('');
}

async function createFormPlan() {
  const job_id = document.getElementById('form-job-id').value.trim();
  const form_url = document.getElementById('form-url').value.trim();
  if (!job_id) {
    setInlineResult('form-action-result', 'warn', 'Pick a tracked job from the dropdown first (or add one in <strong>04 // Jobs &amp; Apps</strong>).');
    return toast('Select a tracked job first.');
  }
  try {
    const res = await api('/api/forms/plan', { method: 'POST', body: JSON.stringify({ job_id, form_url }) });
    setInlineResult('form-action-result', 'ok', `Built Autofill Plan <strong>#${res.id}</strong> (${(res.field_plan || []).length} approved fields). Drag the green <strong>⚡ FILL FORM</strong> button below to your bookmarks bar, open the job page, and click it!`);
    toast('Autofill plan ready!');
    refreshAll();
  } catch (e) {
    setInlineResult('form-action-result', 'err', `Could not build form plan: ${esc(e.message)}`);
    toast(e.message);
  }
}

function copyFormScript(id) {
  const fm = (STATE.forms || []).find(f => f.id === id);
  if (!fm || !fm.autofill_script) return toast('No autofill script available for this plan.');
  copyText(fm.autofill_script);
  STATE.formResults[id] = {
    kind: 'ok',
    html: '<strong>Autofill Script Copied!</strong> Open the job application page &rarr; press <code>F12</code> (Console tab) &rarr; paste &amp; press <code>Enter</code>. All fields fill immediately!',
  };
  renderForms();
}

async function executeFormCDP(id) {
  STATE.formResults[id] = { kind: 'warn', html: `Running Chrome CDP auto-fill for Form #${id}...` };
  renderForms();
  try {
    const res = await api(`/api/forms/${id}/execute`, { method: 'POST', body: '{}' });
    if (res.status === 'filled_pending_submit') {
      const filled = (res.filled_fields || []).length;
      const missed = (res.missed_fields || []).length;
      STATE.formResults[id] = {
        kind: 'ok',
        html: `<strong>Chrome CDP Filled ${filled} field(s)</strong>${missed ? ` (${missed} manual/missed)` : ''}! Review the screenshot below &amp; your Chrome tab before clicking Submit.`,
      };
    } else {
      STATE.formResults[id] = {
        kind: 'warn',
        html: `<strong>Chrome CDP unavailable:</strong> ${esc(res.message || res.status)}<br/><strong>Use Step 2 above instead:</strong> Drag the green <strong>⚡ FILL FORM</strong> bookmarklet to your bookmarks bar (or click <strong>Copy Console Script</strong>) — works in Firefox, Safari, Edge &amp; Chrome!`,
      };
    }
    toast(res.message || res.note || `Form #${id}: ${res.status}`);
    await refreshAll();
  } catch (e) {
    STATE.formResults[id] = { kind: 'err', html: `<strong>CDP Error:</strong> ${esc(e.message)}` };
    renderForms();
    toast(e.message);
  }
}

function renderForms() {
  const cdpBanner = document.getElementById('form-cdp-status');
  if (cdpBanner) {
    if (STATE.browserCdpAvailable) {
      cdpBanner.innerHTML = `<div class="banner ok"><span><strong>2 AUTOFILL MODES READY:</strong> (1) Universal Bookmarklet (works in Firefox/Chrome/Edge/Safari) AND (2) Chrome CDP Auto-Fill (${esc(STATE.detectedBrowser)}).</span></div>`;
    } else {
      cdpBanner.innerHTML = `<div class="banner warn"><span><strong>FIREFOX / UNIVERSAL MODE ACTIVE:</strong> No Chrome/Chromium binary detected for CDP — use the <strong>1-Click Universal Autofill Bookmarklet</strong> or <strong>Copy Console Script</strong> on each form card below (works in Firefox, Safari, Edge &amp; Chrome!).</span></div>`;
    }
  }

  const container = document.getElementById('forms-container');
  if (!STATE.forms.length) {
    container.innerHTML = '<div class="card"><div class="empty-state">No autofill plans created yet. Pick a tracked job above (or add one in <strong>04 // Jobs &amp; Apps</strong>) and click <strong>Build Autofill Plan</strong>.</div></div>';
    return;
  }
  container.innerHTML = STATE.forms.map(fm => {
    const openUrl = safeUrl(fm.form_url);
    const resBox = STATE.formResults[fm.id];
    return `
    <div class="card">
      <div class="card-header">
        <div>
          <h2 class="card-title">Form #${fm.id} // ${esc(fm.job_id)} <span class="tag tag-blue">${esc(fm.ats_type)}</span></h2>
          <div class="mono" style="margin-top:4px;font-size:0.76rem;">
            ${openUrl ? `<a href="${esc(openUrl)}" target="_blank" rel="noopener noreferrer">${esc(openUrl)} &nearr;</a>` : '<em>No application URL saved</em>'}
            | STATUS: <strong>${esc(fm.status)}</strong>
            | FACTS USED: #${(fm.facts_used || []).join(', #') || 'none'}
          </div>
        </div>
      </div>

      <div style="border:2px solid #111;background:#FFFDF0;padding:12px 14px;margin-bottom:14px;">
        <div class="mono" style="font-weight:900;margin-bottom:8px;text-transform:uppercase;">How to Autofill This Form (Works in Firefox, Chrome, Edge &amp; Safari):</div>
        <div class="btn-row">
          ${openUrl ? `<a class="btn btn-sm btn-yellow" href="${esc(openUrl)}" target="_blank" rel="noopener noreferrer">1. Open Application Page &nearr;</a>` : ''}
          ${fm.autofill_bookmarklet ? `<a class="bookmarklet-pill" href="${esc(fm.autofill_bookmarklet)}" onclick="event.preventDefault();toast('Drag this green button onto your Bookmarks Bar, then click it on the job application page!');" title="Drag onto your browser Bookmarks Bar">&#9889; 2. Drag to Bookmarks: Fill #${fm.id}</a>` : ''}
          <button type="button" class="btn btn-sm btn-blue" onclick="copyFormScript(${fm.id})">Or Copy Console Autofill Script</button>
          <button type="button" class="btn btn-sm btn-black" onclick="executeFormCDP(${fm.id})">${STATE.browserCdpAvailable ? '3. Run Chrome CDP Auto-Fill' : 'Try Chrome CDP (Chrome Only)'}</button>
        </div>
        <div class="mono" style="font-size:0.72rem;color:#444;margin-top:8px;">
          Tip: Drag the dashed green button to your browser Bookmarks Bar once, open the job form, and click the bookmark to fill all fields instantly! Or click <strong>Copy</strong> next to any field below.
        </div>
      </div>

      ${resBox ? `<div class="inline-result ${resBox.kind}">${resBox.html}</div>` : ''}
      ${(fm.knockout_warnings || []).map(w => `<div class="banner danger"><span>${esc(w)}</span></div>`).join('')}

      <div class="table-wrap">
        <table>
          <thead><tr><th>Field</th><th>Planned Answer</th><th>Source</th><th>Quick Copy</th></tr></thead>
          <tbody>
            ${(fm.field_plan || []).length ? (fm.field_plan || []).map(fld => `
              <tr>
                <td><strong>${esc(fld.field)}</strong></td>
                <td class="mono">${esc(fld.value)}</td>
                <td class="mono">${esc(fld.type)} ${fld.fact_id ? `<span class="tag tag-lime">FACT #${fld.fact_id}</span>` : ''}</td>
                <td><button type="button" class="btn btn-sm btn-lime" onclick="copyText(${JSON.stringify(String(fld.value || ''))})">Copy</button></td>
              </tr>
            `).join('') : '<tr><td colspan="4"><div class="empty-state">No approved profile facts found yet. Complete <strong>00 // Get Started</strong> or approve facts in <strong>02 // Info &amp; Consent</strong>, then rebuild this plan.</div></td></tr>'}
          </tbody>
        </table>
      </div>
      ${(fm.files_attached || []).length ? `<div style="margin-top:12px;" class="mono"><strong>FILES TO ATTACH:</strong> ${fm.files_attached.map(f => `<span class="tag tag-yellow">${esc(f.label)}: ${esc(f.path)}</span> <button type="button" class="btn btn-sm" onclick="copyText(${JSON.stringify(f.path)})">Copy Path</button>`).join(' ')}</div>` : ''}
      ${fm.screenshot_path ? `<img class="screenshot-preview" src="/api/files/screenshots/${esc(fm.screenshot_path.split('/').pop())}" alt="Form Review Screenshot" />` : ''}
    </div>
  `;
  }).join('');
}

refreshAll();

// Live-detect Thunderbird Auto-Send Bridge coming ONLINE while user is on Step 3 of Setup
setInterval(async () => {
  const onStep3 = document.getElementById('view-onboarding')?.classList.contains('active')
    && document.getElementById('wizard-step-3')?.classList.contains('active');
  const onMail = document.getElementById('view-mailbox')?.classList.contains('active');
  if (!onStep3 && !onMail) return;
  try {
    const mc = await api('/api/mail-config');
    const prevOnline = !!(STATE.mailCfg && STATE.mailCfg.thunderbird && STATE.mailCfg.thunderbird.bridge && STATE.mailCfg.thunderbird.bridge.online);
    const nowOnline = !!(mc.thunderbird && mc.thunderbird.bridge && mc.thunderbird.bridge.online);
    if (nowOnline !== prevOnline) {
      STATE.mailCfg = mc;
      renderSingleProviderWidgets();
      if (nowOnline) toast('Thunderbird Auto-Send Bridge is now ONLINE (100% hands-free)!');
    }
  } catch (_) {}
}, 6000);
