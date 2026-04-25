# YOLO26 Pieces Training Investigation

## Status Check (2026-02-16)

### Findings
1. **Missing Job History**: Initially, `sacct` showed no history because it defaults to "today". Running `sacct -S 2025-01-01` revealed past jobs.
2. **Successful Training Job**:
   - **Job ID**: `14304268`
   - **Name**: `train_pieces`
   - **Status**: `COMPLETED` (Exit Code 0:0)
   - **Start**: 2026-02-06T16:49:30
   - **End**: 2026-02-07T06:02:45
   - **Duration**: ~13 hours
3. **Model Location**:
   - The output was found at a nested path: `/home/andreyl/git/algo/runs/detect/runs/pieces/yolo26_pieces_v110/weights/best.pt`
   - **Size**: 44 MB
   - **Date**: Feb 7, 06:02
   - **Why it was lost**: The training script likely appended `runs/detect` default path to the specified `--project runs/pieces`, creating a deep directory structure (`runs/detect/runs/pieces/...`).
4. **Current Deployment**:
   - The file at `/home/andreyl/git/algo/models/yolo26_pieces.pt` (and locally) is dated **Feb 5**, meaning it is the **OLD** broken model. The new model was never copied over.

### Plan
1. **Download** the correctly trained model from the cluster.
2. **Validate** it locally (check mAP/fitness).
3. **Deploy** it to `live_recognition_server.py`.

### Lessons Learned
- **Slurm History**: Always use `sacct -S <date>` to see jobs older than 24 hours.
- **Output Paths**: YOLO training can nest output directories unexpectedly (`runs/detect/...`). Check logs (`tail ...`) to find the actual "Results saved to" path.
- **Verification**: Always compare file timestamps. The presence of a file named `yolo26_pieces.pt` doesn't mean it's the *latest* training result.

### Log
- **2026-02-16**: Discovered successful job `14304268` and located missing model. Preparing to download.
