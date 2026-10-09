/* Development-only browser fixture, served exclusively by preview_server.py. */
(() => {
  const listeners = [];
  const metadata = { id: "jNQXAC9IVRw", url: "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    title: "Into the mountains: a weekend worth keeping", channel: "SAVEIT4U UI FIXTURE", duration: 412,
    heights: [2160, 1440, 1080, 720, 480], mp4_heights: [1080, 720, 480], is_live: false,
    captions: [{ code: "en", name: "English", automatic: false }, { code: "ur", name: "Urdu", automatic: true }] };
  const state = { output_dir: "D:\\SaveIt4U-Demo", jobs: [] };
  const emit = message => listeners.forEach(listener => listener({ source: "companion", ...message }));
  window.chrome = { runtime: { id: "a".repeat(32), onMessage: { addListener: listener => listeners.push(listener) },
    sendMessage: async message => {
      if (message.action === "hello") return { ok: true, result: { ...structuredClone(state), ready: true, version: "UI fixture",
        dependencies: { yt_dlp: "Simulated", ejs: "Simulated", ffmpeg: "Simulated", ffprobe: "Simulated", runtime: "Simulated" } } };
      if (message.action === "inspect") return { ok: true, result: structuredClone(metadata) };
      if (message.action === "enqueue") {
        const job = { id: crypto.randomUUID(), request: message.request, title: metadata.title, status: "downloading", created: Date.now(),
          files: [], percent: 38.5, downloaded: 48_300_000, total: 125_000_000, speed: 4_100_000, eta: 19, warning: "", error: "", stream: "UI fixture" };
        state.jobs.push(job);
        emit({ event: "job", job });
        return { ok: true, result: structuredClone(job) };
      }
      if (["pause", "resume", "cancel"].includes(message.action)) {
        const job = state.jobs.find(item => item.id === message.job_id);
        job.status = { pause: "paused", resume: "downloading", cancel: "cancelled" }[message.action];
        emit({ event: "job", job });
        return { ok: true, result: structuredClone(job) };
      }
      if (message.action === "clear_finished") { state.jobs = state.jobs.filter(job => job.status !== "cancelled"); return { ok: true, result: structuredClone(state) }; }
      if (message.action === "configure") { state.output_dir = message.output_dir; return { ok: true, result: structuredClone(state) }; }
      return { ok: true, result: { simulated: true } };
    } }, tabs: { query: async () => [{ url: metadata.url }] } };
})();
