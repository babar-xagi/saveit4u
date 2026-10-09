import { youtubeUrl } from "./url.js";

const $ = id => document.getElementById(id);
const query = new URLSearchParams(location.search);
const fullView = query.get("view") === "manager";
document.body.classList.toggle("manager", fullView);
$("expand").hidden = fullView;
let metadata = null;
let ready = false;
let inspecting = false;
let inspectionToken = 0;
const jobs = new Map();
const cards = new Map();

function notice(message, error = false) {
  $("notice").textContent = message;
  $("notice").classList.toggle("error", error);
  $("notice").hidden = !message;
}

function panel(name) {
  for (const item of document.querySelectorAll(".nav-item")) {
    const selected = item.dataset.panel === name;
    item.classList.toggle("selected", selected);
    item.setAttribute("aria-selected", String(selected));
  }
  for (const item of document.querySelectorAll(".panel")) item.hidden = item.id !== `panel-${name}`;
}

async function request(action, data = {}) {
  if (!globalThis.chrome?.runtime?.id) throw new Error("Load the extension in Chrome or Edge to connect to your computer.");
  const response = await chrome.runtime.sendMessage({ action, ...data });
  if (!response?.ok) throw new Error(response?.error || "No response from the companion. Open Setup to reconnect.");
  return response.result;
}

function on(id, event, callback) {
  $(id).addEventListener(event, e => {
    e.preventDefault();
    Promise.resolve().then(() => callback(e)).catch(error => notice(error.message, true));
  });
}

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function duration(seconds) {
  if (!Number.isFinite(seconds)) return "Duration unavailable";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor(seconds / 60) % 60;
  const secs = Math.floor(seconds % 60);
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}` : `${minutes}:${String(secs).padStart(2, "0")}`;
}

function bytes(value) {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const index = Math.min(3, Math.floor(Math.log(value) / Math.log(1024)));
  return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${["B", "KB", "MB", "GB"][index]}`;
}

function option(value, label) {
  const item = node("option", label);
  item.value = value;
  return item;
}

function mode() { return document.querySelector("input[name=mode]:checked").value; }

function updateChoices() {
  const chosen = mode();
  $("container-field").hidden = chosen !== "video";
  $("quality-field").hidden = chosen !== "video";
  $("audio-field").hidden = chosen !== "audio";
  const oldQuality = $("quality").value;
  const heights = $("container").value === "mp4" ? metadata?.mp4_heights || [] : metadata?.heights || [];
  $("quality").replaceChildren(option("best", "Best available"));
  for (const height of [2160, 1440, 1080, 720, 480, 360]) {
    if (heights.includes(height)) $("quality").append(option(String(height), `Up to ${height}p${height === 2160 ? " · 4K" : ""}`));
  }
  if ([...$("quality").options].some(item => item.value === oldQuality)) $("quality").value = oldQuality;
  const oldLanguage = $("language").value;
  $("language").replaceChildren(option("", chosen === "transcript" ? "Choose a caption language" : "Without transcript"));
  const tracks = (metadata?.captions || []).filter(track => $("auto-captions").checked || !track.automatic);
  for (const track of tracks) $("language").append(option(track.code, `${track.name} (${track.code})${track.automatic ? " · automatic" : ""}`));
  if ([...$("language").options].some(item => item.value === oldLanguage)) $("language").value = oldLanguage;
  else if (chosen === "transcript" && tracks.length) $("language").value = (tracks.find(t => t.code === "en") || tracks[0]).code;
  let help = "Original quality with audio. Separate streams are merged locally.";
  let allowed = ready && !!metadata && !metadata.is_live;
  if (chosen === "video" && $("container").value === "mp4") {
    help = heights.length ? `H.264 + AAC, up to ${Math.max(...heights)}p. Use MKV for the highest available quality.` : "No compatible H.264 track is available. Choose MKV for this video.";
    allowed &&= heights.length > 0;
  }
  if (chosen === "audio") help = "M4A/Opus may require conversion. MP3 is converted from the source audio; quality cannot exceed the original.";
  if (chosen === "transcript") {
    help = tracks.length ? "Exports original VTT plus timed TXT, SRT and JSON. Automatic captions may contain mistakes." : "No available captions. This version exports existing transcripts; it does not generate speech recognition.";
    allowed &&= !!$("language").value;
  }
  if (metadata?.is_live) help = "This video is live. Download it after the stream has finished.";
  $("format-help").textContent = help;
  $("enqueue").disabled = !allowed;
}

