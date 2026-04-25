# State and concurrency lessons

Design lessons from in-process, single-process services (e.g. algo video tracker). These are design and mitigation patterns; implementation (lock, sessions, to_thread) lives in the respective repo, not in this context.

---

## Single global state

**Risk:** One shared dict (e.g. `_video_state`) for all clients or browser tabs. Tab B opens a different video or calibrates → overwrites Tab A’s state. Steps in Tab A can then use the wrong frame index, calibration, or board.

**Mitigation:** Session isolation. Key state by session ID (e.g. cookie or token); keep one state dict per session; evict idle sessions. Then each tab/user has its own video state and no cross-tab overwrite.

**Where it appears:** algo `_video_state` is a single global; no session id. See docs/VIDEO_TRACKER_ARCHITECTURE.md.

---

## No lock on shared state

**Risk:** Concurrent requests (e.g. open in one tab, step in another) read and write the same dict. Result: KeyError, inconsistent frame index, or torn reads (half-old, half-new state).

**Mitigation:** One asyncio lock (e.g. `_video_lock`) around every handler that reads or writes the shared state and around pipeline execution. Only one request mutates state or runs the pipeline at a time.

**Where it appears:** algo has no lock; VIDEO_TRACKER_ARCHITECTURE recommends a single lock for video_open, video_step, video_play, video_seek, and any handler that touches _video_state or runs the pipeline.

---

## Blocking CPU on the event loop

**Risk:** Heavy work (cv2, YOLO, SAM2) runs inside async request handlers. The event loop is blocked; other requests (health, list, other tabs) stall until the pipeline finishes.

**Mitigation:** Run the CPU-bound pipeline in a thread or process: e.g. `asyncio.to_thread(run_pipeline, ...)` or a process pool. Keep the event loop free so other requests stay responsive.

**Where it appears:** algo runs the full pipeline (warp, move detection, debug, SAM2) in the async handler; VIDEO_TRACKER_ARCHITECTURE suggests to_thread or process pool.

---

## Optional or failing services

**Risk:** A dependency (e.g. SAM2) is optional or fails to init. If the API omits a field or throws, clients that expect a fixed shape can break (e.g. script error or missing UI).

**Mitigation:** Server always returns a **defined shape**. E.g. `sam2_debug`: either the real data or a placeholder like `{"unavailable": "reason"}` or `{"error": "message"}`. Client checks for `unavailable` or `error` before rendering and shows a clear message instead of assuming the field is present.

**Where it appears:** algo now always sets sam2_debug (data or unavailable/error); client should check before use.

---

## Path traversal

**Risk:** User-supplied paths (e.g. video path in POST /api/video/open) can contain `..`. If the server resolves them against a base dir without validation, the resolved path can point outside the intended directory.

**Mitigation:** Resolve the path and ensure it is under a configured root (e.g. ALGO_DIR or a media root). Reject the request if the resolved path is outside that root. Do not trust user input as a direct filesystem path.

**Where it appears:** algo resolves path as ALGO_DIR / path when not absolute; VIDEO_TRACKER_ARCHITECTURE notes path traversal risk and recommends validating that the resolved path is under the root.

---

## Scope and implementation

These are design/lessons; the algo video tracker documents them in `docs/VIDEO_TRACKER_ARCHITECTURE.md`. As of the last update, lock and session isolation were not implemented; the doc is a roadmap for hardening. When implementing, add the lock first, then consider to_thread for the pipeline, then session isolation and path validation.
