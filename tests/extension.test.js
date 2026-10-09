import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { youtubeUrl } from "../extension/url.js";

const canonical = "https://www.youtube.com/watch?v=jNQXAC9IVRw";

test("normalizes videos and Shorts while stripping playlist and tracking", () => {
  for (const url of [canonical + "&list=abc&t=2", "https://youtu.be/jNQXAC9IVRw?si=123", "https://www.youtube.com/shorts/jNQXAC9IVRw", "https://m.youtube.com/embed/jNQXAC9IVRw/"]) {
    assert.equal(youtubeUrl(url), canonical);
  }
});

test("rejects unsafe, spoofed and non-video URLs", () => {
  for (const url of ["javascript:alert(1)", "http://youtube.com/watch?v=jNQXAC9IVRw", "https://youtube.com.evil.test/watch?v=jNQXAC9IVRw", "https://youtube.com@localhost/watch?v=jNQXAC9IVRw", "https://youtube.com:8888/watch?v=jNQXAC9IVRw", canonical + "&v=abcdefghijk", "https://youtube.com/playlist?list=xx", "https://youtu.be/../../file", null]) assert.throws(() => youtubeUrl(url));
});

test("MV3 extension has local scripts, narrow permissions and existing icons", async () => {
  const manifest = JSON.parse(await readFile(new URL("../extension/manifest.json", import.meta.url)));
  assert.equal(manifest.manifest_version, 3);
  assert.deepEqual(manifest.permissions, ["nativeMessaging", "activeTab", "storage", "contextMenus", "alarms"]);
  assert.equal(manifest.host_permissions, undefined);
  assert.deepEqual(manifest.optional_permissions, ["cookies"]);
  assert.deepEqual(manifest.optional_host_permissions, ["https://*.youtube.com/*"]);
  for (const path of Object.values(manifest.icons)) assert.ok((await readFile(new URL(`../extension/${path}`, import.meta.url))).length > 0);
  for (const path of ["app.js", "content.js", "background.js"]) {
    const source = await readFile(new URL(`../extension/${path}`, import.meta.url), "utf8");
    assert.doesNotMatch(source, /\.innerHTML\s*=|\beval\s*\(|new Function\(/);
  }
});

function event() {
  const listeners = [];
  return { listeners, addListener: callback => listeners.push(callback), fire: (...args) => listeners.forEach(callback => callback(...args)) };
}

test("native bridge authenticates senders, correlates replies and surfaces disconnects", async t => {
  const id = "a".repeat(32);
  const sent = [];
  const tabs = [];
  const broadcasts = [];
  const port = { onMessage: event(), onDisconnect: event(), postMessage: message => sent.push(message), disconnect() { this.onDisconnect.fire(); } };
  globalThis.chrome = {
    runtime: { id, onMessage: event(), onInstalled: event(), onConnect: event(), onStartup: event(), getURL: path => `chrome-extension://${id}/${path}`,
      connectNative: name => { assert.equal(name, "com.saveit4u.downloader"); return port; },
      sendMessage: async message => { broadcasts.push(message); } },
    tabs: { create: async data => { tabs.push(data); } },
    contextMenus: { onClicked: event(), removeAll: callback => callback(), create() {} },
    storage: { local: { set: async () => {} } },
    alarms: { onAlarm: event(), create() {} },
  };
  const module = await import("../extension/background.js");
  t.after(() => { module.bridge.dispose(); delete globalThis.chrome; });
  const receive = chrome.runtime.onMessage.listeners[0];
  const page = { id, url: `chrome-extension://${id}/app.html`, tab: { id: 123 } };
  const content = { id, url: canonical, tab: { id: 456 }, frameId: 0 };
  assert.equal(receive({ action: "configure" }, content, () => assert.fail("Content script accessed filesystem settings")), false);
  assert.equal(receive({ action: "share_youtube_session", consent: true }, content, () => assert.fail("Content script accessed session sharing")), false);
  assert.equal(receive({ action: "youtube_session", cookies: [] }, page, () => assert.fail("Page supplied arbitrary cookies")), false);
  const noConsent = await new Promise(resolve => receive({ action: "share_youtube_session" }, page, resolve));
  assert.equal(noConsent.ok, false);
  assert.match(noConsent.error, /Confirm sharing/);
  assert.equal(receive({ action: "hello" }, { ...page, id: "another-extension" }, () => assert.fail()), false);
  const response = new Promise(resolve => assert.equal(receive({ action: "hello" }, page, resolve), true));
  assert.equal(sent.length, 1);
  port.onMessage.fire({ id: sent[0].id, ok: true, result: { ready: true } });
  assert.deepEqual(await response, { ok: true, result: { ready: true } });
  port.onMessage.fire({ event: "job", job: { id: "job", status: "downloading" } });
  assert.equal(broadcasts[0].source, "companion");
  const opened = new Promise(resolve => receive({ action: "open_manager", url: "https://www.youtube.com/shorts/jNQXAC9IVRw" }, content, resolve));
  assert.deepEqual(await opened, { ok: true });
  assert.equal(new URL(tabs[0].url).searchParams.get("url"), canonical);
  const failure = new Promise(resolve => receive({ action: "inspect", url: canonical }, page, resolve));
  await new Promise(resolve => setImmediate(resolve));
  chrome.runtime.lastError = { message: "Native host not found" };
  port.onDisconnect.fire();
  assert.match((await failure).error, /Native host not found/);
  module.bridge.dispose();
  delete globalThis.chrome;
});
