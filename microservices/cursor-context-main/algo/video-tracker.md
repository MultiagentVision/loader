# Video-to-PGN multiboard (algo) — deep reference

Condensed but detailed reference for the file-based video tracker. Full task: `algo/docs/TASK_VIDEO_TO_PGN_MULTIBOARD.md`. Architecture and failure modes: `algo/docs/VIDEO_TRACKER_ARCHITECTURE.md`.

---

## Goal

Working video-to-PGN for **multiple boards**: open video → calibrate boards → step/play → export valid PGN per board. Input: one video file (e.g. MP4/H.265) with one or more physical boards. Output: one PGN per board.

---

## Repo and run

- **Repo:** algo.
- **Run:** `cd /path/to/algo && .venv/bin/python live_recognition_server.py` → `http://localhost:8765/video`.
- **UI:** `GET /video` returns `video_tracker_ui.html` with headers `Cache-Control: no-store, no-cache, must-revalidate, max-age=0`, `Pragma: no-cache`, `Expires: 0`. HTML path: `_VIDEO_TRACKER_UI_PATH = ALGO_DIR / "video_tracker_ui.html"`; server must run from algo so `ALGO_DIR` is algo repo root.

---

## API routes (video only)

| Method | Path | Purpose |
|--------|------|--------|
| GET | /video | Serve video_tracker_ui.html (no-cache) |
| POST | /api/video/open | Open video; body: path, orientation, start_fen, camera_id, board_index, change_threshold, stability_frames |
| GET | /api/video/list | List videos (e.g. ALGO_DIR/data) |
| GET | /api/video/frame | Get current frame |
| POST | /api/video/convert | Convert video |
| POST | /api/video/calibrate | Calibrate for current board_index; body: frame_no (optional) |
| POST | /api/video/flip | Flip board |
| GET | /api/video/state | Current state (FEN, move_history, etc.) |
| POST | /api/video/step | Advance one frame; run pipeline + debug pipeline |
| POST | /api/video/seek | Seek to frame |
| POST | /api/video/correct | Correct & Save move |
| POST | /api/video/export | Export (e.g. RNN-T) |
| GET | /api/video/boards | List boards (active_board, per-board FEN, etc.) |
| GET | /api/video/pgn?board_id=N | Export PGN for board N (default active_board) |
| POST | /api/video/play | Auto-step until move or max_steps (query: max_steps, skip) |

---

## _video_state keys (relevant to video flow)

- **cap** — cv2.VideoCapture
- **path** — video file path
- **frame_no**, **last_raw** — current frame index and numpy frame
- **H**, **rotation** — homography and rotation (global and per-board)
- **calibrated**, **n_boards**, **board_index** — calibration meta
- **boards** — `dict[int, dict]`: each key is board_index; value has `game_tracker`, `move_detector`, `piece_tracker`, `last_warped`, `H`, `rotation`, etc.
- **active_board** — int; which board is active for step/play
- **orientation**, **start_fen** — game options
- **move_detector**, **game_tracker** — used when no boards dict or fallback for PGN

Step/play read active board from `_video_state["boards"][active_board]` (or legacy move_detector/game_tracker). Calibrate writes into `_video_state["boards"][board_index]` and sets H, rotation, last_warped, move_detector, game_tracker for that board.

---

## Key modules and symbols

### live_recognition_server.py

- `_video_state` — global dict (no lock).
- `_vs_reset()` — clear state on open.
- `_VIDEO_TRACKER_UI_PATH`, `ALGO_DIR`.
- `_run_debug_pipeline(...)` — returns debug_log, raw_crop b64, bytetrack debug, sam2_debug (always set; if unavailable then `{"unavailable": "reason"}` or `{"error": "..."}`).
- Handlers: `video_tracker_page`, `video_open`, `video_calibrate`, `video_step`, `video_play`, `video_seek`, `video_pgn`, etc. Request models: `VideoOpenRequest`, etc.

### game_tracker.py

- **calibrate_from_frame(frame, board_index, ...)** — returns calibration dict (H, rotation, n_boards, etc.); uses board_warp and clustering.
- **warp_frame(frame, H, rotation)** — returns warped image.
- **split_into_cells(warped)** — 8x8 cells.
- **compute_cell_diff(ref_cells, cur_cells)** — diff for move detection.
- **MoveDetector** — ref_cells, stability, change_threshold, stability_frames; .update(cells) → detects move; .apply_move(san), .set_fen(fen).
- **GameTracker** — wraps board (python-chess), move_history (list of dicts: move_san, frame, squares, etc.); .get_board_array(), .board.fen().
- **cell_to_square(row, col, orientation)**, **square_to_cell(sq, orientation)** — coord mapping.
- **export_cell_crops**, **export_yolo_labels** — data export for training.

### board_warp.py

- **load_model(model_type)** — YOLO loader.
- **detect_xcorners**, **detect_xcorners_with_completion**, **detect_boards** — board/corner detection.
- **organize_points_into_grid**, **filter_to_49_points**, **build_destination_grid(output_size=480)**.
- **warp_board**, **warp_board_from_xcorners**, **warp_board_with_completion**, **warp_and_orient_board** — warp and orient.
- **detect_orientation(warped)**, **rotate_board(img, rotation)**, **detect_grid_offset**, **refine_warp_alignment**.
- **draw_8x8_grid**, **draw_points** — debug drawing.
- **process_single_image**, **process_directory** — CLI.

### piece_tracker.py

