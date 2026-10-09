# Verification — SaveIt4U 0.2, 2026-10-09

## 0.2.2 YouTube session and Windows CI fix

- The failed Windows CI run 37959074328 compared two spellings of the same temporary folder: `RUNNER~1` versus `runneradmin`. The reconnect test now compares resolved paths.
- **56 Python and 9 JavaScript tests passed locally.** New regressions cover cookie scope and injection rejection, in-memory cookie jars, expiry/forget, cache invalidation, consent/sender authorization, permission denial, and errors without ANSI or CLI instructions.
- The 0.2.2 Setup EXE installed successfully in a workspace-only profile. With system runtimes removed from PATH, the actual native host exercised synthetic session share/forget, inspected `ARDiDYhDxRc` (13 qualities, 157 caption languages) and `F6oHV3ARAVg` (11 qualities, 157 languages), and downloaded a real video with both audio/video streams plus VTT/SRT/TXT/JSON exports. All final files were flat and warning-free.
- The browser transport adapter rendered the real extension dashboard against the new EXE. The reported Shorts URL was detected successfully under guest access in this environment. The UI refused sharing without the consent checkbox. Browser permission denial and cookie scope were tested with synthetic API fixtures.
- Session sharing is an explicit user action with optional YouTube-only permission. No actual account cookies were read by the verification tools. Account access and browser permission prompts still require a real Chrome/Edge acceptance check by the user.

## 0.2.1 Unicode hotfix

- Reproduced the user's exact Windows frozen-worker error on `F6oHV3ARAVg`: `charmap` could not encode `\u0101` at position 5008 even with `PYTHONIOENCODING=utf-8` set.
- The title was English. Its caption-language metadata included “Māori”; therefore English titles were also affected. The earlier English-only smoke fixture lacked this character and did not catch the regression.
- Worker JSON now writes UTF-8 bytes directly. Library-facing worker streams are explicitly configured to UTF-8, incoming worker JSON reads the binary stream, and diagnostic messages also avoid locale-dependent text encoding.
- **50 Python tests and 6 JavaScript tests passed**, including cp1252 text-wrapper regression cases for Urdu, Japanese, emoji, Māori caption names and Unicode diagnostics.
- The rebuilt frozen worker successfully inspected the same affected English video under an explicit cp1252 parent setting, returning all 11 quality options and the intact Māori caption name.
- The installed 0.2.1 EXE also passed the clean-PATH native smoke check: the affected English video returned 11 qualities and 157 caption languages, and a real video/audio download plus all four caption exports succeeded.
- Stable extension identity is unchanged. Existing extension pairing is preserved when updating the desktop application.

Test host: Windows 10 x64, Python 3.13.15, Node 24.19.0, yt-dlp 2026.8.19, EJS 0.8.0, psutil 7.2.2 and checksum-verified portable FFmpeg/FFprobe. Build tool: PyInstaller 6.22.3.

## Automated checks

- **48 Python tests passed.** Includes real media HTTP downloads, MKV/MP4 video+audio merging, source M4A and converted MP3, timestamped captions, native framing, authenticated named pipes, two-browser sessions, reconnect persistence, detached-heartbeat rejection, first-key creation races, unavailable/restricted network counters, aggregate video/audio progress, estimates, cached inspection coalescing, flat-title publication, collisions, recovery without modifying existing output, staged installation, tamper rejection, path-traversal rejection, rollback and update continuation.
- **6 JavaScript tests passed.** Includes native handshake coalescing, connection-loss recovery, preserved snapshots, stale-port rejection, URL restrictions, component sender authorization, response correlation and extension permissions.
- Actual temporary current-user Chrome, Edge and Chromium registry entries were written, read back and removed using unique test host names. Their manifests use the automatically computed stable origin; no extension ID input was needed. The user's normal native-host registration was left unchanged by those tests.
- JavaScript syntax checks, Python compilation and dependency consistency checks passed.

## Final EXE installation and live download

`scripts/smoke_windows.py --release-dir dist/final --live` completed successfully against the final packaged EXE.

- The EXE installer extracted and verified its payload into an isolated workspace installation with browser registration disabled for test isolation.
- System Python, Node and FFmpeg were removed from the child PATH. The installed app reported ready and located FFmpeg, FFprobe and Node exclusively under its own bundled directory.
- Real framed native messages connected to the frozen host and the authenticated shared engine. The engine reported **Connected** and accepted the selected output folder.
- A short public YouTube smoke fixture was inspected and downloaded through actual frozen worker processes.
- The final MKV contained both **video** and **audio**, verified with the **bundled** FFprobe.
- English captions exported to VTT, SRT, timed TXT and JSON. The final test completed with no user-facing warnings.
- All five final files were saved directly in one `SaveIt4U` folder, with the original title and no per-video output subfolders.

## Interactive integration check

The in-app browser ran the actual extension background, bridge, dashboard and content scripts through the clearly marked development browser transport adapter in `scripts/workflow_server.py`. Native framing, the packaged host EXE, IPC, YouTube extraction, workers, network counters, FFmpeg and publication were real.

- Watch and Shorts routes automatically opened the quality panel without using the toolbar or Find video.
- The panel showed actual available qualities and combined video/audio sizes.
- Clicking a quality started a real video+caption job in the background.
- A deliberate native-port interruption recovered automatically while preserving the saved job history and output files.
- A second same-title download produced `Me at the zoo (2).mkv` and matching `(2)` caption exports. The first files remained intact.
- The dashboard restored the saved jobs and showed connection and actual OS receive-rate telemetry.
- Integration checks found and fixed browser timer binding, shadow-panel style inheritance, a disconnect race and first-connection key-write concurrency. The visible panel now supports accessibility/browser tooling with an open shadow root while authorization remains in the isolated script, trusted clicks and current-tab checks.

## Limits of this verification

- The browser transport adapter substitutes Chrome's native-launch API. Actual Chrome/Edge **unpacked-extension installation and browser-to-host lookup in a real profile** still need a manual acceptance check. No Chrome Web Store/Edge publication occurred.
- The desktop EXE launched and exposed its native window. Native screenshot/control inspection was limited by the desktop helper's capture and foreground-window errors, so a complete graphical desktop QA pass is not claimed.
- Live high-resolution/long downloads and live large-file pause/resume were not manually exercised. Real format selection, aggregate progress and worker pause/resume/update continuation are covered by deterministic tests.
- The installer is unsigned. Publisher code signing, SmartScreen reputation and store distribution are public-release tasks, not completed checks.
- Historical 0.2 checks below were local. See the 0.2.2 record for the remote CI repair. Linux/macOS installer UX and Firefox support are not included.

These results describe the tested build and environment. Source quality, network/CDN limits, regional/account restrictions and future YouTube changes can affect individual downloads.