async function inspect() {
  if (!ready) { panel("setup"); throw new Error("Complete companion setup and check the connection first."); }
  const url = youtubeUrl($("url").value);
  const token = ++inspectionToken;
  inspecting = true;
  metadata = null;
  $("video").hidden = true;
  $("inspect").disabled = true;
  $("inspect").textContent = "Finding…";
  notice("Reading available quality, audio and caption tracks…");
  try {
    const found = await request("inspect", { url });
    if (token !== inspectionToken) return;
    metadata = found;
    $("url").value = found.url;
    $("video-title").textContent = found.title;
    $("video-channel").textContent = found.channel;
    $("video-meta").textContent = `${duration(found.duration)} · ${found.heights.length ? `Up to ${Math.max(...found.heights)}p` : "Audio available"} · ${found.captions.length} caption languages`;
    $("video").hidden = false;
    updateChoices();
    notice("");
  } finally {
    if (token === inspectionToken) {
      inspecting = false;
      $("inspect").disabled = false;
      $("inspect").textContent = "Find video →";
    }
  }
}

function renderJob(job) {
  jobs.set(job.id, job);
  let card = cards.get(job.id);
  if (!card) {
    const element = node("article", undefined, "job");
    const title = node("h2", "", "job-title");
    const status = node("span");
    const rate = node("span");
    const statusRow = node("div", undefined, "job-status");
    statusRow.append(status, rate);
    const progress = node("progress");
    progress.max = 100;
    const detail = node("p", "", "job-detail");
    const warning = node("p", "", "job-detail job-warning");
    const error = node("p", "", "job-detail job-error");
    const actions = node("div", undefined, "job-actions");
    element.append(title, statusRow, progress, detail, warning, error, actions);
    card = { element, title, status, rate, progress, detail, warning, error, actions, lastStatus: null };
    cards.set(job.id, card);
    $("jobs").prepend(element);
  }
  card.title.textContent = job.title;
  card.status.textContent = ({ queued: "Queued", downloading: "Downloading", merging: "Merging streams", processing: "Processing media", complete: "Saved", paused: "Paused", failed: "Needs attention", cancelled: "Cancelled" })[job.status] || job.status;
  card.status.className = job.status;
  card.rate.textContent = job.status === "downloading" ? `${bytes(job.speed)}/s${job.eta != null ? ` · ${duration(job.eta)} left` : ""}` : "";
  if (Number.isFinite(job.percent)) card.progress.value = job.percent;
  else card.progress.removeAttribute("value");
  card.progress.hidden = ["complete", "cancelled", "failed"].includes(job.status);
  card.progress.setAttribute("aria-label", `${job.title}: ${card.status.textContent}`);
  const type = job.request.mode === "video" ? `${job.request.container.toUpperCase()} · ${job.request.quality === "best" ? "Best quality" : `Up to ${job.request.quality}p`}` : job.request.mode === "audio" ? job.request.audio.toUpperCase() : "Transcript";
  card.detail.textContent = job.status === "complete" ? `${type} · ${job.files.length} files saved · ${job.files.join(", ")}` : `${type} · ${bytes(job.downloaded)}${job.total ? ` / ${bytes(job.total)}` : ""}${job.stream ? ` · Stream ${job.stream}` : ""}`;
  card.warning.textContent = job.warning || "";
  card.warning.hidden = !job.warning;
  card.error.textContent = job.error || "";
  card.error.hidden = !job.error;
  if (card.lastStatus !== job.status) {
    card.actions.replaceChildren();
    const actions = [];
    if (["queued", "downloading", "merging", "processing"].includes(job.status)) actions.push(["pause", "Pause"]);
    if (["paused", "failed"].includes(job.status)) actions.push(["resume", job.status === "failed" ? "Retry" : "Resume"]);
    if (["queued", "downloading", "merging", "processing", "paused", "failed"].includes(job.status)) actions.push(["cancel", "Cancel"]);
    actions.push(["open_folder", "Open folder ↗"]);
    for (const [action, label] of actions) {
      const button = node("button", label, "secondary");
      button.type = "button";
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          const result = await request(action, { job_id: job.id });
          if (result?.id) renderJob(result);
        } catch (error) { notice(error.message, true); }
        finally { button.disabled = false; }
      });
      card.actions.append(button);
    }
    card.lastStatus = job.status;
  }
  updateCount();
}

function updateCount() {
  $("queue-count").textContent = [...jobs.values()].filter(job => !["complete", "cancelled"].includes(job.status)).length;
  $("empty").hidden = jobs.size > 0;
}

