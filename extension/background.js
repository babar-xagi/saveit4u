import { youtubeUrl } from "./url.js";
import { NativeBridge } from "./connection.js";

const ACTIONS = new Set(["hello", "inspect", "enqueue", "pause", "resume", "cancel", "configure", "clear_finished", "open_folder", "open_desktop"]);
const pages = new Set();
const cache = new Map();
const flights = new Map();

function publish(message) {
  chrome.runtime.sendMessage({ source: "companion", ...message }).catch(() => {});
  for (const port of pages) {
    try { port.postMessage(message); } catch { pages.delete(port); }
  }
  if (message.event === "connection") chrome.storage.local.set({ connection: message.connection }).catch(() => {});
}

const bridge = new NativeBridge(chrome.runtime, { publish });
export { bridge };

async function inspect(url) {
  const canonical = youtubeUrl(url);
  const saved = cache.get(canonical);
  if (saved && Date.now() - saved.time < 90_000) return saved.value;
  if (flights.has(canonical)) return flights.get(canonical);
  const promise = bridge.send("inspect", { url: canonical }).then(value => {
    cache.set(canonical, { time: Date.now(), value });
    while (cache.size > 24) cache.delete(cache.keys().next().value);
    return value;
  }).finally(() => flights.delete(canonical));
  flights.set(canonical, promise);
  return promise;
}

async function openManager(url) {
  const target = new URL(chrome.runtime.getURL("app.html"));
  target.searchParams.set("view", "manager");
  if (url) target.searchParams.set("url", youtubeUrl(url));
  await chrome.tabs.create({ url: target.href });
}

function youtubeSender(sender) {
  if (sender.id !== chrome.runtime.id || sender.frameId !== 0 || !sender.tab) return null;
  try {
    const url = new URL(sender.url);
    return url.protocol === "https:" && ["www.youtube.com", "m.youtube.com"].includes(url.hostname);
  } catch { return false; }
}

function videoSender(sender) {
  if (!youtubeSender(sender)) return null;
  try { return youtubeUrl(sender.url); } catch { return null; }
}

chrome.runtime.onConnect.addListener(port => {
  if (port.name !== "saveit4u-video" || !youtubeSender(port.sender)) return;
  pages.add(port);
  port.onDisconnect.addListener(() => pages.delete(port));
  port.postMessage({ event: "connection", connection: bridge.state });
});

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id || !message || typeof message !== "object") return false;
  const extensionPage = sender.url?.startsWith(chrome.runtime.getURL(""));
  const currentVideo = videoSender(sender);
  if (message.action === "open_manager" && (extensionPage || currentVideo)) {
    openManager(message.url).then(() => respond({ ok: true }), error => respond({ ok: false, error: error.message }));
    return true;
  }
  if (message.action === "get_connection" && (extensionPage || currentVideo)) { respond({ ok: true, result: bridge.state }); return false; }
  if (!extensionPage) {
    if (!currentVideo || !["inspect", "enqueue"].includes(message.action)) return false;
    try {
      const requested = youtubeUrl(message.action === "inspect" ? message.url : message.request?.url);
      if (requested !== currentVideo) throw new Error("Open the selected video before downloading it.");
    } catch (error) { respond({ ok: false, error: error.message }); return false; }
  } else if (!ACTIONS.has(message.action)) return false;
  const operation = message.action === "inspect" ? inspect(message.url) : bridge.send(message.action,
    Object.fromEntries(["url", "request", "job_id", "output_dir"].filter(key => key in message).map(key => [key, message[key]])));
  operation.then(result => respond({ ok: true, result }), error => respond({ ok: false, error: error.message }));
  return true;
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => chrome.contextMenus.create({ id: "saveit4u", title: "Save with SaveIt4U", contexts: ["page", "link", "video"],
    documentUrlPatterns: ["https://*.youtube.com/*", "https://youtube.com/*", "https://youtu.be/*"] }));
  bridge.ensureConnected().catch(() => {});
});
chrome.runtime.onStartup.addListener(() => bridge.ensureConnected().catch(() => {}));
chrome.contextMenus.onClicked.addListener(info => {
  if (info.menuItemId === "saveit4u") openManager(info.linkUrl || info.pageUrl).catch(() => openManager());
});
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === "saveit4u-reconnect") bridge.ensureConnected().catch(() => {});
});
chrome.alarms.create("saveit4u-reconnect", { periodInMinutes: 0.5 });
bridge.ensureConnected().catch(() => {});
