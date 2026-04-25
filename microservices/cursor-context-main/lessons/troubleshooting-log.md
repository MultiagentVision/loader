# Troubleshooting & Lessons Learned Log

Entries use headings `## [YYYY-MM-DD] Title`. The file is ordered **newest first** (latest date at the top, oldest at the bottom). When appending a new lesson, add a new section **immediately below this paragraph** so it stays at the top; periodic cleanup can re-sort if dates end up out of order.

## [2026-04-03] Harbor large image push: worker disk, nginx buffering, CA rotation

- **Symptom**: `docker push` to `registry.multiagent.vision` retries GB layers forever; nginx access log shows **408** on PATCH, or **502** with `recv() failed (104: Connection reset by peer)` from `harbor-core`; earlier **503** / disk full on the worker node hosting Harbor.
- **Cause (disk)**: Registry data lived on the worker root filesystem (small VM disk, ~150 GB). Large images fill the node; Harbor or the OS runs out of space.
- **Fix (disk)**: On Proxmox, grow the worker VM’s main disk from the **thin pool** (e.g. +2 TB), then inside the guest: `growpart /dev/sdb 1` (or correct device) and `resize2fs` on the root/data partition. Use QEMU guest agent (`qm guest exec`) if SSH to the worker is awkward. Confirm with `df -h` inside the registry pod’s `/storage` mount.
- **Cause (ingress)**: RKE2 nginx ingress **buffers** the entire PATCH body to `/tmp/nginx/client-body/` before forwarding. Multi‑GB CUDA layers take minutes; **client_body** / idle timeouts fire → **408**; with streaming enabled, **harbor-core** could still reset if the path was wrong—primary fix is buffering off.
- **Fix (ingress)**: On `Ingress` `harbor/harbor-ingress`, set annotation `nginx.ingress.kubernetes.io/proxy-request-buffering: "off"` (and keep a generous `proxy-read-timeout` if already set). **Persist this in GitOps/Helm** so ArgoCD reapplies it; a manual `kubectl annotate` alone can drift when the app syncs.
- **Docker build host (bs3)**: If `/var/lib/docker` fills the root LV, move Docker **`data-root`** to a large mount (e.g. ext4 on an LV carved from the ~20 TB pool), `rsync` while Docker is stopped, update `/etc/docker/daemon.json`, restart Docker.
- **TLS after Harbor redeploy**: Helm/Argo rollouts can issue a **new** `harbor-ca`. `openssl s_client` often saves the **server leaf**, not the registry trust anchor—Docker then fails with `unknown authority`. Fetch the **root CA** with Harbor’s API: `GET /api/v2.0/systeminfo/getcert` (admin credentials), write to `/etc/docker/certs.d/registry.multiagent.vision/ca.crt`, run `update-ca-certificates`, **restart dockerd**, then retry push.
- **Routing (bs3 → worker)**: Ensure `registry.multiagent.vision` resolves to the **LAN** VIP or worker IP (`/etc/hosts` as in the Harbor setup entry). Tailscale table 52 can own `10.0.0.0/24`; add a high‑priority `ip rule` to `10.0.0.<worker>` → `lookup main` if pushes accidentally go slow path.
- **Image ref** (pre-baked ClearML runner): `registry.multiagent.vision/clearml/clearml-yolo-runner:8.4.30` — confirm current digest with `docker manifest inspect` after rebuilds.

## [2026-04-03] ClearML venv downloads CUDA wheels every run despite pre-baked image

- **Symptom**: Container logs show `Can't uninstall 'nvidia-cudnn-cu12' ... outside environment /root/.clearml/venvs-builds/3.12`. GB-scale CUDA wheel downloads on every task even after Harbor image is deployed.
- **Cause**: ClearML agent creates an **isolated virtualenv** at `/root/.clearml/venvs-builds/3.12`. By default it does NOT inherit system site-packages. The pre-baked image packages live in `/usr/local/lib/python3.12/dist-packages` (outside the venv), so pip reinstalls everything.
- **Fix**: Add `venv_params: ["--system-site-packages"]` to the `package_manager {}` block in `/root/clearml.conf`. The venv inherits all system packages; pip only installs what's missing or version-mismatched. Combined with baking `requirements.txt` into the Docker image, task setup becomes near-instant.
- **Persistent fix**: `infra/ansible/playbooks/templates/clearml-pve-agent-block.conf.j2` updated with the same `venv_params` line. Will survive the next Ansible deploy.

## [2026-04-03] ClearML Dataset.get() picks up unfinalized orphan — crash on get_local_copy

- **Symptom**: `ValueError: Cannot get a local copy of a dataset that was not finalized/closed`
- **Cause**: A previous failed run created a new child dataset (via `Dataset.create(..., parent_datasets=[...])`) but crashed before `finalize()`. Next run's `Dataset.get()` returned this unfinalized draft (it's the newest).
- **Fix**: Pass `only_completed=True` to `Dataset.get()` in `model_train/src/yolov8/data.py`. Also wrapped `new_dataset.delete()` in try/except so empty-draft cleanup doesn't crash the step.
- **Cleanup**: Delete orphan via ClearML internal API from bs3: `curl -sf http://100.114.215.51:9080/api/v2.30/tasks.delete -H "Authorization: Bearer $TOKEN" -d '{"task":"<id>","force":true}'`

## [2026-04-03] Harbor setup for ClearML on bs3

- **Projects**: `chessverse` (CI images), `clearml` (step runner images), `docker-proxy` (pull-through cache for Docker Hub)
- **Robot account**: `robot$clearml-runner` / see `/root/harbor-clearml.env` on bs3
- **Harbor admin password**: `Harbor12345` (from `harbor-core` k8s secret `HARBOR_ADMIN_PASSWORD`)
- **Harbor CA**: self-signed (`CN=harbor-ca`). Install on Docker hosts: `mkdir -p /etc/docker/certs.d/registry.multiagent.vision && openssl s_client -connect 10.0.0.202:443 -servername registry.multiagent.vision </dev/null 2>/dev/null | openssl x509 > /etc/docker/certs.d/registry.multiagent.vision/ca.crt`
- **LAN bypass**: Add `10.0.0.202 registry.multiagent.vision` to `/etc/hosts` — Docker daemon cannot send CF-Access headers so must hit LAN IP directly, not via Cloudflare
- **Harbor API from outside cluster**: Use `--resolve "registry.multiagent.vision:443:10.0.0.202"` with curl, or do it from inside bs3 where LAN IP is reachable
- **Docker Hub proxy**: `docker-proxy` project in Harbor (registry ID 1, type docker-hub). bs3 `daemon.json`: `"registry-mirrors": ["https://registry.multiagent.vision/v2/docker-proxy"]`
- **Pre-baked runner image**: `registry.multiagent.vision/clearml/clearml-yolo-runner:8.4.30` — built from `model_train/docker/Dockerfile.clearml-runner`, includes full `requirements.txt`

