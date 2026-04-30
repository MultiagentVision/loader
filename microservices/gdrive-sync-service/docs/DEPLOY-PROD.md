# Production: Rehovot Drive → MinIO `chess-ai/video/Rehovot/`

## Goal

- **Source**: Google Drive folder [Rehovot](https://drive.google.com/drive/folders/1BJFbwCtGKcuo6B13Jae-S5QkIq6MkyT4) (ID `1BJFbwCtGKcuo6B13Jae-S5QkIq6MkyT4`).
- **Target**: bucket **`chess-ai`**, object prefix **`video/Rehovot/`** (visible in the S3 console under `video/Rehovot/…`, e.g. [s3-console.multiagent.vision](https://s3-console.multiagent.vision/browser/chess-ai/video%2FRehovot%2F) after Cloudflare Access login).

## Preconditions

1. **Service account** with Drive **read** access to that folder; JSON key as `rehovot-drive-sa.json`.
2. **PostgreSQL** reachable from the cluster (async URL `postgresql+asyncpg://…`).
3. **Redis** for Celery.
4. **MinIO / S3** credentials: reuse Vault path `chessverse/minio` (`access_key`, `secret_key`) the same way as `microservices/videostreaming/rtsp_to_hls/k8s/external-secret-s3.yaml` in chessverse-monorepo.
5. **`MINIO_ENDPOINT`**: in-cluster hostname (or Tailscale IP:port to MinIO), **not** the browser console host. Examples: `minio.<namespace>.svc.cluster.local:9000` or `100.x.x.x:9000` if you expose MinIO only on Tailscale. Set `MINIO_SECURE` to `true` or `false` to match that endpoint.

## Kubernetes secrets

```bash
kubectl create secret generic gdrive-sync-env -n chessverse \
  --from-literal=DATABASE_URL='postgresql+asyncpg://USER:PASS@HOST:5432/gdrive_sync' \
  --from-literal=REDIS_URL='redis://redis-master.chessverse-infra:6379/0' \
  --from-literal=MINIO_ENDPOINT='minio.example.svc.cluster.local:9000' \
  --from-literal=MINIO_SECURE='false'
```

```bash
kubectl create secret generic gdrive-sync-drive-sa -n chessverse \
  --from-file=rehovot-drive-sa.json=./rehovot-drive-sa.json
```

Apply `k8s/external-secret-minio.yaml` if External Secrets + Vault are configured.

Apply ConfigMap and Deployments from `k8s/` (order: ExternalSecret → Secret sync → ConfigMap → Deployments).

## Build image (Jenkins)

In **chessverse-monorepo**, run the pipeline with **`SERVICE=gdrive_sync`** (after the Jenkinsfile in that repo lists this service). Image: `registry.multiagent.vision/chessverse/gdrive_sync:sha-<gitsha>`.

## Argo CD (пошагово)

**Почему не видно в Argo:** Jenkins только собрал образ `registry.multiagent.vision/chessverse/gdrive_sync:sha-…`. В Argo появляется только то, для чего создан **`Application`**.

1. Подготовьте секреты (`gdrive-sync-env`, `gdrive-sync-drive-sa`, MinIO ExternalSecret) — см. выше.
2. В UI Argo ищите приложение с именем вроде **`chessverse-gdrive-sync`**, не `gdrive_sync` (это имя в Jenkins).
3. **New App:** repo `https://github.com/MultiagentVision/chessverse-monorepo.git`, revision `main`, path **`microservices/gdrive-sync-service/k8s`**, namespace **`chessverse`**. Образец YAML: **`docs/argo-cd-application.sample.yaml`** (не хранить его внутри `k8s/`).
4. **Sync** / дождаться авто-синка. Образ подтянется из `deployments.yaml` на ветке `main` (после коммита Jenkins с metadata).

Пока Application не создан, стадия Jenkins **Verify** для `gdrive_sync` пропускается.

## Smoke test

- `kubectl logs -n chessverse deploy/chessverse-gdrive-sync-worker -f`
- After sync: objects like `video/Rehovot/<driveFileId>_<filename>.h265` in bucket `chess-ai`.
