# Verification — 2026-10-09

Verified on Windows with Python 3.13.15, Node 24.19.0, yt-dlp 2026.8.19, EJS 0.8.0 and the checksum-verified Gyan portable FFmpeg/FFprobe build.

- Python: 25 tests passed, including real yt-dlp downloads over loopback, FFmpeg MKV/MP4 merges, MP3 conversion, source M4A extraction, and caption-only export.
- JavaScript: 4 tests passed, covering URL restrictions, permissions, message routing, trusted senders, response correlation and disconnect handling.
- JavaScript syntax checks and Python dependency checks passed.
- Live YouTube inspection returned available formats and human caption languages for a public 19-second test video.
- A live video download produced an MKV with an AV1 video stream and Opus audio stream, confirmed by FFprobe.
- The video's English captions downloaded and exported to VTT, SRT, TXT and JSON. yt-dlp emitted a nonfatal impersonation warning during the caption request; all four exports succeeded.
- The interface was reviewed in the in-app browser using an explicitly marked simulated companion fixture. Shorts URL normalization, available-quality controls, MP4 quality caps, queue and setup rendering were checked. Those UI checks did not use browser native messaging.
- The extension ZIP passed its archive integrity check and contains no test fixtures, companion state, virtual environment or downloaded binaries.

**Still requires installation:** load `extension/` in Chrome/Edge, register the displayed extension ID and check the connection. Actual browser-to-host registration has not been exercised in this workspace. Native stdio framing and host command processing were verified in real subprocess tests. Linux/macOS installer paths and high-resolution live YouTube downloads have not been manually exercised. CI is provided but has not been run remotely.

These results describe the tested version and network environment, not a guarantee for all YouTube videos or future platform changes.