## [2026-04-03] MinIO in **Kubernetes** vs ClearML agent on **Proxmox host**

- **Reality**: RKE2 runs on Proxmox VMs; MinIO S3 is in-cluster (`minio` namespace). ClearML agent runs on a **host/VM** and executes step jobs as **Docker** on that host — not as k8s pods.
- **Broken assumptions**: `minio.minio.svc.cluster.local:9000` is unreachable from host Docker (no cluster DNS). `http://bs3:9000` only works if the S3 API actually listens on that host; if MinIO is **only** in k8s, host `:9000` is empty.
- **Works**: Expose MinIO to the host via **Ingress** (`https://s3.multiagent.vision` per `gitops/apps/infra/minio/ACCESS.md`), or **NodePort / LB** on an IP the host reaches (Tailscale/LAN). Align `AWS_ENDPOINT_URL` and `dataset_mappings.yaml` with that URL; use `PIPELINE_DOCKER_ADD_HOST_BS3=0` when not mapping a local MinIO.
- **Probe**: `cursor-context/examples/bs3-clearml-host-to-k8s-minio/docker-s3-probe.sh` (curl + aws-cli in disposable containers on the host).
- **Docs**: `examples/bs3-clearml-host-to-k8s-minio/README.md`, `rules/clearml-training.mdc` pitfall **7b**.

## [2026-04-03] ClearML docs: bs3 as primary worker (gpu_bs3), others deferred

- **Decision**: Focus ClearML **boards / model_train** work on **bs3** only — RTX 5070 Ti 16 GB (fastest GPU). Queue **`gpu_bs3`** for controller + all pipeline steps via `.env` until multi-host distribution is explicitly wanted.
- **Ops**: SSH `root@100.98.15.96`, `journalctl -u clearml-agent-gpu.service`, MinIO on same tailnet **`bs3:9000`** (not `s3.multiagent.vision`).
- **Deferred**: bs1, bs2, rg1–rg3 queues stay documented but not the default operating mode.
- **Updated**: `rules/clearml-training.mdc` (primary worker section, pipeline queue table, MinIO wording), `rules/cluster-workflows.mdc` (ClearML blurb), `README.md` rule table.

## [2026-04-03] ClearML pipeline: wrong `requirements.txt` (parent `train/` TF + numpy 1.23 on Python 3.12)

- **Symptom**: Controller task fails during `pip install -r .../microservices/train/requirements.txt` with `numpy==1.23.5` build / `pkgutil.ImpImporter` (setuptools) on **Python 3.12** in `ultralytics/ultralytics:latest`.
- **Cause**: ClearML agent auto-picked the **parent** service requirements (TensorFlow, `numpy==1.23.5` for older agents), not `model_train/requirements.txt` (uv export, py3.12-friendly).
- **Fix**: In `model_train/src/pipeline.py`, pass `packages=str(model_train/requirements.txt)` into `PipelineController(...)`, and call `task.set_packages(...)` on each step draft in `create_step_task` after `set_script`. That overwrites auto-detected packages so the agent only installs the model_train lockfile.
- **Artifact**: `chessverse-monorepo/microservices/train/model_train/src/pipeline.py`

## [2026-04-03] ClearML training: MinIO via Tailscale `bs3:9000`, not `s3.multiagent.vision`

- **Problem**: Pipeline / data_prep failed when step containers used `s3.multiagent.vision` (or `https://s3.multiagent.vision`) for MinIO/S3. Runners sit inside the **Tailscale** contour; the public hostname goes through Cloudflare / wrong path and breaks S3 API access from agents.
- **Fix**:
  1. **`.env`** (machine that runs `uv run src/pipeline.py`): `MINIO_ENDPOINT=bs3:9000`, `MINIO_SECURE=false`, `AWS_ENDPOINT_URL=http://bs3:9000` (plus same access keys as before). These vars are injected into every pipeline step’s Docker via `STEP_DOCKER_ARGUMENTS` in `pipeline.py`.
  2. **`config/dataset_mappings.yaml`**: `s3_source_uri` for boards → `s3://bs3:9000/chess-academia-boards-yolo/` (MagicDNS host for MinIO on bs3, port 9000).
  3. **`pipeline.py`**: `s3_source_uri` from the mapping is now passed into `pipe.add_parameter("s3_custom_uri", …)` so `DataConfig/s3_custom_uri` is no longer always empty (was preventing YAML MinIO path from reaching `add_external_files`).
