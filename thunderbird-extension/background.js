/* Employmaxing Auto-Send Bridge for Mozilla Thunderbird (GPL-3.0)
 * Polls strictly local http://127.0.0.1:8787 for user-approved plain-text emails
 * and sends them hands-free through Thunderbird's official compose.sendMessage API.
 */

const DEFAULT_BASE_URL = "http://127.0.0.1:8787";
const BRIDGE_HEADER = "employmaxing-tb-v1";
let isProcessing = false;
let lastInboxSyncTs = 0;

async function collectRecentInboxMessages(force = false) {
  const now = Date.now();
  if (!force && now - lastInboxSyncTs < 60000) return [];
  if (!messenger.messages || !messenger.messages.query) return [];
  lastInboxSyncTs = now;
  try {
    const fromDate = new Date(now - 7 * 86400 * 1000);
    const page = await messenger.messages.query({ fromDate });
    const msgs = (page && page.messages ? page.messages : []).slice(0, 35);
    const out = [];
    for (const m of msgs) {
      let snippet = "";
      try {
        const full = await messenger.messages.getFull(m.id);
        const findText = (part) => {
          if (!part) return "";
          if (part.contentType && part.contentType.toLowerCase().includes("text/plain") && part.body) return part.body;
          if (part.parts) {
            for (const p of part.parts) {
              const t = findText(p);
              if (t) return t;
            }
          }
          return "";
        };
        snippet = findText(full).slice(0, 2000);
      } catch (_) {}
      out.push({
        from: m.author || "",
        subject: m.subject || "",
        body: snippet,
        message_id: m.headerMessageId || String(m.id || ""),
        date: m.date ? new Date(m.date).toISOString() : "",
      });
    }
    return out;
  } catch (_) {
    return [];
  }
}

async function getSettings() {
  const res = await messenger.storage.local.get({
    baseUrl: DEFAULT_BASE_URL,
    paused: false,
    lastStatus: "Connecting to http://127.0.0.1:8787...",
    lastPollAt: "",
    sentCount: 0,
  });
  return res;
}

async function listLocalIdentities() {
  const accounts = await messenger.accounts.list(false);
  const found = [];
  for (const acc of accounts) {
    for (const id of (acc.identities || [])) {
      if (id.email) {
        found.push({
          accountId: acc.id,
          identityId: id.id,
          email: id.email,
          name: id.name || "",
          accountName: acc.name || "",
        });
      }
    }
  }
  return found;
}

async function sendViaThunderbird(job, identities) {
  const targetFrom = (job.from_email || "").toLowerCase();
  let chosen = identities.find((i) => i.email.toLowerCase() === targetFrom) || identities[0];
  if (!chosen) {
    throw new Error("No signed-in email identity found in Thunderbird.");
  }

  const composeDetails = {
    identityId: chosen.identityId,
    to: [job.recipient_email],
    subject: job.subject || "(No Subject)",
    plainTextBody: job.body || "",
    isPlainText: true,
  };

  const tab = await messenger.compose.beginNew(composeDetails);
  try {
    const result = await messenger.compose.sendMessage(tab.id, { mode: "sendNow" });
    return {
      sent: true,
      mode: result && result.mode ? result.mode : "sendNow",
      headerMessageId: (result && result.headerMessageId) || "",
      from_email: chosen.email,
    };
  } catch (err) {
    // Clean up compose window if send failed
    try { await messenger.tabs.remove(tab.id); } catch (_) {}
    throw err;
  }
}

async function pollEmploymaxing(forceInbox = false) {
  if (isProcessing) return;
  const settings = await getSettings();
  if (settings.paused) {
    await messenger.storage.local.set({ lastStatus: "Paused by user" });
    return;
  }

  isProcessing = true;
  try {
    const identities = await listLocalIdentities();
    const recentInbox = await collectRecentInboxMessages(forceInbox);
    const pollResp = await fetch(`${settings.baseUrl}/api/thunderbird/bridge/poll`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Employmaxing-Bridge": BRIDGE_HEADER,
      },
      body: JSON.stringify({
        version: "1.4.0",
        accounts: identities.map((i) => ({ email: i.email, display_name: i.name })),
        recent_inbox: recentInbox,
      }),
    });

    if (!pollResp.ok) {
      throw new Error(`HTTP ${pollResp.status}`);
    }

    const data = await pollResp.json();
    const queue = data.queue || [];
    let sentNow = 0;

    for (const job of queue) {
      let ackPayload;
      try {
        const sendRes = await sendViaThunderbird(job, identities);
        ackPayload = {
          id: job.id,
          sent: true,
          message_id: sendRes.headerMessageId || "",
          from_email: sendRes.from_email,
        };
        sentNow += 1;
      } catch (sendErr) {
        ackPayload = {
          id: job.id,
          sent: false,
          error: String(sendErr && sendErr.message ? sendErr.message : sendErr),
        };
      }

      await fetch(`${settings.baseUrl}/api/thunderbird/bridge/ack`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Employmaxing-Bridge": BRIDGE_HEADER,
        },
        body: JSON.stringify(ackPayload),
      });
    }

    const totalSent = (settings.sentCount || 0) + sentNow;
    await messenger.storage.local.set({
      lastStatus: `ONLINE (${identities.length} account${identities.length === 1 ? "" : "s"} synced)`,
      lastPollAt: new Date().toLocaleTimeString(),
      sentCount: totalSent,
    });
  } catch (err) {
    await messenger.storage.local.set({
      lastStatus: `Waiting for Employmaxing server (${settings.baseUrl})`,
      lastPollAt: new Date().toLocaleTimeString(),
    });
  } finally {
    isProcessing = false;
  }
}

// Poll every 5 seconds while Thunderbird is open
messenger.alarms.create("employmaxing_poll", { periodInMinutes: 0.1 });
messenger.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "employmaxing_poll") pollEmploymaxing();
});

// Fast 5-second interval fallback + immediate boot heartbeat
setInterval(pollEmploymaxing, 5000);
pollEmploymaxing();

// Allow popup to trigger immediate poll (including fresh inbox sync)
messenger.runtime.onMessage.addListener((msg) => {
  if (msg && msg.type === "poll_now") {
    return pollEmploymaxing(true).then(() => ({ ok: true }));
  }
});
