/* Local workflow server only. Never included in the extension or installer. */
const key = "__TEST_KEY__";
const id = "__EXTENSION_ID__";
const revision = "__REVISION__";
const origin = `chrome-extension://${id}/`;
const event = () => {
  const callbacks = [];
  return { addListener: fn => callbacks.push(fn), fire: (...args) => callbacks.forEach(fn => fn(...args)), callbacks };
};
async function transport(action, value = {}) {
  const response = await fetch(`/__native__/${action}`, { method: "POST", headers: { "Content-Type": "application/json", "X-SaveIt4U-Test": key }, body: JSON.stringify(value) });
  const result = await response.json();
  if (result.error) throw new Error(result.error);
  return result;
}
const videoPage = location.pathname === "/watch" || location.pathname.startsWith("/shorts/");
function sender() {
  const videoId = location.pathname.startsWith("/shorts/") ? location.pathname.split("/")[2] : new URLSearchParams(location.search).get("v") || "jNQXAC9IVRw";
  return videoPage ? { id, frameId: 0, tab: { id: 1 }, url: `https://www.youtube.com/watch?v=${videoId}` } : { id, url: origin + "app.html" };
}
const onMessage = event(), onConnect = event();
window.chrome = {
  runtime: { id, onMessage, onConnect, onInstalled: event(), onStartup: event(), getURL: path => origin + path,
    sendMessage: message => {
      if (message.source === "companion") { onMessage.fire(message, { id, url: origin + "background.js" }, () => {}); return Promise.resolve(); }
      return new Promise(resolve => {
        let handled = false;
        for (const callback of onMessage.callbacks) if (callback(message, sender(), resolve) === true) handled = true;
        if (!handled && message.action !== "get_connection") resolve(undefined);
      });
    },
    connectNative: () => {
      const messages = event(), disconnected = event();
      let alive = true, sequence = 0;
      const connected = transport("connect");
      const port = { onMessage: messages, onDisconnect: disconnected,
        postMessage: message => { connected.then(value => transport("send", { session: value.session, message })).catch(error => {
          if (alive) { alive = false; chrome.runtime.lastError = { message: error.message }; disconnected.fire(); }
        }); },
        disconnect: () => { if (alive) { alive = false; disconnected.fire(); } },
      };
      async function poll() {
        if (!alive) return;
        try {
          const value = await connected;
          const result = await transport("poll", { session: value.session, after: sequence });
          for (const item of result.messages) { sequence = item.sequence; messages.fire(item.message); }
          if (!result.connected && alive) { alive = false; chrome.runtime.lastError = { message: "Native connection interrupted by the workflow test" }; disconnected.fire(); return; }
        } catch (error) { if (alive) { alive = false; chrome.runtime.lastError = { message: error.message }; disconnected.fire(); return; } }
        setTimeout(poll, 150);
      }
      poll();
      return port;
    },
    connect: values => {
      const toContent = event(), disconnect = event();
      const content = { onMessage: toContent, onDisconnect: disconnect };
      onConnect.fire({ name: values.name, sender: sender(), onDisconnect: disconnect, postMessage: value => queueMicrotask(() => toContent.fire(value)) });
      return content;
    },
  },
  tabs: { query: async () => [{ url: "https://www.youtube.com/watch?v=jNQXAC9IVRw" }], create: async value => {
    const target = new URL(value.url); location.href = "/__workflow__/app.html" + target.search;
  } },
  storage: { local: { set: async value => localStorage.setItem("saveit4u-workflow", JSON.stringify(value)) } },
  // The UI harness can exercise denial but never reads real browser credentials.
  permissions: { request: async () => false, contains: async () => false, remove: async () => true, onRemoved: event() },
  contextMenus: { onClicked: event(), removeAll: callback => callback(), create() {} },
  alarms: { onAlarm: event(), create: (name, options) => setInterval(() => chrome.alarms.onAlarm.fire({ name }), options.periodInMinutes * 60_000) },
};
await import(`/background.js?rev=${revision}`);
if (videoPage) {
  await import(`/content.js?rev=${revision}`);
  document.getElementById("disconnect").addEventListener("click", async () => {
    await transport("disconnect");
    document.getElementById("result").textContent = "Native port interrupted. The actual extension bridge will reconnect automatically; the download engine remains running.";
  });
} else await import(`/app.js?rev=${revision}`);
