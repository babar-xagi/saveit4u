export function youtubeUrl(value) {
  if (typeof value !== "string" || value.length > 2048) throw new Error("Paste a YouTube video or Shorts link.");
  let url;
  try { url = new URL(value.trim()); } catch { throw new Error("Enter a valid HTTPS YouTube URL."); }
  if (url.protocol !== "https:" || url.username || url.password || url.port) throw new Error("Use an HTTPS YouTube link.");
  let id;
  if (url.hostname === "youtu.be") id = url.pathname.slice(1);
  else if (["youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"].includes(url.hostname)) {
    if (url.pathname === "/watch") {
      const ids = url.searchParams.getAll("v");
      id = ids.length === 1 ? ids[0] : "";
    } else id = url.pathname.match(/^\/(?:shorts|embed|live)\/([A-Za-z0-9_-]{11})\/?$/)?.[1];
  }
  if (!id || !/^[A-Za-z0-9_-]{11}$/.test(id)) throw new Error("Use an individual YouTube video or Shorts link.");
  return `https://www.youtube.com/watch?v=${id}`;
}