function renderSnapshot(state) {
  const ids = new Set(state.jobs.map(job => job.id));
  for (const [id, card] of cards) if (!ids.has(id)) { card.element.remove(); cards.delete(id); jobs.delete(id); }
  for (const job of [...state.jobs].sort((a, b) => a.created - b.created)) renderJob(job);
  $("output-dir").value = state.output_dir;
  updateCount();
}

function disconnected(message) {
  ready = false;
  $("connection").textContent = "Setup needed";
  $("connection").className = "connection error";
  $("dependencies").replaceChildren();
  updateChoices();
  if (message) notice(message, true);
}

async function connect() {
  $("connection").textContent = "Connecting…";
  $("reconnect").disabled = true;
  try {
    const result = await request("hello");
    ready = result.ready;
    $("connection").textContent = ready ? "● Companion ready" : "Dependencies missing";
    $("connection").className = `connection ${ready ? "ready" : "error"}`;
    renderSnapshot(result);
    $("dependencies").replaceChildren();
    const names = { yt_dlp: "yt-dlp", ejs: "YouTube JS solver", ffmpeg: "FFmpeg", ffprobe: "FFprobe", runtime: "JS runtime" };
    for (const [key, value] of Object.entries(result.dependencies)) {
      const row = node("div", undefined, `dependency${value ? "" : " missing"}`);
      row.append(node("span", names[key] || key), node("span", value || "Missing"));
      $("dependencies").append(row);
    }
    updateChoices();
    notice(ready ? "" : "Install the missing dependencies, then check the connection again.", !ready);
    if (!ready) panel("setup");
  } catch (error) { disconnected(error.message); panel("setup"); }
  finally { $("reconnect").disabled = false; }
}

async function useTab() {
  if (!globalThis.chrome?.tabs) throw new Error("Open this extension from a YouTube tab.");
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  $("url").value = youtubeUrl(tab?.url);
  panel("download");
}

for (const item of document.querySelectorAll(".nav-item")) item.addEventListener("click", () => panel(item.dataset.panel));
for (const input of document.querySelectorAll("input[name=mode]")) input.addEventListener("change", updateChoices);
for (const id of ["container", "auto-captions", "language"]) $(id).addEventListener("change", updateChoices);
$("url").addEventListener("input", () => {
  if (metadata || inspecting) { ++inspectionToken; metadata = null; inspecting = false; $("video").hidden = true; $("inspect").disabled = false; $("inspect").textContent = "Find video →"; }
});
on("inspect-form", "submit", inspect);
on("use-tab", "click", useTab);
on("expand", "click", () => chrome.runtime.sendMessage({ action: "open_manager", url: metadata?.url }));
on("new-download", "click", () => panel("download"));
on("reconnect", "click", connect);
on("copy-id", "click", async () => { await navigator.clipboard.writeText(chrome.runtime.id); notice("Extension ID copied."); });
on("open-folder", "click", () => request("open_folder"));
on("settings-form", "submit", async () => { renderSnapshot(await request("configure", { output_dir: $("output-dir").value })); notice("Folder saved for new downloads."); });
on("clear", "click", async () => { renderSnapshot(await request("clear_finished")); notice("Finished history cleared. Your files are still on disk."); });
on("download-form", "submit", async () => {
  if (!metadata || !ready || $("enqueue").disabled) return;
  $("enqueue").disabled = true;
  try {
    const job = await request("enqueue", { request: { url: metadata.url, mode: mode(), quality: $("quality").value,
      container: $("container").value, audio: $("audio").value, language: $("language").value, auto_captions: $("auto-captions").checked } });
    renderJob(job);
    panel("queue");
    notice("Added to your local download queue.");
  } finally { updateChoices(); }
});

if (globalThis.chrome?.runtime?.id) {
  $("extension-id").textContent = chrome.runtime.id;
  $("install-command").textContent = `.venv\\Scripts\\python.exe scripts\\register_host.py --extension-id ${chrome.runtime.id}`;
  chrome.runtime.onMessage.addListener(message => {
    if (message.source !== "companion") return;
    if (message.event === "job") renderJob(message.job);
    if (message.event === "disconnected") disconnected(message.error);
  });
  if (query.get("url")) {
    try { $("url").value = youtubeUrl(query.get("url")); } catch (error) { notice(error.message, true); }
  } else if (!fullView) useTab().catch(() => {});
  await connect();
} else {
  $("extension-id").textContent = "Available after loading the unpacked extension";
  $("install-command").textContent = ".venv\\Scripts\\python.exe scripts\\register_host.py --extension-id YOUR_EXTENSION_ID";
  disconnected("Preview only. Load extension/ through your browser's extensions page to use SaveIt4U.");
}
