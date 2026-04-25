# Algo repo — detailed overview

**Purpose:** Chess recognition pipeline: live RTSP cameras and file-based video, board detection, piece detection, move detection, PGN export. Single-board and multiboard (tournament) setups.

**Entrypoint:** `live_recognition_server.py` — single FastAPI app (uvicorn). Serves video tracker UI at `GET /video`; exposes cameras API, video API, annotations, training, and dataset gallery.

## Run (file-based video tracker)

```bash
cd /path/to/algo
.venv/bin/python live_recognition_server.py
```

Default port 8765. Open `http://localhost:8765/video`. Server **must** run from algo dir so `ALGO_DIR = Path(__file__).resolve().parent` points to algo and `video_tracker_ui.html` is loaded from there.

## Paths and constants (live_recognition_server.py)

- `ALGO_DIR = Path(__file__).resolve().parent`
- `_VIDEO_TRACKER_UI_PATH = ALGO_DIR / "video_tracker_ui.html"`
- Video list scans `ALGO_DIR / "data"` (or configured dir). Open accepts relative path → resolved as `ALGO_DIR / path`.

## Key modules (top-level in algo)

| File | Purpose |
|------|--------|
| `live_recognition_server.py` | FastAPI app, `_video_state`, `_sam2_segmenter`, `_sam2_init_error`; all routes |
| `board_warp.py` | YOLO load_model, detect_xcorners, detect_boards, warp_board, warp_and_orient_board, detect_orientation, refine_warp_alignment; OUTPUT_SIZE 480 |
| `game_tracker.py` | calibrate_from_frame, warp_frame, split_into_cells, compute_cell_diff, MoveDetector, GameTracker, cell_to_square, square_to_cell, export_cell_crops, export_yolo_labels, run_pipeline |
| `piece_tracker.py` | TrackedPiece, OccupancyChange, TrackingResult, ChessPieceTracker (ByteTrack), _bbox_to_cell, CELL_PX |
| `batch_video_tracker.py` | BoardPipeline (per-board state), export_pgn(gt, path, event=, board_id=), run_batch |
| `sam2_segmenter.py` | SAM2 integration (optional) |

## Directory layout

- `live_recognition_server.py`, `video_tracker_ui.html` — server and UI
- `board_warp.py`, `game_tracker.py`, `piece_tracker.py`, `batch_video_tracker.py`, `sam2_segmenter.py` — core pipeline
- `run_qa_camera.py`, `train_pieces_yolo26.py`, `rnnt_dataset_exporter.py` — scripts
- `slurm/` — batch_generate_training.sbatch, download_gdrive.sbatch, finetune_pieces_yolo26.sbatch, train_raw_pieces_yolo26.sbatch, merge_calibration_data.py, etc.
- `calibration_data/`, `cell_detect/` — YOLO train/val data and labels
- `docs/` — VIDEO_TRACKER_ARCHITECTURE.md, TASK_VIDEO_TO_PGN_MULTIBOARD.md
- `RecoAlgo/` — submodule or symlink; e.g. RecoAlgo/app/inference/corner_detector.py
- `data/` — default dir for video list (videos to open)
- `.venv/` — Python venv; use `.venv/bin/python` to run server

## Camera API (RTSP, separate from file video)

- `GET /`, `GET /debug` — HTML pages
- `GET /api/health`
- `GET /api/cameras` — list CameraInfo
- `POST /api/cameras/{camera_id}/capture` — RecognitionResult
- `POST /api/cameras/{camera_id}/recalibrate`, `POST .../calibrate-position`
- `GET /api/cameras/{camera_id}/frame`, `GET .../state`
- `POST /api/validate-fen`, `POST /api/cameras/{camera_id}/save-annotation`
- `GET /api/annotations/stats`, `GET /api/annotations/review`
- `POST /api/models/reload`
- `GET /api/dataset/gallery`
- `POST /api/train/launch`, `GET /api/train/status`, `GET /api/train/log`

Helpers: `_rebuild_camera_map`, `_get_reco_pipeline`, `infer_fen_detailed`, `infer_fen_yolo26`, `calibrate_camera`, `run_recognition`, `annotate_frame`. Pydantic: CameraInfo, CellResult, BoardResult, RecognitionResult, SaveAnnotationRequest, ValidateFenRequest, TrainLaunchRequest.

## Video API (file-based; used by /video UI)

- `GET /video` — HTML (video_tracker_ui.html), Cache-Control no-store
- `POST /api/video/open` — body: path, orientation, start_fen, camera_id, board_index, change_threshold, stability_frames
- `GET /api/video/list` — list video files (e.g. from data/)
- `GET /api/video/frame` — current frame (query params)
- `POST /api/video/convert` — optional conversion
- `POST /api/video/calibrate` — body: frame_no (optional); uses _video_state["frame_no"], ["last_raw"]; sets H, rotation, calibrated, n_boards, board_index, boards[bid], last_warped, move_detector, game_tracker, etc.
- `POST /api/video/flip`
- `GET /api/video/state`
- `POST /api/video/step` — advance one frame, run pipeline + debug pipeline
- `POST /api/video/seek` — seek to frame
- `POST /api/video/correct` — "Correct & Save" move correction
- `POST /api/video/export` — export (e.g. RNN-T)
- `GET /api/video/boards` — list boards state
- `GET /api/video/pgn?board_id=N` — export PGN for board N (or active); uses batch_video_tracker.export_pgn(gt, tmp, event=, board_id=)
- `POST /api/video/play` — auto-step until move or max_steps

## _video_state (global dict) — keys used

- `cap` — cv2.VideoCapture (open video)
- `path` — video path
- `frame_no`, `last_raw` — current frame index and raw frame
- `H`, `rotation`, `calibrated`, `n_boards`, `board_index` — calibration (also per-board in boards)
- `boards` — dict[board_index, { "game_tracker", "move_detector", "piece_tracker", "last_warped", ... }]
- `active_board` — which board is active for step/play
- `orientation`, `start_fen` — game options
- `move_detector`, `game_tracker` — legacy/single-board (when boards not used)
- Reset via `_vs_reset()` on open.

## Video tracker UI (video_tracker_ui.html)

Single HTML file; no build. Toolbar (Open, Board #, Calibrate, Step, Play, Seek), main grid: debug row (Action log, Raw crop, Warped+pieces, ByteTrack, SAM2), raw frame + warped board, transport, board editor / move history / cell diff. JS: fetch /api/video/*, updateDebugRow(data), downloadPGN() → GET /api/video/pgn. Debug row must be first grid row (grid-row: 1), first child of .main.

## Dependencies

Python 3.x; opencv-python (cv2); ultralytics (YOLO); supervision (ByteTrack); python-chess; numpy. Optional: sam2; RecoAlgo (inference). See requirements.txt.

## Video-to-PGN multiboard (deep dive)

See [../algo/video-tracker.md](../algo/video-tracker.md) in this context repo for full API list, symbols in game_tracker/board_warp/piece_tracker/batch_video_tracker, gaps, acceptance criteria, and implementation order.

## Source of truth

- No top-level README. Use `docs/TASK_VIDEO_TO_PGN_MULTIBOARD.md` and `docs/VIDEO_TRACKER_ARCHITECTURE.md` for task and failure-mode detail.
