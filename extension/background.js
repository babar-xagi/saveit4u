import { youtubeUrl } from "./url.js";

const HOST = "com.saveit4u.downloader";
const ACTIONS = new Set(["hello", "inspect", "enqueue", "pause", "resume", "cancel", "configure", "clear_finished", "open_folder"]);
let nativePort = null;
const pending = new Map();

function broadcast(message) {
  chrome.runtime.sendMessage({ source: "companion", ...message }).catch(() => {});
}

function connect() {
  if (nativePort) return nativePort;
  const port = chrome.runtime.connectNative(HOST);
  nativePort = port;
  port.onMessage.addListener(message => {
    if (message.event === "fatal") {
      for (const request of pending.values()) { clearTimeout(request.timer); request.reject(new Error(message.error)); }
      pending.clear();
      broadcast({ event: "disconnected", error: message.error });
      port.disconnect();
      nativePort = null;
      return;
    }
    if (message.id && pending.has(message.id)) {
      const request = pending.get(message.id);
      pending.delete(message.id);
      clearTimeout(request.timer);
      if (message.ok) request.resolve(message.result);
      else request.reject(new Error(message.error || "Companion request failed."));
    } else if (message.event) broadcast(message);
  });
  port.onDisconnect.addListener(() => {
    const detail = chrome.runtime.lastError?.message || "Companion connection ended.";
    if (nativePort === port) nativePort = null;
    for (const request of pending.values()) {
      clearTimeout(request.timer);
      request.reject(new Error(`${detail} Open Setup to install or reconnect the companion.`));
    }
    pending.clear();
    broadcast({ event: "disconnected", error: detail });
  });
  return port;
}

function nativeRequest(message) {
  return new Promise((resolve, reject) => {
    const id = crypto.randomUUID();
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error("Companion request timed out. Check the download manager and try again."));
    }, message.action === "inspect" ? 100_000 : 30_000);
    pending.set(id, { resolve, reject, timer });
    try { connect().postMessage({ ...message, id }); }
    catch (error) { clearTimeout(timer); pending.delete(id); reject(error); }
  });
}

async function openManager(url) {
  const target = new URL(chrome.runtime.getURL("app.html"));
  target.searchParams.set("view", "manager");
  if (url) target.searchParams.set("url", youtubeUrl(url));
  await chrome.tabs.create({ url: target.href });
}

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id || !message || typeof message !== "object") return false;
  // A content script can only open the manager; filesystem commands come from extension pages.
  if (message.action === "open_manager") {
    openManager(message.url).then(() => respond({ ok: true }), error => respond({ ok: false, error: error.message }));
    return true;
  }
  if (!sender.url?.startsWith(chrome.runtime.getURL("")) || !ACTIONS.has(message.action)) return false;
  nativeRequest(message).then(result => respond({ ok: true, result }), error => respond({ ok: false, error: error.message }));
  return true;
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: "saveit4u", title: "Save with SaveIt4U", contexts: ["page", "link", "video"],
      documentUrlPatterns: ["https://*.youtube.com/*", "https://youtube.com/*", "https://youtu.be/*"],
    });
  });
});

chrome.contextMenus.onClicked.addListener(info => {
  if (info.menuItemId === "saveit4u") openManager(info.linkUrl || info.pageUrl).catch(() => openManager());
});
