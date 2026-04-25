# Video Recognition Results — 22_19_H_clip_9m30-15min_fixed.mp4

Analysis and best results from automated video-to-PGN runs (2 boards, full clip). Target: complete PGN for both boards with game result (1-0, 0-1, 1/2-1/2).

---

## Target Video

| Field | Value |
|-------|--------|
| **Path** | `algo/data/22_19_H_clip_9m30-15min_fixed.mp4` |
| **Output base** | `algo/data/22_19_H_clip_9m30-15min_fixed_auto_out/` |
| **Clip** | 9m30–15min (~5.5 min) |

---

## Best Result (so far)

**Run:** `run_1771391074`  
**Board moves:** board_0 = 1, board_1 = 6 (total 7)  
**Result:** Incomplete (both games `*`). Best achieved across 8h sweep.

### Parameters that produced this result

| Param | Value |
|-------|--------|
| **orientation** | `white` |
| **change_threshold** | `16.0` |
| **stability_frames** | `2` |
| **fps** | `2.5` |
| **skip_start** | `0` |

Config index in `run_video_recognition_auto.py`: 8th config (0-based: 7).

### PGN content

**Board 0** (1 move): `1. h3 {frame 4410, conf=high} *`

**Board 1** (6 moves): `1. f3 f5 2. e4 Nc6 3. Bc4 Rb8 *` (frames 384–4152)

Both PGNs parse and are legal. Games are truncated (no result).

---

## 8-hour run summary

- **Script:** `run_video_recognition_auto.py --video ... --timeout 8 --min-boards 2 --min-moves-per-board 20`
- **Attempts:** 1149 (10 configs cycled)
- **Outcome:** TIMEOUT. No run reached 20 moves per board.
- **Best:** board_0 max 1 move, board_1 max 6 moves.

### Parameter observations

- **Board 0** gets moves only with **lower threshold** (16–18); 0 moves with 20, 22, 25.
- **Board 1** best with **change_threshold=16**, **stability_frames=2**, **fps=2.5**.
- **Orientation white** gives more board_1 moves; **black** gives 1–2 moves on both but balanced.
- **Winning config:** white, threshold 16, stability 2, fps 2.5, skip_start 0.

---

## Gap vs goal

| Goal | Current | Gap |
|------|---------|-----|
| 2 boards with moves | Yes (1 + 6) | — |
| Game result (not *) | No | Need many more moves |
| Full clip coverage | No | Detection stops early |

---

## Human-in-the-loop (UI with full debug)

Use the algo video tracker UI to complete games with manual correction and full debug.

### 1. Start server (from algo repo)

```bash
cd /path/to/algo
.venv/bin/python live_recognition_server.py
```

Then open **http://localhost:8765/video** in the browser. Do a **hard refresh** (Cmd+Shift+R / Ctrl+Shift+R) so the debug row and latest UI load (no-cache is set; if debug row is missing, cache was stale).

### 2. Open video with best params

- **Video:** select `data/22_19_H_clip_9m30-15min_fixed.mp4`
- **Orientation:** White at bottom
- **Threshold:** 16 (best for this clip)
- **Stability:** 2
- **Board index:** 0

Click **Open**. First frame appears (raw + warped after calibrate).

### 3. Calibrate both boards

- **Board 0:** Board index = 0 → **Calibrate**. Check warped view: one board, 8×8 grid.
- **Board 1:** Board index = 1 → **Calibrate**. Check warped view: other board.
- Use **board tabs** or **Board index** to switch; each board has its own FEN and move history.

### 4. Step / Play with full debug

- **Step** (or **Play**) advances frames and runs the pipeline. After each step the UI shows:
  - **Debug row (top):** debug log (move candidates, scores, REJECTED/ACCEPTED), raw crop, ByteTrack grid, SAM2 if available.
  - **Cell diff heatmap** (bottom): per-cell change vs threshold.
  - **Move history:** accepted moves and failed attempts.
- Use the debug log to see why a move was rejected (e.g. score &lt; 40, wrong squares). Adjust **Threshold** / **Stability** and re-open if needed, or correct manually.

### 5. Correct and Save

- If the engine missed a move or got it wrong: set the **board editor** to the correct position (click cells, use piece picker, or paste FEN → Apply), then **Correct & Save**. That appends/updates the move in history and keeps PGN in sync.

### 6. Export PGN per board

- Switch to **Board 0** or **Board 1** (board selector / Board index).
- Click **Download PGN** (or GET `/api/video/pgn?board_id=N`). Save as e.g. `board_0_game.pgn`, `board_1_game.pgn`.

### Debug checklist

- **Debug row invisible:** Hard refresh; ensure server is run from algo dir so `video_tracker_ui.html` is the one in algo.
- **No move detected:** Check debug log for score and threshold; try Threshold 14–16, Stability 2.
- **Wrong move accepted:** Use Correct & Save with the right position.
- **Warped board wrong:** Re-calibrate on a clear frame; try another board index if the wrong region is selected.

---

## Future steps

1. **Tune for board_0:** Add change_threshold 14, 12; check calibration/homography for board_0.
2. **Extend move detection:** Try stability_frames=1, higher fps; inspect move rejection (scores, diff) in game_tracker.
3. **Calibration:** Confirm which camera region is board_0 vs board_1; check occlusion.
4. **Script:** Keep --min-boards 2; consider lower --min-moves-per-board for intermediate runs.
5. **Document:** Link this file from lessons/troubleshooting-log.md.

---

## References

- Script: `algo/scripts/run_video_recognition_auto.py`
- Batch: `algo/batch_video_tracker.py`
- cursor-context: `algo/video-tracker.md`, `rules/reco-pipeline.mdc`
- **Subagents (AI-only):** `~/.cursor/agents/video-recognition-manager.md`, developer, architect, qa
- **Subagents (human-in-the-loop):** `~/.cursor/agents/video-recognition-manager-hitl.md`, developer-hitl, architect-hitl, qa-hitl
