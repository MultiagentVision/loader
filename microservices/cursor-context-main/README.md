# Cursor Context & Rules

This repository contains the persistent context, rules, and knowledge base for AI agents working on the Chessverse project.

## 🧠 Rule Library (`.cursor/rules/`)

These `.mdc` files provide context-aware instructions to Cursor agents.

| Rule File | Description | Triggers |
|---|---|---|
| [`cluster-workflows.mdc`](rules/cluster-workflows.mdc) | Workflows for BGU SLURM cluster, training, and finding output. | `*.sbatch`, `slurm`, `cluster` |
| [`camera-network.mdc`](rules/camera-network.mdc) | NVR credentials, IPs, and RTSP URL patterns for BS and RG sites. | `rtsp`, `camera`, `nvr` |
| [`reco-pipeline.mdc`](rules/reco-pipeline.mdc) | Algo architecture, 480x480 constraints, and model details. | `pipeline.py`, `models`, `yolo` |
| [`cursor-troubleshooting.mdc`](rules/cursor-troubleshooting.mdc) | Fixes for UI blinking, file conflicts, stale git status, IDE glitches. | `blinking`, `bug`, `glitch`, `green` |
| [`knowledge-capture.mdc`](rules/knowledge-capture.mdc) | **META-RULE**: Protocol for agents to save new lessons. | `memorize`, `learn`, `save` |
| [`legacy-recognition.mdc`](rules/legacy-recognition.mdc) | Legacy video-to-PGN app: structure, branches, pipeline, model paths. | `legacy-recognition`, `monolith`, `video`, `PGN` |
| [`legacy-new-models.mdc`](rules/legacy-new-models.mdc) | Add TF.js models or call GPU endpoints (algo :8765). | `legacy-recognition`, `loadModels`, `gpu`, `endpoint` |
| [`jenkins-cicd.mdc`](rules/jenkins-cicd.mdc) | Jenkins + Harbor + ArgoCD CI/CD — image builds, registry, ApplicationSets. | `Jenkinsfile`, `jenkins`, `harbor`, `argocd` |
| [`cloudflare-access.mdc`](rules/cloudflare-access.mdc) | Shared CF Access tokens for CVAT, ClearML, registry, Jenkins — machine-to-machine. | `cloudflare`, `CF-Access`, `registry`, `cvat`, `clearml` |
| [`web-deployment.mdc`](rules/web-deployment.mdc) | Next.js deployment to Cloudflare Pages & external media handling. | `pages.dev`, `cloudflare`, `next.js` |
| [`landing-contact-form.mdc`](rules/landing-contact-form.mdc) | Landing contact form — Telegram + Web3Forms, env vars, secrets location. | `landing`, `leads`, `telegram`, `web3forms` |
| [`clearml-training.mdc`](rules/clearml-training.mdc) | ClearML on **bs3** first (`gpu_bs3`, RTX 5070 Ti): Vera pipeline, Tailscale MinIO `bs3:9000`, all-queue-on-bs3 `.env`, Vault PAT, pitfalls; other workers deferred. | `clearml`, `bs3`, `gpu_bs3`, `pipeline.py`, `model_train` |

## 📂 Artifacts

- **`examples/bs3-clearml-host-to-k8s-minio/`**: ClearML agent on **host** + MinIO **in Kubernetes** — ingress vs NodePort, `docker-s3-probe.sh` to test from the host.
- **`models/`**: Stores best-known-good model checkpoints (e.g., `yolo26_pieces.pt`).
- **`lessons/`**: Logs of troubleshooting sessions and ad-hoc learnings.
- **`training_status.md`**: Log of recent training runs and debugging sessions.
- **`secrets/`** (gitignored): Canonical credentials. Copy `*.env.example` → `*.env`, fill in. Used by agents and scripts (e.g. `landing.env`, `jenkins.env`).

## 🚀 How to Use
1.  **Sync**: Pull this repo to get the latest rules.
2.  **Install**: Copy rules to your active workspace:
    ```bash
    cp rules/*.mdc ../your-repo/.cursor/rules/
    ```
3.  **Reference**: In Cursor, simply ask questions like "How do I connect to the RG camera?" or "Where is the training output?" and the agent will load the relevant rule.
