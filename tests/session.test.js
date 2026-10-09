import test from "node:test";
import assert from "node:assert/strict";
import { readYouTubeSession, SESSION_PERMISSIONS, userError } from "../extension/session.js";

test("permission denial never reads cookies", async () => {
  const api = { permissions: { contains: async () => false }, cookies: { getAllCookieStores: () => assert.fail("Cookies read without permission") } };
  await assert.rejects(readYouTubeSession(api), /Allow YouTube/);
  assert.deepEqual(SESSION_PERMISSIONS.origins, ["https://*.youtube.com/*"]);
});

test("only YouTube cookies from the selected tab store are forwarded", async () => {
  let query;
  const cookie = { domain: ".youtube.com", name: "SAPISID", value: "synthetic-value", path: "/", secure: true, httpOnly: true, hostOnly: false, storeId: "regular" };
  const api = {
    permissions: { contains: async () => true },
    cookies: { getAllCookieStores: async () => [{ id: "regular", tabIds: [42] }, { id: "incognito", tabIds: [99] }],
      getAll: async details => { query = details; return [cookie, { ...cookie, domain: ".google.com" }, { ...cookie, domain: "youtube.com.evil.test" }, { ...cookie, partitionKey: { topLevelSite: "https://other.test" } }]; } }
  };
  const values = await readYouTubeSession(api, { tabId: 42 });
  assert.deepEqual(query, { domain: "youtube.com", storeId: "regular" });
  assert.equal(values.length, 1);
  assert.equal(values[0].value, "synthetic-value");
  assert.equal(values[0].storeId, undefined);
});

test("verification error has an actionable message without ANSI or CLI advice", () => {
  const message = userError("\x1b[0;31mERROR:\x1b[0m Sign in to confirm you’re not a bot. Use --cookies-from-browser chrome");
  assert.match(message, /YouTube verification required/);
  assert.doesNotMatch(message, /\x1b|--cookies|ERROR:/);
  assert.equal(userError("\x1b[31mVideo unavailable\x1b[0m"), "Video unavailable");
});