- **TrackedPiece**, **OccupancyChange**, **TrackingResult** — data classes.
- **ChessPieceTracker** — ByteTrack-based; .update(detections), returns tracking result; CELL_PX for bbox→cell.
- **_bbox_to_cell(bbox, cell_px)** — map detection to cell.

### batch_video_tracker.py

- **BoardPipeline** — per-board: homography, move_detector, game_tracker, piece_tracker; .process_frame(frame), etc.
- **export_pgn(gt: GameTracker, path, event=, board_id=)** — writes PGN to path, returns PGN string; used by GET /api/video/pgn.
- **run_batch(args)** — CLI batch run.
- **OUTPUT_SIZE = 480**.

### sam2_segmenter.py

- Optional; used in debug pipeline. Server sets `sam2_debug` to data or `{"unavailable": "..."}` / `{"error": "..."}` so client never gets missing key.

---

## Current behavior (concise)

- **Open:** POST /api/video/open with path, board_index. Creates cap, reads first frame, runs YOLO/calibration for that board_index; populates _video_state (frame_no, last_raw, boards[board_index] or legacy move_detector/game_tracker).
- **Calibrate:** POST /api/video/calibrate; uses current frame from _video_state; stores H, rotation, move_detector, game_tracker, piece_tracker, last_warped in _video_state["boards"][board_index] (and legacy keys for single-board).
- **Step:** POST /api/video/step; advances cap, warps active board, runs MoveDetector + GameTracker, optional debug pipeline; returns FEN, move_history, raw/warped b64, debug_*.
- **Play:** POST /api/video/play; loop of step until move or max_steps.
- **PGN:** GET /api/video/pgn?board_id=N; from boards[N].game_tracker or _video_state.game_tracker; batch_video_tracker.export_pgn(gt, tmp, event=, board_id=); returns text/plain with Content-Disposition attachment.

Only **active** board is updated on step/play. Multiboard: user must switch active_board and calibrate/play per board, or server must be extended to step all boards each frame.

---

## Known gaps and failure modes

- **UI / cache:** Debug row invisible → browser cache or server run from wrong dir. Fix: no-cache on GET /video; run from algo; hard-refresh (Cmd+Shift+R). Debug row: first child of .main, grid-row: 1.
- **Single global _video_state:** No session; no lock. Multiple tabs/users overwrite. Mitigation: asyncio lock around all video_* handlers; optional session isolation.
- **Blocking event loop:** Pipeline CPU-bound (cv2, YOLO, SAM2). Mitigation: asyncio.to_thread(pipeline) or process pool.
- **Multiboard:** Step/play update only active board. For “PGN for all boards” either calibrate+play each board in turn or extend server to run pipeline for every board each frame.
- **Move detection:** Wrong/missed moves → wrong PGN. “Correct & Save” (POST /api/video/correct) updates GameTracker; export_pgn uses move_history.
- **Path traversal:** Open accepts path; if relative, ALGO_DIR / path. Validate path is under ALGO_DIR or configured media root.
- **SAM2 optional:** Server always returns sam2_debug (data or unavailable/error); client should check before rendering.

---

## Acceptance criteria (working)

1. Open video, select board index, calibrate; step/play update active board FEN and move_history; raw/warped view and UI match backend.
2. Switch board; GET /api/video/pgn?board_id=N returns valid PGN for each calibrated board; optional “Download all PGNs” (e.g. ?board_id=all or zip).
3. Exported PGN parseable (e.g. python-chess), legal moves; “Correct & Save” reflected in PGN.
4. UI at http://localhost:8765/video loads without stale cache; debug row visible; server started from algo.

---

## Implementation order (suggested)

1. Verify UI: GET /video no-cache, debug row first in .main, hard refresh.
2. Optional: step/play update all calibrated boards each frame.
3. PGN “download all” (e.g. GET /api/video/pgn?board_id=all → zip or multi-download).
4. Move detection tuning; ensure Correct & Save updates move_history and export_pgn uses it.
5. asyncio lock around _video_state and pipeline; optional session isolation.

---

## Auto mode (3h retry until recognized)

For unattended runs when a video fails with 0 moves:

```bash
cd algo && .venv/bin/python scripts/run_video_recognition_auto.py --video data/game.mp4 --timeout 3
```

Tries different orientations, thresholds, fps, skip-start until at least 1 move is recognized or timeout. Fixes corrupted video start via ffmpeg trim. **Skill:** `video-recognition-auto`.

---

## References (files in algo)

- **Task:** `docs/TASK_VIDEO_TO_PGN_MULTIBOARD.md`
- **Architecture:** `docs/VIDEO_TRACKER_ARCHITECTURE.md`
- **UI:** `video_tracker_ui.html` — toolbar, .main grid, debug row (id=debugRow), transport, board editor, move history, PGN button; JS updateDebugRow, downloadPGN.
- **Server:** `live_recognition_server.py` — search _video_state, _vs_reset, video_open, video_calibrate, video_step, video_play, video_seek, video_pgn, _run_debug_pipeline, VideoOpenRequest.
- **Batch:** `batch_video_tracker.py` — BoardPipeline, export_pgn, run_batch.
- **Game:** `game_tracker.py` — calibrate_from_frame, warp_frame, MoveDetector, GameTracker, move_history.
- **Warp:** `board_warp.py` — detect_boards, warp_board, warp_and_orient_board.
- **Pieces:** `piece_tracker.py` — ChessPieceTracker.
