// Called only by the extension UI after an explicit permission request and click.
export const SESSION_PERMISSIONS = { permissions: ["cookies"], origins: ["https://*.youtube.com/*"] };
const domains = new Set(["youtube.com", "www.youtube.com", "m.youtube.com"]);

export async function readYouTubeSession(api, context = {}) {
  if (!await api.permissions.contains(SESSION_PERMISSIONS)) throw new Error("Allow YouTube session access first.");
  const stores = await api.cookies.getAllCookieStores();
  const matching = context.tabId != null ? stores.find(store => store.tabIds.includes(context.tabId)) : null;
  // Never combine regular and incognito cookie stores. The extension page's store
  // is used if a dashboard has no current YouTube tab.
  const details = { domain: "youtube.com", ...(matching ? { storeId: matching.id } : {}) };
  const values = await api.cookies.getAll(details);
  const filtered = values.filter(cookie => domains.has(cookie.domain.replace(/^\./, "")) && !cookie.partitionKey);
  if (!filtered.length) throw new Error("No YouTube session found. Open YouTube in this browser, sign in or complete verification, then try again.");
  return filtered.map(({ domain, name, value, path, secure, httpOnly, hostOnly, expirationDate }) =>
    ({ domain, name, value, path, secure, httpOnly, hostOnly, expirationDate }));
}

export function userError(value) {
  const message = String(value || "Request failed.").replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, "").replace(/[\x00-\x08\x0b-\x1f\x7f]/g, "");
  if (/confirm you[’']re not a bot|verification required|login required|sign in to|use --cookies/i.test(message))
    return "YouTube verification required. Open the video on YouTube, finish signing in or verification, then use ‘Use YouTube sign-in’ below and retry. YouTube may still restrict this request.";
  return message.slice(0, 2000);
}
