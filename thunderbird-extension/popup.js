async function render() {
  const s = await messenger.storage.local.get({
    paused: false,
    lastStatus: "Starting...",
    lastPollAt: "-",
    sentCount: 0,
  });
  document.getElementById("st").textContent = s.paused ? "PAUSED" : s.lastStatus;
  document.getElementById("ts").textContent = s.lastPollAt || "-";
  document.getElementById("cnt").textContent = String(s.sentCount || 0);
  document.getElementById("btn-pause").textContent = s.paused ? "Resume" : "Pause";
}

document.getElementById("btn-sync").addEventListener("click", async () => {
  await messenger.runtime.sendMessage({ type: "poll_now" });
  render();
});

document.getElementById("btn-pause").addEventListener("click", async () => {
  const s = await messenger.storage.local.get({ paused: false });
  await messenger.storage.local.set({ paused: !s.paused });
  render();
});

render();
