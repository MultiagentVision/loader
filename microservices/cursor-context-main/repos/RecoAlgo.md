# RecoAlgo repo — detailed overview

**Purpose:** WTConv (Wavelet Convolutions for Large Receptive Fields, ECCV 2024). Research code for wavelet-based convolutions; used by **algo** repo for inference (e.g. corner or piece recognition). Subdir **wtconv/** is the main package.

---

## Layout

- **wtconv/** — Python package: WTConv2d, WTConv1d, integration with timm (e.g. wtconvnext_tiny). Semantic_segmentation in wtconv/semantic_segmentation/ (README).
- **wtconv/README.md** — usage, training, results, model links.

---

## Dependencies

- Python 3.12
- timm 1.0.7
- PyWavelets 1.6.0

---

## Usage (Python)

```python
from wtconv import WTConv2d
conv_dw = WTConv2d(32, 32, kernel_size=5, wt_levels=3)
```

Or via timm:

```python
import wtconvnext
model = create_model("wtconvnext_tiny", pretrained=False, num_classes=1000)
```

---

## Training (from README)

Example ImageNet training: `python train.py --model wtconvnext_tiny --drop-path 0.1 --data-dir IMAGENET_PATH --epochs 300 ...`. Distributed: torchrun --nproc-per-node=4 ...; effective batch size 4096 (gpus * batch-size * grad-accum-steps). WTConv1d added for TimePoint.

---

## Results and models

ImageNet-1K: WTConvNeXt-T/S/B; table with acc@1, params, FLOPs, drive links. See wtconv/README.

---

## Algo integration

Algo repo references RecoAlgo (e.g. `RecoAlgo/app/inference/corner_detector.py` or similar path). RecoAlgo may be a git submodule or sibling directory; ensure RecoAlgo is available on PYTHONPATH or sys.path when running algo inference. Algo uses it for detection/recognition in the pipeline.

---

## Source

Repo root and **wtconv/README.md** for API, training scripts, and model links.
