(() => {
  const host = document.createElement("div");
  host.id = "saveit4u-page-tools";
  // Keep the visible panel accessible to assistive tools. Download authorization
  // lives in the isolated script, trusted click checks and current-tab validation.
  const shadow = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = `
    *{box-sizing:border-box} :host{font:13px/1.5 system-ui,sans-serif;color:#f0f2e8}
    button,select{font:inherit} button{cursor:pointer;border:0} button:disabled{opacity:.5;cursor:wait}
    button:focus-visible,select:focus-visible{outline:2px solid #c1f17b;outline-offset:3px}
    .trigger{border-radius:99px;background:#c1f17b;color:#182314;padding:12px 18px;font:750 13px/1.5 system-ui,sans-serif;box-shadow:0 5px 24px #0006;float:right}
    .sheet{font:13px/1.5 system-ui,sans-serif;color:#f0f2e8;width:370px;max-width:calc(100vw - 32px);padding:20px;border:1px solid #425239;background:#141a14;border-radius:18px;box-shadow:0 15px 70px #000a;margin-bottom:10px;max-height:75vh;overflow:auto}
    [hidden]{display:none!important}.header{display:flex;justify-content:space-between;align-items:center;gap:12px}.brand{color:#c1f17b;font-weight:750;font-size:18px}
    .close{background:#2a3526;color:#e4f1d7;border-radius:7px;font-size:20px;padding:2px 10px}.status{color:#a8b39f;font-size:11px;margin:8px 0}.status.error{color:#ffb29f}
    h2{font-size:15px;line-height:1.4;margin:12px 0;overflow-wrap:anywhere}.help{color:#a8b39f;font-size:11px;line-height:1.5;margin:10px 0}
    select{width:100%;background:#24301e;color:#e9f5df;border:1px solid #47553c;padding:9px;border-radius:8px;margin:4px 0 12px}
    label{display:block;font-size:11px;color:#acb7a3}.qualities{display:grid;grid-template-columns:1fr 1fr;gap:8px}.quality{padding:12px;background:#29371f;color:#e4fbc9;border:1px solid #435638;border-radius:10px;text-align:left}.quality:hover{background:#3d502e}
    .quality strong{display:block;font-size:15px}.size{display:block;color:#b3c7a1;font-size:10px;margin-top:4px}.secondary{background:#2b3723;color:#d7e9c5;border-radius:8px;padding:9px 12px;margin:5px 5px 0 0}
    .success{color:#c1f17b}.footer{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:12px}.automatic{font-size:10px;color:#9ba990}
  `;
  shadow.append(style);
  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  const sheet = element("section", undefined, "sheet");
  sheet.setAttribute("aria-label", "SaveIt4U quality selection");
  sheet.hidden = true;
  const heading = element("div", undefined, "header");
  const close = element("button", "×", "close");
  close.setAttribute("aria-label", "Close quality selection");
  heading.append(element("span", "↓ saveit4u", "brand"), close);
  const status = element("p", "Connecting…", "status");
  status.setAttribute("role", "status");
  const title = element("h2", "Choose a quality to download");
  const formatLabel = element("label", "Video format");
  const format = element("select");
  for (const [value, text] of [["mkv", "MKV · highest available quality"], ["mp4", "MP4 · compatible playback"]]) {
    const option = element("option", text); option.value = value; format.append(option);
  }
  formatLabel.append(format);
  const grid = element("div", undefined, "qualities");
  const captionsLabel = element("label", "Include transcript");
  const captions = element("select");
  captionsLabel.append(captions);
  const help = element("p", "", "help");
  const retry = element("button", "Detect again", "secondary");
  const manager = element("button", "Download dashboard ↗", "secondary");
  const footer = element("div", undefined, "footer");
  footer.append(manager, element("span", "Saves locally", "automatic"));
  sheet.append(heading, status, title, formatLabel, grid, captionsLabel, help, retry, footer);
  const trigger = element("button", "↓ SaveIt4U", "trigger");
  trigger.setAttribute("aria-label", "Show available download qualities");
  shadow.append(sheet, trigger);
  let current = "", dismissed = "", token = 0, metadata = null, busy = false, detecting = false, inspectionRetries = 0;
  let connection = { state: "Connecting", ready: false };

  function canonical() {
    const url = new URL(location.href);
    const id = url.pathname === "/watch" ? url.searchParams.get("v") : url.pathname.match(/^\/shorts\/([A-Za-z0-9_-]{11})\/?$/)?.[1];
    return /^[A-Za-z0-9_-]{11}$/.test(id || "") ? `https://www.youtube.com/watch?v=${id}` : "";
  }
  function bytes(value) {
    if (!value) return "Size unknown";
    return value >= 1024 ** 3 ? `${(value / 1024 ** 3).toFixed(1)} GB` : `${(value / 1024 ** 2).toFixed(1)} MB`;
  }
  async function request(action, values = {}) {
    const result = await chrome.runtime.sendMessage({ action, ...values });
    if (!result?.ok) throw new Error(result?.error || "Connection unavailable. Open SaveIt4U and try again.");
    return result.result;
  }
  function showStatus() {
    status.textContent = connection.state + (connection.state === "Connected" ? " · desktop app ready" : " · reconnecting automatically");
    status.classList.toggle("error", connection.state === "Connection Error");
  }
  function choices() {
    grid.replaceChildren();
    const qualities = (metadata?.qualities || []).filter(item => item.container === format.value);
    for (const quality of qualities) {
      const button = element("button", undefined, "quality");
      button.append(element("strong", quality.label), element("span", `${quality.estimated && quality.size ? "~" : ""}${bytes(quality.size)} · ${format.value.toUpperCase()}`, "size"));
      button.addEventListener("click", async event => {
        if (!event.isTrusted || busy || !metadata || metadata.url !== canonical()) return;
        busy = true;
        for (const item of grid.querySelectorAll("button")) item.disabled = true;
        try {
          await request("enqueue", { request: { url: metadata.url, mode: "video", quality: String(quality.height), container: format.value,
            language: captions.value, auto_captions: true } });
          help.className = "help success";
          help.textContent = "Added to your downloads. You can keep watching; the app handles the rest.";
        } catch (error) { help.className = "help"; help.textContent = error.message; }
        finally { busy = false; for (const item of grid.querySelectorAll("button")) item.disabled = false; }
      });
      grid.append(button);
    }
    if (!qualities.length) help.textContent = metadata?.is_live ? "This video is live. Download it after the stream finishes." : "No tracks in this format. Try MKV, Detect again, or paste the YouTube link in the dashboard.";
    else help.textContent = "Click a quality to start downloading. ~ means estimated size; source quality is preserved.";
    retry.hidden = false;
  }
  async function detect() {
    const url = canonical();
    if (!url) return;
    const own = ++token;
    detecting = true;
    current = url;
    metadata = null;
    sheet.hidden = false;
    title.textContent = "Reading available qualities…";
    grid.replaceChildren();
    retry.hidden = true;
    help.textContent = "You can keep watching while we check this video.";
    try {
      const found = await request("inspect", { url });
      if (own !== token || canonical() !== url) return;
      metadata = found;
      inspectionRetries = 0;
      title.textContent = found.title;
      captions.replaceChildren();
      const none = element("option", "Without transcript"); none.value = ""; captions.append(none);
      for (const track of found.captions) {
        const option = element("option", `${track.name} (${track.code})${track.automatic ? " · automatic" : ""}`);
        option.value = track.code; captions.append(option);
      }
      choices();
    } catch (error) {
      if (own !== token) return;
      title.textContent = "Video detection needs attention";
      help.textContent = /YouTube verification required/.test(error.message)
        ? "YouTube requires sign-in or verification. Open Download dashboard → YouTube sign-in, then Detect again."
        : `${error.message} Use Detect again or open the dashboard to paste a YouTube link.`;
      retry.hidden = false;
      if (/Two videos|inspection is busy/.test(error.message) && inspectionRetries++ < 3) {
        help.textContent = "Finishing the previous video check. Trying this video again shortly…";
        setTimeout(() => { if (own === token && !sheet.hidden && canonical() === url) detect(); }, 1500);
      }
    } finally {
      if (own === token) detecting = false;
    }
  }
  function navigate() {
    const url = canonical();
    host.hidden = !url;
    if (!host.isConnected) document.body.append(host);
    if (url !== current) {
      ++token; current = url; metadata = null; inspectionRetries = 0; dismissed = "";
      if (url && dismissed !== url) detect();
      else sheet.hidden = true;
    }
  }
  close.addEventListener("click", () => { dismissed = canonical(); sheet.hidden = true; });
  trigger.addEventListener("click", event => { if (event.isTrusted) metadata ? (sheet.hidden = !sheet.hidden) : detect(); });
  retry.addEventListener("click", event => { if (event.isTrusted) detect(); });
  manager.addEventListener("click", event => { if (event.isTrusted) request("open_manager", { url: canonical() }).catch(error => { help.textContent = error.message; }); });
  format.addEventListener("change", choices);
  function subscribe() {
    try {
      const port = chrome.runtime.connect({ name: "saveit4u-video" });
      port.onMessage.addListener(message => {
        if (message.event === "connection") {
          connection = message.connection;
          showStatus();
          if (connection.ready && !metadata && !detecting && !sheet.hidden) detect();
        }
        if (message.event === "job" && message.job.request.url === canonical()) {
          const job = message.job;
          if (job.status === "complete") { help.className = "help success"; help.textContent = "Saved to your SaveIt4U folder. Keep watching or choose another quality."; }
          else if (job.status === "downloading") { help.className = "help success"; help.textContent = `Downloading · ${job.percent == null ? "estimating progress" : job.percent + "%"} · ${bytes(job.speed)}/s`; }
          else if (job.status === "failed") { help.className = "help"; help.textContent = `Download needs attention: ${job.error} Open the dashboard to retry.`; }
          else if (job.status === "paused") { help.className = "help"; help.textContent = "Download paused. Resume it from the dashboard or desktop app."; }
          else if (job.status === "queued") { help.className = "help success"; help.textContent = "Queued. Your download will start automatically."; }
          else if (["processing", "merging"].includes(job.status)) { help.className = "help success"; help.textContent = "Finishing your video and transcript files…"; }
        }
      });
      port.onDisconnect.addListener(() => {
        connection = { state: "Disconnected", ready: false }; showStatus();
        setTimeout(subscribe, 3000);
      });
    } catch { status.textContent = "Extension updated. Refresh this page to reconnect."; }
  }
  document.addEventListener("yt-navigate-finish", navigate);
  window.addEventListener("popstate", navigate);
  setInterval(navigate, 1000);
  navigate();
  subscribe();
})();
