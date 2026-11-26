/* Employmaxing — Local Non-CLI Dashboard Controller (GPL-3.0) */
let STATE = {
  dashboard: null,
  facts: [],
  factFilter: 'all',
  jobs: [],
  emails: [],
  emailFilter: 'all',
  forms: [],
};

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(() => el.classList.remove('show'), 3600);
}

function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `HTTP ${res.status}`);
  }
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

async function refreshAll() {
  try {
    const [dash, factsRes, jobsRes, emailsRes, formsRes, mailCfg, profRes] = await Promise.all([
      api('/api/dashboard'),
      api('/api/facts'),
      api('/api/jobs'),
      api('/api/emails'),
      api('/api/forms'),
      api('/api/mail-config'),
      api('/api/profile'),
    ]);
    STATE.dashboard = dash;
    STATE.facts = factsRes.facts || [];
    STATE.jobs = jobsRes.jobs || [];
    STATE.emails = emailsRes.emails || [];
    STATE.forms = formsRes.forms || [];

    renderDashboard(dash);
    renderFacts();
    renderMasterProfile(profRes);
    renderJobs();
    renderMailConfig(mailCfg);
    renderEmails();
    renderForms();
  } catch (err) {
    toast(`Sync error: ${err.message}`);
  }
}

function renderDashboard(dash) {
  const c = dash.counts || {};
  document.getElementById('footer-datadir').textContent = `DATA: ${dash.data_dir}`;
  document.getElementById('kpi-approved-facts').textContent = c.facts_approved ?? 0;
  document.getElementById('kpi-pending-facts').textContent = c.facts_pending_consent ?? 0;
  document.getElementById('kpi-jobs').textContent = c.jobs_total ?? 0;
  document.getElementById('kpi-interviews').textContent = c.jobs_interviews ?? 0;
  document.getElementById('kpi-sent').textContent = c.emails_sent ?? 0;
  document.getElementById('kpi-replies').textContent = c.inbox_replies ?? 0;
  document.getElementById('kpi-forms').textContent = c.forms_pending ?? 0;

  document.getElementById('badge-pending-facts').textContent = c.facts_pending_consent ?? 0;
  document.getElementById('badge-jobs').textContent = c.jobs_total ?? 0;
  document.getElementById('badge-mail').textContent = (c.emails_pending_approval ?? 0) + (c.inbox_replies ?? 0);
  document.getElementById('badge-forms').textContent = c.forms_pending ?? 0;

  const alerts = [];
  if (c.facts_pending_consent > 0) {
    alerts.push(`
      <div class="banner warn">
        <span>TRANSPARENCY NOTICE: ${c.facts_pending_consent} discovered fact(s) are waiting for your consent before they will be used in any resume, email, or form fill.</span>
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
  if (c.emails_pending_approval > 0) {
    alerts.push(`
      <div class="banner warn">
        <span>OUTBOX QUEUE: ${c.emails_pending_approval} outbound email(s) awaiting your approval before sending.</span>
        <button class="btn btn-sm btn-black" onclick="switchView('mailbox')">Inspect Outbox</button>
      </div>
    `);
  }
  document.getElementById('dashboard-alerts').innerHTML = alerts.join('');

  const events = dash.recent_events || [];
  const tbody = document.getElementById('events-tbody');
  if (!events.length) {
    tbody.innerHTML = '<tr><td colspan="3"><div class="empty-state">No events logged yet. Start in 02 // Info &amp; Consent to ingest your resume or GitHub profile.</div></td></tr>';
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
    tbody.innerHTML = '<tr><td colspan="6"><div class="empty-state">No profile facts in this filter yet. Run Transparent Discovery above.</div></td></tr>';
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
        <td>
          <input type="text" id="fact-val-${f.id}" value="${esc(f.fact_value)}" />
        </td>
        <td class="mono">
          <div><strong>SRC:</strong> ${esc(f.source)}</div>
          <div><strong>USE:</strong> ${esc(f.planned_usage)}</div>
          ${f.source_url ? `<a href="${esc(f.source_url)}" target="_blank">source link ↗</a>` : ''}
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
  const payload = {
    resume_path: document.getElementById('enrich-resume-path').value.trim(),
    resume_text: document.getElementById('enrich-resume-text').value.trim(),
    linkedin_path: document.getElementById('enrich-linkedin-path').value.trim(),
    github: document.getElementById('enrich-github').value.trim(),
    website: document.getElementById('enrich-website').value.trim(),
  };
  toast('Discovering facts from sources...');
  try {
    const res = await api('/api/enrich', { method: 'POST', body: JSON.stringify(payload) });
    toast(`Discovery complete! ${res.pending_review_count} fact(s) queued for your consent.`);
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
    body.innerHTML = '<div class="empty-state">No approved profile facts yet. Approve facts in 02 // Info &amp; Consent to assemble your Master Profile.</div>';
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
    const res = await api('/api/linkedin-audit', {
      method: 'POST',
      body: JSON.stringify({
        linkedin_path: document.getElementById('li-audit-path').value.trim(),
        linkedin_text: document.getElementById('li-audit-text').value.trim(),
      }),
    });
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

async function addJob() {
  try {
    const res = await api('/api/jobs', {
      method: 'POST',
      body: JSON.stringify({
        company: document.getElementById('job-company').value.trim(),
        role: document.getElementById('job-role').value.trim(),
        url: document.getElementById('job-url').value.trim(),
        days_old: parseInt(document.getElementById('job-days').value || '1', 10),
        posting_text: document.getElementById('job-posting').value.trim(),
      }),
    });
    toast(`Added ${res.job.company} (${res.job.priority_tier})`);
    document.getElementById('job-company').value = '';
    document.getElementById('job-role').value = '';
    document.getElementById('job-url').value = '';
    document.getElementById('job-posting').value = '';
    refreshAll();
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
        <a class="btn btn-sm btn-lime" href="${esc(q.fresh_google_url)}" target="_blank">Open &lt;48h ↗</a>
      </div>
    `).join('');
  } catch (e) { toast(e.message); }
}

