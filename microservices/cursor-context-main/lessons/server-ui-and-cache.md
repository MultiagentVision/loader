# Server-served UI: cache and path lessons

Lessons from “debug row not visible” and “UI didn’t change after deploy” in the algo video tracker. Apply to any server that serves a single HTML file or SPA that must reflect the latest deploy immediately.

---

## Problem

Users see an old UI (missing debug row, wrong layout, or “no change” after a deploy). Common causes:

1. **Browser cache** — The browser reused a cached copy of the HTML (or JS/CSS) from a previous request.
2. **Wrong server path** — The process was started from a different directory, so the server served a different file (e.g. an old copy of the HTML from another checkout or tree).
3. **Layout in cached version** — The cached HTML had the new section in a grid row that was below the fold or had zero height, so it was effectively invisible.

---

## Fixes applied (algo video tracker)

1. **No-cache headers on the HTML response**  
   For `GET /video`, the response includes:
   - `Cache-Control: no-store, no-cache, must-revalidate, max-age=0`
   - `Pragma: no-cache`
   - `Expires: 0`  
   So the browser does not cache the page; each reload fetches the current file from the server.

2. **Deterministic HTML path from server location**  
   The path to the HTML file is derived from the server’s own file location, e.g.:
   - `ALGO_DIR = Path(__file__).resolve().parent`
   - `_VIDEO_TRACKER_UI_PATH = ALGO_DIR / "video_tracker_ui.html"`  
   The same process always serves the HTML that lives next to the server script (e.g. in the algo repo). If the server is run from another tree, that other tree’s file is served—so run from the correct repo.

3. **Layout: critical UI above the fold**  
   The debug row is the first child of the main container and is assigned the first grid row (`grid-row: 1`). So it appears at the top of the main area and is visible without scrolling. In an older or cached layout where the row order differed, the debug row could end up off-screen.

---

## Operational checklist

- Start the server from the **repo root** that contains the UI file (e.g. algo). Avoid starting from a different cwd or a copy of the server elsewhere.
- After deploy or any HTML/asset change, have the user perform a **hard refresh** once: Cmd+Shift+R (macOS) or Ctrl+Shift+R (Windows/Linux) so any previously cached HTML is dropped.
- If “still not visible,” verify the response body of the HTML endpoint (e.g. GET /video) contains the expected block (e.g. id="debugRow") and that the server process is the one from the intended repo (e.g. check port, process cwd, or add a small version string in the UI).

---

## Generic lessons

- **Cache:** For HTML (or critical assets) that must update immediately on deploy, send strong no-cache headers. Optionally use versioned query strings (e.g. ?v=2) or ETag for cache invalidation.
- **Path:** Resolve the path to the HTML (or static root) from the server’s own location (e.g. `__file__` or `Path(__file__).resolve().parent`) so the correct repo/version is always served.
- **Layout:** Put critical UI (e.g. debug panel, status) in the first grid row or above the fold so it is visible without scrolling and is not hidden by viewport or older CSS.

---

## Reference (algo)

- `live_recognition_server.py`: `_VIDEO_TRACKER_UI_PATH`, `video_tracker_page()` (GET /video) with Response headers. `video_tracker_ui.html`: .main grid, first child debug row with grid-row: 1.
