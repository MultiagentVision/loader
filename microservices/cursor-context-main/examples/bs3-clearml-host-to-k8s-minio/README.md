# ClearML on Proxmox host + MinIO S3 inside Kubernetes

Use this when the **ClearML agent runs on a bare-metal / VM host** (e.g. **bs3**) while **MinIO is deployed in the RKE2 cluster** on Proxmox. The agent’s step containers are plain **Docker** on the host; they are **not** Kubernetes pods, so they **cannot** resolve or reach `minio.minio.svc.cluster.local`.

## What does not work from the host

| Endpoint | Why |
|----------|-----|
| `http://minio.minio.svc.cluster.local:9000` | Kubernetes DNS; exists only inside the cluster. |
| `http://bs3:9000` | Only valid if MinIO’s **S3 API** is actually listening on that host/port (e.g. host-network MinIO or a local process). If MinIO lives **only** in k8s, nothing listens on the host’s `:9000`. |

## What works (choose one)

### 1. Public ingress (current GitOps default)

MinIO S3 API is exposed via Ingress (see `gitops/apps/infra/minio/ingress.yaml` and `ACCESS.md`):

- **S3 API:** `https://s3.multiagent.vision` (HTTPS, port 443)
- **Credentials:** `minio-root-credentials` in namespace `minio`

From the **host** (and from any ClearML step container on that host), set:

```bash
export AWS_ENDPOINT_URL="https://s3.multiagent.vision"
export AWS_DEFAULT_REGION="us-east-1"
export AWS_ACCESS_KEY_ID="..."   # rootUser from secret
export AWS_SECRET_ACCESS_KEY="..."
```

**ClearML / boto3:** use the same `AWS_ENDPOINT_URL` and paths in `dataset_mappings.yaml` consistent with this host (e.g. `s3://s3.multiagent.vision:443/bucket/prefix` or bucket-style as your client expects).

**Cloudflare Access:** If the origin is behind Zero Trust, machine clients need `CF-Access-Client-Id` / `CF-Access-Client-Secret` on requests (your `model_train` code uses `cf_patch` for ClearML HTTP; S3/boto may need a compatible pattern or an unauthenticated path—confirm with your edge config).

### 2. NodePort or LoadBalancer on the tailnet (no public URL)

Expose the `minio` Service in namespace `minio` with a **NodePort** or **LoadBalancer** IP that is reachable from the Proxmox host over **Tailscale** or LAN:

```bash
kubectl -n minio get svc minio -o wide
```

Then on the host:

```bash
export AWS_ENDPOINT_URL="http://<NODE_TAILSCALE_IP>:<NODEPORT>"
# or http://<MetalLB-VIP>:9000 if you front MinIO that way
```

Use **HTTP** on plain MinIO API ports unless you terminate TLS on the LB.

### 3. kubectl port-forward (debug only)

For quick checks from your laptop—not for the ClearML agent:

```bash
kubectl -n minio port-forward svc/minio 9000:9000
export AWS_ENDPOINT_URL="http://127.0.0.1:9000"
```

## Simulate a ClearML step container on bs3

### `docker-s3-probe.sh` (needs Docker)

Runs **curl** and **aws-cli** inside disposable containers (bridge network). Set `CF_ACCESS_CLIENT_ID` / `CF_ACCESS_CLIENT_SECRET` for `https://s3.multiagent.vision` — the stock **aws-cli image does not inject CF headers** into SigV4 calls; use **`probe-local-uv.sh`** for a real S3 API check, or extend the Docker flow with a tiny custom image.

1. Copy `env.example` → `.env` and fill MinIO keys (never commit `.env`).
2. Export CF tokens (see `cursor-context/secrets/cloudflare-access.env`).
3. On a host with Docker: `./docker-s3-probe.sh`

### `probe-local-uv.sh` (no Docker — recommended on macOS dev machines)

Uses **`kubectl`** for MinIO root creds, **`secrets/cloudflare-access.env`** for Cloudflare Access, and **`chessverse-monorepo/.../model_train`** `cf_patch` (same botocore hook as pipeline steps) so **boto3 `list_buckets`** succeeds against the ingress.

```bash
cd /path/to/cursor-context/examples/bs3-clearml-host-to-k8s-minio
chmod +x probe-local-uv.sh
# optional: export CHESSVERSE_MODEL_TRAIN=.../model_train
./probe-local-uv.sh
```

Default model_train path: sibling `../chessverse-monorepo/microservices/train/model_train` next to `cursor-context`.

## Mapping to `model_train`

- Set **`AWS_ENDPOINT_URL`** / **`MINIO_*`** in the machine that runs `uv run src/pipeline.py` so `pipeline.py` injects the same values into step Docker (`STEP_DOCKER_ARGUMENTS`).
- Align **`config/dataset_mappings.yaml`** `output_uri` and `s3_source_uri` with that endpoint (same host/port/scheme as boto will use).
- Remove reliance on **`--add-host=bs3:host-gateway`** for MinIO-in-k8s unless you intentionally map `bs3` to a **node IP** that reaches the Service (advanced). You can set `PIPELINE_DOCKER_ADD_HOST_BS3=0` when using ingress-only URLs.

## References

- In-repo GitOps: `gitops/apps/infra/minio/ACCESS.md`, `ingress.yaml`
- Harbor uses in-cluster MinIO: `http://minio.minio.svc.cluster.local:9000` (pods only)
- Cursor rule: `rules/clearml-training.mdc`