- **Rule updated**: `cursor-context/rules/clearml-training.mdc` (Tailscale MinIO section + pitfall #7).
- **Artifacts**: `chessverse-monorepo/microservices/train/model_train/.env.example`, `config/dataset_mappings.yaml`, `src/pipeline.py`.

## [2026-04-03] Boards training via Vera's pipeline.py (ClearML PipelineController + cf_patch)

**Context**: Previous session established boards training with a simple `train_boards_clearml.py` script requiring Tailscale IP. Vera had already built a much more complete solution on branch `feature/model-train-yolo26n`.

### Steps & Lessons

**1. Discovered Vera's `model_train` pipeline**
- Branch: `remotes/origin/feature/model-train-yolo26n` (`verock@yandex.ru`)
- Location: `microservices/train/model_train/src/pipeline.py`
- Run command (PowerShell style Vera uses): `$env:TRIGGER_DATASET_NAME = "chess-academia-boards"; $env:PYTHONPATH = "."; uv run src/pipeline.py`
- This is a proper ClearML `PipelineController` with 4 ordered steps: `data_prep → model_training → export_and_test → generate_report`

**2. Key insight: `cf_patch.py` solves Cloudflare Zero Trust**
- `src/utils/cf_patch.py` monkey-patches `requests.Session.send` to inject `CF-Access-Client-Id` and `CF-Access-Client-Secret` on every request
- CF creds hardcoded as defaults: `31ac6b5b8358a3b78703ba425a5eab14.access` / `f739f3dc336681b46781f668c6d127462450d11d06c9a486828638909b59d5ed`
- **This means the public `https://clearml.multiagent.vision` URL works directly** — no Tailscale IP needed
- Every step script (`step_train.py`, `step_data.py`, etc.) calls `patch_clearml_requests()` at import time

**3. Dataset source: MinIO, not Roboflow**
- Dataset configured in `config/dataset_mappings.yaml` keyed by `TRIGGER_DATASET_NAME`
- `chess-academia-boards` → MinIO at `s3://chess-ai/models_train/boards/`, model `yolo26n`
- Agents receive MinIO credentials via Docker `-e` flags injected by the pipeline's `STEP_DOCKER_ARGUMENTS`

**4. Checking out model_train onto current branch**
- The directory didn't exist on `feat/train-video-splitter-service`
- Used: `git checkout remotes/origin/feature/model-train-yolo26n -- microservices/train/model_train/`
- This brings the full directory without switching branches

**5. uv not installed on Mac**
- Installed via: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Then: `export PATH="$HOME/.local/bin:$PATH" && uv sync` in the `model_train/` directory

**6. `.env` setup**
- Created `microservices/train/model_train/.env` with MinIO creds, ClearML API keys, CF creds, and all `PIPELINE_*_QUEUE=gpu_bs3` overrides
- `.env` is gitignored by the project's `.gitignore`

**7. Pipeline enqueued successfully**
- Task `c06ad9b7a2094268b4bc5bbb68348218` created
- bs3 agent picked it up within 30 seconds and started `ultralytics/ultralytics:latest` container with MinIO + Vault PAT injected
- UI: https://clearml.multiagent.vision/projects/32d241ed0d0d432fa1b72bb43a31d1ec/experiments/c06ad9b7a2094268b4bc5bbb68348218/output/log

**8. Auxiliary artifact upload 405 (non-blocking)**
- The git diff artifact upload to `https://clearml.multiagent.vision/files` returns 405
- This is a CF restriction on the files server for PUT/POST; only affects the auxiliary `auxiliary_git_diff.txt`
- The pipeline task still enqueues and runs normally

### Lesson
Always check if there's a proper `pipeline.py` in `microservices/train/model_train/` before writing a new training script. Vera's pipeline is the canonical approach: it handles dataset download, training, export, and report generation end-to-end, routes steps to appropriate GPU queues, and works with the public ClearML URL via `cf_patch.py`.

## [2026-04-03] ClearML Boards Training on bs3 — Full Setup Walkthrough

### Context
Needed to free VRAM on bs3 (RTX 5070 Ti 16 GB) and run YOLO11 boards training via ClearML.

### Steps & Lessons

**1. Undeploying Fooocus to free VRAM**
- **Problem**: Fooocus was consuming 2350 MiB VRAM via `fooocus.service` (systemd), leaving only ~13.5 GB free.
- **Solution**: `systemctl stop fooocus && systemctl disable fooocus` — freed VRAM to 501 MiB (only gpu-inference-service remains).
- **Lesson**: Fooocus runs as `fooocus.service`; WorkingDirectory=/opt/Fooocus, conda env `fooocus`. Re-enable with `systemctl enable --now fooocus`.

**2. ClearML task creation and enqueueing**
- **Training script**: Created `chessverse-monorepo/packages/coaching/train-app/python/train_boards_clearml.py`
  - Downloads Roboflow dataset: workspace=`chessacademiaboards-oafl9`, project=`chess-academia-boards`, version=1, format=`yolov11`
  - Trains `yolo11n.pt`, epochs=300, imgsz=640, batch=16
  - Uploads `best.pt` as ClearML artifact
  - ClearML project: `chess-academia`, task: `train-boards-yolo11n`
- **Enqueue**: `task.execute_remotely(queue_name='gpu_bs3', exit_process=True)` then run locally with internal Tailscale URL:
  ```bash
  CLEARML_API_HOST=http://100.114.215.51:8008 \
  CLEARML_WEB_HOST=http://100.114.215.51:9080 \
  CLEARML_FILES_HOST=http://100.114.215.51:9081 \
  CLEARML_API_ACCESS_KEY=... CLEARML_API_SECRET_KEY=... \
  python3 train_boards_clearml.py
  ```
- **Lesson**: Local `clearml.conf` uses `https://clearml.multiagent.vision/api` which is blocked by Cloudflare for direct Python SDK access. Must use internal Tailscale URL `http://100.114.215.51:8008`.

**3. CUDA image pull delay**
- **Problem**: First run on bs3: `docker ps` showed no container for ~4 minutes.
- **Root Cause**: `nvidia/cuda:12.2.2-cudnn8-runtime-ubuntu20.04` (~1.5 GB) was not cached on bs3.
- **Lesson**: First run always takes 5–10 minutes for image pull + conda/pip setup. Subsequent runs are faster (cached layers).

**4. Expired GitHub PAT — task failed during git clone**
- **Problem**: Task failed: `remote: Invalid username or token. Password authentication is not supported for Git operations.`
- **Root Cause**: A GitHub PAT was hardcoded in `deploy-clearml-agents.yml` and propagated to all runners' `clearml.conf`; it later expired. (Token value redacted from this log — store only in Vault.)
- **Solution**: See Vault section below.

**5. GitHub PAT moved to Vault**
- **Vault path**: `secret/jenkins/github` → key `clearml_github_pat` (same path as `token` and `mvat_github_pat` for Jenkins)
- **Write**: `kubectl exec -n vault vault-0 -- env VAULT_TOKEN="..." vault kv patch secret/jenkins/github clearml_github_pat=<PAT>`
- **Read for Ansible**: `export GITHUB_PAT=$(kubectl exec -n vault vault-0 -- env VAULT_TOKEN="$(kubectl get secret vault-token -n external-secrets -o jsonpath='{.data.token}' | base64 -d)" vault kv get -field=clearml_github_pat secret/jenkins/github)`
- **Ansible playbook** (`deploy-clearml-agents.yml`): removed hardcoded default, now fails loudly if `GITHUB_PAT` env is empty
- **Rule Updated**: `infra/.cursor/rules/clearml-agents-infra.mdc` — added "GitHub PAT for Agent Git Clone (Vault-backed)" section with rotate + deploy commands
- **Rule Created**: `cursor-context/rules/clearml-training.mdc`

## [2026-03-28] Jenkins — Vault PAT, `github-frontend`, and per-service `chessverse/*` jobs

- **Goal**: One Vault path **`secret/jenkins/github`** (`token`, `mvat_github_pat`) → ExternalSecret **`github-token`** → controller `envFrom` → JCasC **`jenkins-token`**, **`github-frontend`**, **`mvat-github-pat`**. Retire manual UI credential **`git-deploy-multiagent-ci token`** once CasC works.
- **Pre-existing K8s secret**: If **`github-token`** was created manually first, use ExternalSecret **`creationPolicy: Merge`** so keys sync without ownership errors; or patch the secret then let ESO refresh.
- **Vault without local CLI**: `kubectl exec -n vault vault-0 -- env VAULT_TOKEN=… vault kv put secret/jenkins/github …` with a token from **`external-secrets/vault-token`** (same as `ClusterSecretStore` `vault-backend`) — **never** commit PATs or tokens.
- **Per-service builds**: Nine **`pipelineJob`s under folder `chessverse/`** (e.g. `chessverse/bff`) share **`chessverse-monorepo/Jenkinsfile`**. **`SERVICE`** is inferred from **`JOB_NAME`** last segment (`SERVICE_FIXED`); multibranch **`chessverse-monorepo`** still uses the **`SERVICE`** parameter. **Update metadata** stage uses `branch('main')` **or** `SERVICE_FIXED != null`.
- **JCasC + Job DSL quirk**: Folder **`chessverse`** can appear while inner jobs from a Groovy `.each` do not; fix with **Script Console** Job DSL once or controller restart — see `repos/jenkins-github-pat-vault-rollout.md` §10.
- **Verify agents**: Kaniko pod names should include **`chessverse-<service>-…`** for per-service jobs.
- **Artifacts**: `gitops/apps/infra/jenkins/values.yaml` (`chessverse-services`, credentials), `templates/external-secret-github-token.yaml`, `chessverse-monorepo/Jenkinsfile`, `JENKINS_SETUP.md` §5b.
- **Rules / runbook**: `rules/jenkins-cicd.mdc`, `repos/jenkins-github-pat-vault-rollout.md`.

## [2026-03-28] CVAT UI "Cannot connect" — `/api/server/health/` 500 from disk usage (bs2 Docker)

- **Problem**: Browser at `https://cvat.multiagent.vision` shows **Cannot connect to the server** (Database/Redis/OPA message). Public checks with Cloudflare Access tokens on `/api/server/about` can still return **200**.
- **Root Cause**: CVAT’s SPA calls **`GET /api/server/health/?format=json&org=`**. Django **django-health-check** includes a **DiskUsage** check: when the **host (or visible mount) is above ~90%**, it raises `ServiceWarning`, which becomes **HTTP 500** on the health endpoint. DB/Redis/OPA can all be fine; Traefik access logs show **500** on `/api/server/health/` and **200** on `/api/server/about`.
- **Diagnosis (on host)**: SSH to CVAT Docker host (e.g. **bs2** / **ppd** — Tailscale `root@100.114.215.51`, LAN doc **10.0.0.5**). Run:
  - `curl -sS -w '\n%{http_code}\n' -H 'Host: localhost' 'http://127.0.0.1:8082/api/server/health/?format=json&org='`
  - `docker logs cvat_server --since 30m 2>&1 | grep -i health`
  - `df -h /` — if use is **≥ ~90%**, expect DiskUsage warning in logs.
- **Solution**: Free space on **`/`** (e.g. `docker image prune -af`, log rotation, remove old data) until usage is **below 90%**; health should return **200** and the UI loads.
- **Artifacts**: `infra/docs/EXTERNAL_ACCESS_CVAT_CLEARML.md`, `rules/cloudflare-access.mdc` (browser vs health vs disk).
- **Rule updated**: `rules/cloudflare-access.mdc` (health/disk note).

## [2026-03-27] MVAT branding, logo, LICENSE/NOTICE, Cloudflare Access

- **Logo**: UI header uses `/api/server/about` → `logo_url` from Django `LOGO_FILENAME`. Static file is `cvat/apps/engine/static/logo.png` (was `logo.svg`). Webpack copies `cvat-ui/src/assets/mvat-logo.png` to `/assets/mvat-logo.png` for `<link rel="icon">` in `cvat-ui/src/index.html`. `CVATIcon` in `icons.tsx` uses the same PNG (24×24). Hugo docs nav uses `site/assets/icons/mvat-logo.png` + `site/layouts/partials/navbar.html`.
- **Copy**: User-facing strings in `cvat-ui` were switched from CVAT to MVAT where safe. **Do not rename** export format labels `CVAT for video 1.1` / `CVAT for images 1.1` — they are API format identifiers.
- **License**: Root `LICENSE` is proprietary (Multiagent Vision). `NOTICE` retains upstream CVAT MIT copyright and terms. About modal links: License → GitHub `LICENSE`, Third-party notices → `NOTICE`, Multiagent Vision → `https://multiagent.vision`.
- **Access**: `mvat.multiagent.vision` uses the same Cloudflare Access application and service-token headers as other `*.multiagent.vision` hosts; verify with `curl` to `/api/server/about` (see `rules/cloudflare-access.mdc`).

## [2026-03-27] MVAT Jenkins — missing credential `mvat-github-pat` (build looked failed after Kaniko OK)

- **Problem**: Pipeline ended **FAILURE** even though Kaniko pushed images and webpack reported success. Log: `ERROR: Could not find credentials entry with ID 'mvat-github-pat'` in stage **Update deploy/metadata.yaml** (`withCredentials([string(credentialsId: 'mvat-github-pat', ...)])`).
- **Root Cause**: The `mvat/Jenkinsfile` expected a Jenkins **Secret text** credential that was never defined in GitOps JCasC. The controller also had no env `mvat_github_pat` (the `github-token` Kubernetes secret only had key `token`, not `mvat_github_pat`).
- **Solution**:
  1. **GitOps**: In `gitops/apps/infra/jenkins/values.yaml`, add JCasC `string` credential `id: mvat-github-pat` with `secret: "${mvat_github_pat}"`. Push `main`, hard-refresh ArgoCD app `jenkins` until **Synced** on that revision.
  2. **Cluster secret**: Add key **`mvat_github_pat`** to Secret **`github-token`** in namespace `jenkins` (same value as `token` works if that PAT can **push** to `MultiagentVision/mvat`). Patch example: copy `.data.token` to `.data.mvat_github_pat`, or re-run `setup-secrets.sh` with `MVAT_GITHUB_PAT` set.
  3. **Restart** Jenkins controller pod so CasC and `envFrom` reload (`kubectl delete pod -n jenkins jenkins-0` or delete by label `app.kubernetes.io/component=jenkins-controller`).
- **Do not** put `mvat_github_pat` on both `github-token` and `jenkins-credentials` (duplicate env keys on the controller).
- **Artifacts**: `gitops/apps/infra/jenkins/values.yaml`, `JENKINS_SETUP.md` §5a, `setup-secrets.sh`, `mvat/Jenkinsfile`.
- **Rule updated**: `rules/jenkins-cicd.mdc` (MVAT credential wiring).

## [2026-03-27] MVAT Jenkins — metadata stage: read-only deploy key → PAT

- **Problem**: `mvat/main` pipeline failed at **Update deploy/metadata.yaml** after Kaniko succeeded: `The key you are authenticating with has been marked as read only` on `git push`.
- **Root Cause**: GitHub deploy key `mvat-github-deploy-key` had no write access; `git` sidecar also lacked workspace (fixed earlier by using `jnlp`).
- **Solution**: Jenkins **Secret text** credential **`mvat-github-pat`** (classic PAT with `repo`). `Jenkinsfile` uses HTTPS `https://x-access-token:${GH_TOKEN}@github.com/MultiagentVision/mvat.git` in that stage. Local reference copy: `cursor-context/secrets/mvat-github-pat` (gitignored). **Rotate PAT if it was ever pasted in chat.**
- **Artifacts**: `mvat/Jenkinsfile`, `cursor-context/rules/jenkins-cicd.mdc`.

## [2026-03-20] Frontend K8s Deploy — Harbor Image Pull Chain (Cloudflare → TLS → Success)

- **Problem**: `frontend` pods stuck in `ErrImagePull` / `ImagePullBackOff` after switching from GHCR to Harbor (`registry.multiagent.vision`).
- **Root Cause chain**:
  1. **FailedPrecondition / size mismatch (32166 bytes)** — K8s worker nodes resolved `registry.multiagent.vision` to Cloudflare's CDN IP. Cloudflare returned a 32 KB Access challenge HTML page instead of the actual image layer. Containerd tried to store the HTML as an OCI blob → size mismatch.
  2. **x509: certificate signed by unknown authority** — After fixing DNS (nodes now hit `10.0.0.201` directly), Harbor presented its self-signed `harbor-ca` cert. Containerd doesn't trust it.
- **Solution**:
  1. **DNS bypass**: DaemonSet in `kube-system` (`node-harbor-hosts`) writes `10.0.0.201 registry.multiagent.vision` to each node's `/etc/hosts` via privileged init container + `hostPath: /`.
  2. **TLS skip**: Same DaemonSet writes `/etc/rancher/rke2/registries.yaml` with `insecure_skip_verify: true` for `registry.multiagent.vision`, then uses `nsenter -t 1 -m -u -n -i` to restart `rke2-agent` (workers) or `rke2-server` (master) in the host namespace. Alpine must install `nsenter` via `apk add util-linux`.
  3. **maxUnavailable: "100%"**: Required to unblock DaemonSet rolling update when the master node has broken Docker Hub DNS (can't pull `alpine`).
- **Key insight**: `hostAliases` in a pod spec only affects the container's `/etc/hosts` — it does NOT affect the kubelet/containerd image pull process, which uses the node's own DNS. Node-level `/etc/hosts` must be patched via a privileged DaemonSet.
- **Key insight**: Harbor self-signed cert (`CN = harbor-ca`) is not trusted by containerd. Use RKE2's `registries.yaml` with `insecure_skip_verify: true` + service restart. The `certs.d/hosts.toml` approach requires `config_path` to be set in containerd config (RKE2 may not set it).
- **Artifacts**: `gitops/apps/infra/fix-node-harbor-hosts.yaml`, `frontend/k8s/harbor-pull-secret.yaml`, `frontend/k8s/deployment.yaml`.
- **Harbor credentials**: admin / `Harbor12345`; robot `robot$chessverse+fe` / `3IguK0UCqUPdpFHwdtWxiSDJXnRyKr6l`.

## [2026-03-20] Frontend Domain Mismatch — app.multiagent.vision vs frontend.multiagent.vision + Vite 7 allowedHosts

- **Problem**: Visiting `https://frontend.multiagent.vision` showed Vite's "Blocked request. This host is not allowed." page instead of the app.
- **Root Cause**: Three separate issues:
  1. **Ingress hostname wrong**: `k8s/ingress.yaml` had `host: app.multiagent.vision` but the Cloudflare Tunnel routes traffic to `frontend.multiagent.vision`. The nginx pod was healthy but unreachable from the correct hostname.
  2. **Cloudflare Tunnel `mv-tunnel` dev route**: `frontend.multiagent.vision` was routed by a local Cloudflare Tunnel (`cloudflare-tunnel-config.yml`) to the Vite dev server on `localhost:5173`. Vite 5+ blocks requests from hosts not in `server.allowedHosts`. The tunnel runs as chess user: `cloudflared tunnel --config cloudflare-tunnel-config.yml run`.
  3. **Vite 7 `allowedHosts` type mismatch**: `allowedHosts: "all"` (string) does NOT work in Vite 7. It gets spread as `["a","l","l"]` (three chars). Only `allowedHosts: true` (boolean) or `allowedHosts: ["hostname1", ...]` (string array) are valid. The TypeScript type is `string[] | true`.
- **Solution**:
  1. Updated `frontend/k8s/ingress.yaml` host from `app.multiagent.vision` → `frontend.multiagent.vision`.
  2. Set `allowedHosts: true` (not `"all"`, not `["all"]`) in `vite.config.ts` `server` block.
  3. Restarted the local Vite dev server so it picks up the config change (Vite auto-reloads on config change when running).
- **Key insight**: The `mv-tunnel` Cloudflare Tunnel routes `frontend.multiagent.vision` and `aichess.games` to `localhost:5173`, `backend.multiagent.vision` to `localhost:3007`, etc. If the tunnel is down, traffic falls through to the main system tunnel (root cloudflared with `--token`), which routes to the K8s nginx ingress.
- **Key insight**: The Vite process must be started from `/home/chess/git/frontend` (not another directory) so it reads the correct `vite.config.ts`. Check with `readlink /proc/<pid>/cwd`.
- **Artifacts**: `frontend/k8s/ingress.yaml`, `frontend/vite.config.ts`.

## [2026-03-20] ArgoCD / Jenkins Auth — SSH Migration for GitHub

- **Problem**: ArgoCD and Jenkins both failed to access `MultiagentVision/frontend.git` and `MultiagentVision/chessverse-monorepo.git` with expired HTTPS PATs.
- **Solution**: Migrated all GitHub access to SSH (`git@github.com:MultiagentVision/...`). Used working ed25519 key `~/.ssh/id_ed25519_github`.
  - ArgoCD: added SSH repo credential via API.
  - Jenkins: created `github-ssh` credential (BasicSSHUserPrivateKey), updated job SCM URL, configured `GitHostKeyVerificationConfiguration` with GitHub's ED25519 host key via Groovy script console.
- **Key insight**: When ArgoCD has cached a stale HTTPS repoURL in the Application object, a hard refresh + sync of the PARENT app is needed to force reconciliation.

## [2026-03-20] ClearML Dataset Registration — S3 Listing "maximum recursion depth exceeded" via Cloudflare

- **Problem**: `Dataset.add_external_files()` failed with `maximum recursion depth exceeded` when listing files at `s3://s3.multiagent.vision:443/chess-ai/datasets/chess-academia-boards/baseline/`. Dataset could not be finalized. Tried: Cloudflare header injection via urllib3 patch, SKIP_STATS=1, multiple script rewrites — all failed.
- **Root Cause**: `s3.multiagent.vision` is served via Cloudflare Tunnel (proxmox-tunnel). When boto3 sends `ListObjectsV2`, Cloudflare intercepts and returns a redirect/challenge page (HTML) instead of S3 XML. boto3 follows the redirect, gets another redirect, and hits Python's recursion limit. This is NOT a credentials issue — it's a network-layer problem.
- **Solution**: Run dataset registration from a machine on the cluster network (bs2 / 100.114.215.51), bypassing Cloudflare:
  1. Add `/etc/hosts` entry: `10.0.0.201 s3.multiagent.vision` (points to nginx ingress directly)
  2. Write a `clearml.conf` with S3 credentials (`sdk.aws.s3.credentials` section) — ClearML SDK needs this for its own S3 handler during `add_external_files()`
  3. Use `add_external_files(source_url="s3://s3.multiagent.vision/chess-ai/datasets/.../")` with the folder URL (SDK lists and adds all files in one call)
  4. Call `dataset.upload()` before `dataset.finalize()` (required even for external files)
  5. Remove `/etc/hosts` entry after registration
- **Key Insights**:
  - ClearML `add_external_files()` uses its own S3 storage handler (not raw boto3) — needs credentials in `clearml.conf` under `sdk.aws.s3.credentials`, not just env vars
  - Connecting to `https://10.0.0.201` directly returns 404 — nginx ingress needs the correct `Host: s3.multiagent.vision` header, so use `/etc/hosts` override instead of IP-based endpoint
  - `dataset.upload()` must be called before `finalize()` even for external-only datasets
  - The same Cloudflare issue applies to any S3 API call (ListObjects, GetObject) made from outside the cluster — agents work because they could use internal DNS
- **Artifacts**: `infra/scripts/register-clearml-dataset-internal.py`, `infra/scripts/diagnose-s3-listing.py`
- **Dataset registered**: ID `511bae9e7e6b4e7799ed9b5b2c799f53`, project `chess-academia-boards`, name `baseline`, 2002 files

## [2026-03-04] Jenkins Frontend Pipeline — Kaniko /var/run Read-Only Failure → SUCCESS

- **Problem**: Jenkins frontend job "Build and Push" failed with `chmod: /var/run/secrets/kubernetes.io/serviceaccount: Read-only file system` during Docker build.
- **Root Cause**: Dockerfile had `chmod -R 755 /var/run` and `chown -R nginx:nginx /var/run`. Kaniko runs inside a K8s pod where `/var/run/secrets/kubernetes.io/serviceaccount` is a read-only mount; recursive chmod/chown fails.
- **Solution**: Remove `/var/run` chmod/chown from the Dockerfile. Only nginx cache dirs need permissions; the nginx:alpine base image already sets up `/var/run` for the PID file.
- **Artifacts**: `frontend/dockerfile`
- **Result**: Build #7 succeeded. Image pushed to `registry.multiagent.vision/chessverse/frontend:sha-<commit>` and `:latest`.
- **Rule Updated**: `rules/jenkins-cicd.mdc` (Kaniko Dockerfile constraint).

## [2026-03-03] Jenkins Build and Push — Full Fix (UNAUTHORIZED → S3 → SUCCESS)

- **Problem**: Jenkins "Build and Push" stage failed with `UNAUTHORIZED: authentication required` or `invalid character '<'` (HTML) or `DriverName:s3aws RequestFailure` (S3).
- **Root Cause**: (1) Kaniko cannot send CF headers; `registry.multiagent.vision` returns HTML for token endpoint. (2) `harbor-registry:5000` returns UNAUTHORIZED for robot accounts (auth not validated). (3) Harbor S3 used placeholder credentials; MinIO bucket `harbor-registry` did not exist.
- **Solution**:
  1. **Jenkinsfile**: Use `REGISTRY=registry.multiagent.vision` with `hostAliases: registry.multiagent.vision → 10.0.0.201` (ingress IP) to bypass CF for token; add `--skip-tls-verify` for Kaniko.
  2. **harbor-credentials** secret: `docker-server=registry.multiagent.vision`, username `robot$chessverse+<name>`, password = robot token.
  3. **Harbor S3**: Create `harbor-registry-s3` secret with `REGISTRY_STORAGE_S3_ACCESSKEY` and `REGISTRY_STORAGE_S3_SECRETKEY` from MinIO; Harbor values use `existingSecret: harbor-registry-s3`.
  4. **MinIO bucket**: Create `harbor-registry` bucket (s3-console or `aws s3 mb s3://harbor-registry --endpoint-url https://s3.multiagent.vision`).
- **Artifacts**: `chessverse-monorepo/Jenkinsfile`, `gitops/apps/infra/harbor/values.yaml`, `gitops/apps/infra/jenkins/HARBOR_SETUP.md`, `gitops/apps/infra/jenkins/JENKINS_SETUP.md`.
- **Rule Updated**: `rules/jenkins-cicd.mdc` (Harbor push setup).

## [2026-03-03] Chat Summary — Jenkins CI E2E Setup

**Goal**: Replace GitHub Actions with Jenkins + Harbor + ArgoCD; validate e2e.

**Done**:
1. **timestamps() fix**: Removed from Jenkinsfile (plugin not installed).
2. **Cloudflare Access fix**: Kaniko push failed because `registry.multiagent.vision` returns HTML login page. Switched to internal Harbor URL `harbor-core.harbor.svc.cluster.local` for in-cluster push; updated `harbor-credentials` secret.
3. **Multibranch pipeline**: `chessverse-monorepo` — branches `main`, `feature/AI-446-...` discovered.
4. **CF Access tokens**: Same tokens for all services (CVAT, ClearML, registry, Jenkins). Rule: `cloudflare-access.mdc`; secrets: `secrets/cloudflare-access.env`.

**Paths**: `gitops/apps/infra/jenkins/`, `chessverse-monorepo/Jenkinsfile`, `cursor-context/rules/jenkins-cicd.mdc`, `cursor-context/rules/cloudflare-access.mdc`.

**Harbor internal URL**: `harbor-core` returns HTML (portal); use `harbor-registry.harbor.svc.cluster.local:5000` for Docker API v2 push.

**Next**: Trigger build at https://jenkins.multiagent.vision/job/chessverse-monorepo/job/main/ → Build Now; verify image in Harbor; confirm ArgoCD deploys.

## [2026-03-03] Jenkins API Trigger — CF Tokens + Cookies for Crumb

- **Problem**: Triggering Jenkins build via API from outside returned 403 "No valid crumb was included in the request".
- **Root Cause**: Jenkins crumb is session-bound. The crumb request and the build POST must share the same HTTP session (cookies).
- **Solution**: Use `curl -c /tmp/jc.txt -b /tmp/jc.txt` for both requests. Include CF-Access-Client-Id and CF-Access-Client-Secret headers (jenkins.multiagent.vision is behind Cloudflare Access).
- **Rule Updated**: `rules/cloudflare-access.mdc` (added Jenkins trigger example).

## [2026-03-03] Cloudflare Access — Shared Tokens for All Services

- **Fact**: The same CF Access service token is used for all *.multiagent.vision services (CVAT, ClearML, registry, Jenkins, etc.).
- **Headers**: `CF-Access-Client-Id` and `CF-Access-Client-Secret` for machine-to-machine access.
- **Token location**: `cursor-context/secrets/cloudflare-access.env` (gitignored); doc: EXTERNAL_ACCESS_CVAT_CLEARML.md.
- **Rule Created**: `rules/cloudflare-access.mdc`

## [2026-03-03] Jenkins CI/CD Pipeline Implementation

- **Context**: Migrate from GitHub Actions to self-hosted Jenkins to avoid March 2026 billing ($0.002/min for self-hosted runners).
- **Jenkins admin**: `admin` / `Chess2510!` (stored in credentials.md)
- **Flow**: Code push → Jenkins (Kaniko) → Build image → Push to Harbor → ArgoCD ApplicationSets pick up image tags from repo metadata (no gitops update).
- **Artifacts**: `gitops/apps/infra/jenkins/`, `gitops/charts/chessverse-service/`, `gitops/apps/chessverse/chessverse-production-appset.yaml`, `chessverse-monorepo/Jenkinsfile`, `chessverse-monorepo/Jenkinsfile.preview`, `chessverse-monorepo/deploy/metadata.yaml`.
- **Rule Created**: `rules/jenkins-cicd.mdc`
- **Post-deploy**: Add jenkins.multiagent.vision to Cloudflare Tunnel; create Harbor robot account; configure Jenkins multibranch pipelines and GitHub webhook; retire ARC after validation.

## [2026-03-02] Stale Git Status — Folder Green When Clean
- **Problem**: cursor-context (and rag) showed green in sidebar; `git status` was clean.
- **Root Cause**: Cursor's git state cache stale in multi-root workspace.
- **Solution**: `Cmd+Shift+P` → Developer: Reload Window.
- **Rule Updated**: `rules/cursor-troubleshooting.mdc` (added "Stale Git Status" section).

## [2026-03-02] Web3Forms error 1106 from Cloudflare Pages Function
- **Problem**: After deployment, leads API returned `{ ok: true, channels: { telegram: "ok", web3forms: "error" }, errors: { web3forms: "error code: 1106" } }`. Telegram worked; email failed.
- **Root Cause**: Cloudflare error 1106 = "Access Denied: Your IP address has been banned." Cloudflare Pages Functions use shared Cloudflare IPs for outbound requests. Web3Forms (or their CDN) blocks those IPs.
- **Solution**: Migrated from Web3Forms to Resend. Resend uses API key auth (no IP allowlisting), works from Cloudflare Workers/Pages, and is Cloudflare's official recommendation. Free tier: 100 emails/day.
- **Artifacts**: `landing/functions/api/leads.js`, `landing/.env.example`, `cursor-context/rules/landing-contact-form.mdc`
- **Rule Updated**: `rules/landing-contact-form.mdc` — now documents Resend, env vars, and domain verification.

## [2026-02-22] Missing Videos on Next.js Static Export to Cloudflare Pages
- **Problem**: Large `.mp4` video files were not displaying on the live Cloudflare Pages deployment, despite working locally. Next.js tried to load them from the domain root.
- **Root Cause**: The media files are intentionally not bundled in the repo; they live on `s3.multiagent.vision`. We forgot to pass the `NEXT_PUBLIC_MEDIA_BASE_URL` environment variable during the GitHub Action build step, so Next.js compiled static paths locally.
- **Solution**: Updated `deploy.yml` GitHub Action to inject `env: NEXT_PUBLIC_MEDIA_BASE_URL: https://s3.multiagent.vision` during `npm run build`. This allows the static export (`output: "export"`) to compile the correct absolute URLs for media assets. Also configured `unoptimized: true` in `next.config.ts` for images when using a remote pattern.
- **Artifacts**: `landing/.github/workflows/deploy.yml`, `landing/next.config.ts`
- **Rule Created**: `rules/web-deployment.mdc`

## [2026-02-22] Static Site Contact Form Submissions
- **Problem**: Next.js static exports to Cloudflare Pages have no backend API to handle contact form submissions.
- **Solution**: Integrated Web3Forms (Option A) directly into the frontend React components. A hidden honeypot field (`botcheck`) prevents spam without requiring a visible captcha. The access key is managed via a GitHub Actions secret (`NEXT_PUBLIC_WEB3FORMS_ACCESS_KEY`) and injected into the build process, sending emails to `admin@multiagent.vision` which is handled by Cloudflare Email Routing.
- **Artifacts**: `landing/src/components/sections/CTASection.tsx`, `landing/src/components/ContactForm.tsx`
- **Rule Created**: Updated `rules/web-deployment.mdc` with contact form info.

## [2026-02-21] Live stream xcorner calibration fails on individual board crops

- **Problem**: Board 1 calibration failed in live MJPEG stream — `4corner_fallback` with only 4 inliers, rejected by quality check. Result: black panel for Board 1.
- **Root Cause**: `calibrate_from_frame` was called on each small board crop individually. The crop for Board 1 had 48 xcorners but only 1 cluster (44 pts) — grid fitting (`35pt_adaptive`) failed because the isolated crop lacked spatial context. Fell back to `4corner_fallback` which was always rejected (`n_inliers <= 4`, and 4-corner by definition returns exactly 4).
- **Solution**: Run `calibrate_from_frame` on the **full scene frame** with `board_index=0` / `board_index=1`. Full scene yields 98 xcorners, properly clustered into 2 boards (47+47), both calibrated with `35pt_adaptive` (30 and 34 inliers). Also: the homography H is now relative to the scene frame, so `gt_warp_frame` must also use the scene frame (not the board crop).
- **Key insight**: Boards don't move — xcorners are static. Detect once on full scene for proper multi-board clustering.
- **Artifacts**: `algo/live_recognition_server.py` (lines ~4151-4197).
- **Rule Created**: Updated `rules/reco-pipeline.mdc` with xcorner calibration guidance.

## [2026-02-21] Live stream panel layout — 6 panels (3 per board)

- **Problem**: User wanted 3 views per board (classification, warped YOLO, raw YOLO) = 6 panels total. Initially only 3 showed; YOLO board detection on full frame returned 0 results.
- **Solution**: Simplified: (1) Warped classification (YOLO+RecoAlgo merged), (2) Board crop resized to 480x480 + `infer_fen_yolo26` grid overlay, (3) Raw YOLO bounding boxes with white labels. No need for `detect_boards` — just resize the user's board crop directly.
- **Artifacts**: `algo/live_recognition_server.py`, `algo/video_tracker_ui.html`.

## [2026-02-21] Warped board grid shifted by ~30px — xcorner-to-grid mapping off by fractional cell

- **Problem**: Board 0 warped image was misaligned — pieces appeared shifted ~half a cell, causing YOLO and RecoAlgo to assign pieces to wrong ranks. Board 1 was fine.
- **Root Cause**: The calibration homography H mapped xcorners to the 480x480 grid with a ~30px vertical offset. The xcorner model detected a frame-edge corner alongside the 49 internal intersections, biasing the grid. `detect_grid_offset` (brightness-based) could NOT catch this because: (1) it works modulo 60px (full-cell periodic), so offsets >=30px wrap around; (2) Board 0 had only 22 vertical samples (below MIN_RELIABLE=25 threshold) due to low evening light, so dy defaulted to 0.
- **Solution**: On the first frame, run xcorner detection on the **pre-rotation** warped image (before `cv2.rotate`). Compute median Y of all detected corners. Expected median for a properly aligned 7x7 grid is 240.0px. Apply pixel-precise corrective translation `T @ H` where `T[1,2] = 240 - median_y`. Threshold: only correct if |offset| > 5px. Store corrected H in `board_calibrations[i]` for all subsequent frames.
- **Key insight**: `detect_grid_offset` and `detect_grid_offset_xcorners` both snap to nearest grid line (modular), so they can only measure sub-cell offsets. For fractional/full-cell offsets, use the absolute median position of xcorners vs the expected 240px center.
- **Key insight**: Correction must be applied in pre-rotation coordinate space (before `cv2.rotate`), not on the final rotated image. Applying to the rotated image reverses the sign for rot=180.
- **Artifacts**: `algo/live_recognition_server.py` (grid correction block in live loop, ~line 4464).

## [2026-02-18] Video recognition best params — 2 boards, 8h sweep

- **Context**: Target video `22_19_H_clip_9m30-15min_fixed.mp4` (2 boards, ~5.5 min clip). Goal: complete PGN for both boards.
- **Best result**: board_0 = 1 move, board_1 = 6 moves (run `run_1771391074`). Games incomplete (result `*`).
- **Winning params**: `orientation=white`, `change_threshold=16`, `stability_frames=2`, `fps=2.5`, `skip_start=0`.
- **Observation**: Board 0 only gets moves with low threshold (16–18); board 1 benefits from same. No run reached 20 moves/board in 1149 attempts.
- **Full analysis**: `algo/docs/VIDEO_RECOGNITION_RESULTS.md`

## [2026-02-17] Video recognition 0 moves — cell_diffs not passed

- **Problem**: `batch_video_tracker` produced 0 moves; logs showed "score=-2.0" and "REJECTED: best score -2.0 < 40".
- **Root Cause**: `batch_video_tracker.py` called `game_tracker.process_move(changed_cells, frame_no)` without passing `cell_diffs`. When `cell_diffs` is None, `find_matching_move` uses -1.0 for from/to diffs → score -2.0.
- **Solution**: Pass `cell_diffs=move_result.get("cell_diffs")` to `process_move`.
- **Artifacts**: `algo/batch_video_tracker.py` (line ~153).

## [2026-02-17] ClearML Agent getaddrinfo DNS Error on rg1/rg2

- **Problem**: Tasks fail with `fatal: unable to access 'https://github.com/...': getaddrinfo() thread failed to start`.
- **Root Cause**: PVE kernel 6.14.x incompatibility with glibc's threaded DNS resolver in Docker containers.
- **Solution**: (1) Add `"dns": ["8.8.8.8", "8.8.4.4"]` to `/etc/docker/daemon.json` on PVE hosts; (2) In clearml.conf `agent.extra_docker_shell_script`, install Miniconda + conda git and symlink to `/usr/bin/git`.
- **Artifacts**: `infra/ansible/playbooks/deploy-clearml-agents.yml`, `infra/.cursor/rules/clearml-agents-infra.mdc`

## [2026-02-17] rg1 dpkg broken — nvidia-kernel-dkms for kernel 6.17.2-1-pve

- **Problem**: `dpkg --configure -a` stuck; `nvidia-kernel-dkms` fails to build for kernel 6.17.2-1-pve (NVIDIA 550 driver incompatible).
- **Root Cause**: Kernel 6.17.2-1-pve was removed (rc) but headers remained; DKMS still tried to build for `/lib/modules/6.17.2-1-pve`.
- **Solution**: (1) Remove kernel packages: `apt-get remove proxmox-kernel-6.17.2-1-pve-signed proxmox-kernel-6.17`; (2) Remove headers: `apt-get remove proxmox-headers-6.17.2-1-pve proxmox-headers-6.17`; (3) `dpkg --configure -a`.
- **Artifacts**: `infra/scripts/fix-rg1-dpkg-kernel6.17.sh`

## [2026-02-16] Cursor UI Blinking / Flickering
- **Problem**: Cursor AI screen blinking, old plans appearing/disappearing.
- **Root Cause**: Accumulation of temporary `.plan.md` files in `~/.cursor/plans/` which the UI keeps polling.
- **Solution**: Moved files to archive.
  ```bash
  mkdir -p ~/.cursor/plans_archived && mv ~/.cursor/plans/* ~/.cursor/plans_archived/
  ```
- **Rule Created**: `rules/cursor-troubleshooting.mdc`

## [2026-02-16] YOLO26 Pieces Model 0.0 mAP
- **Problem**: `yolo26_pieces.pt` detected 0 objects despite correct input.
- **Root Cause**: The model file was from a failed training run (0.0 fitness).
- **Solution**: Found successful training job `14304268` on BGU cluster, located nested output path `runs/detect/runs/pieces/...`, and downloaded `best.pt` (0.98 mAP).
- **Rule Created**: `rules/cluster-workflows.mdc` (added "Nested Paths" and "Model Validation" sections).

## [2026-02-03] Legacy-Recognition Model Path Mismatch
- **Problem**: legacy-recognition app may fail to load models on startup.
- **Root Cause**: `loadModels.tsx` references `480_new_pices/model.json` and `480_new_xcorrners/model.json`, but `public/` contains `480M_pieces_float16/` and `480L_xcorners_float16/`.
- **Solution**: Either (a) add symlinks `480_new_pices` → `480M_pieces_float16` and `480_new_xcorrners` → `480L_xcorners_float16`, or (b) update loadModels.tsx to use the actual paths. Also fix typo: `pices` → `pieces`.
- **Rule Created**: `rules/legacy-recognition.mdc`