const STAGES = ['Discovered', 'Saved', 'Tailored', 'Applied', 'Phone Screen', 'Technical', 'Onsite / Final', 'Offer', 'Accepted', 'Rejected', 'Withdrawn'];

function renderJobs() {
  const tbody = document.getElementById('jobs-tbody');
  if (!STATE.jobs.length) {
    tbody.innerHTML = '<tr><td colspan="5"><div class="empty-state">No jobs tracked yet. Add a potential job above or run Employmaxing job-search.</div></td></tr>';
    return;
  }
  tbody.innerHTML = STATE.jobs.map(j => {
    const ghostCls = j.ghost_risk === 'HIGH' ? 'tag-coral' : (j.ghost_risk === 'LOW' ? 'tag-lime' : 'tag-yellow');
    const stageOpts = STAGES.map(s => `<option value="${s}" ${j.stage === s ? 'selected' : ''}>${s}</option>`).join('');
    return `
      <tr>
        <td>
          <strong>${esc(j.company)}</strong> — ${esc(j.role)}
          <div class="mono" style="margin-top:4px;font-size:0.74rem;">ID: ${esc(j.id)} ${j.url ? `| <a href="${esc(j.url)}" target="_blank">Posting ↗</a>` : ''}</div>
        </td>
        <td>
          <div><span class="tag tag-black">${esc(j.priority_tier)}</span></div>
          <div style="margin-top:4px;"><span class="tag ${ghostCls}">GHOST: ${esc(j.ghost_risk)}</span></div>
        </td>
        <td>
          <select onchange="updateJobStage('${esc(j.id)}', this.value)">${stageOpts}</select>
        </td>
        <td class="mono">
          <div>${esc(j.ats_type || 'auto')}</div>
          <div>${esc(j.salary_band || '-')}</div>
        </td>
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
      html += '<div class="empty-state">No tailored artifacts saved in this job folder yet. Run `/employmaxing:autopilot` to generate resume, cover letter, and outreach.</div>';
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
  badge.textContent = cfg.configured ? `CONNECTED (${cfg.email})` : 'NOT CONFIGURED';
  badge.className = `tag ${cfg.configured ? 'tag-lime' : 'tag-coral'}`;
  if (cfg.email) document.getElementById('cfg-email').value = cfg.email;
  if (cfg.provider) document.getElementById('cfg-provider').value = cfg.provider;
  if (cfg.display_name) document.getElementById('cfg-display').value = cfg.display_name;
}

async function saveMailConfigUI() {
  try {
    await api('/api/mail-config', {
      method: 'POST',
      body: JSON.stringify({
        provider: document.getElementById('cfg-provider').value,
        email: document.getElementById('cfg-email').value.trim(),
        password: document.getElementById('cfg-pass').value,
        display_name: document.getElementById('cfg-display').value.trim(),
      }),
    });
    document.getElementById('cfg-pass').value = '';
    toast('Mailbox credentials saved locally (chmod 600).');
    refreshAll();
  } catch (e) { toast(e.message); }
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
  toast('Scanning IMAP inbox for job replies...');
  try {
    const res = await api('/api/emails/scan-inbox', { method: 'POST', body: JSON.stringify({ days: 14 }) });
    toast(res.message || `Inbox scanned: ${(res.new_replies || []).length} job message(s) found.`);
    refreshAll();
  } catch (e) { toast(e.message); }
}

function filterEmails(flt, btn) {
  STATE.emailFilter = flt;
  btn.parentElement.querySelectorAll('.subtab').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
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
