#!/usr/bin/env bash
# When Docker is unavailable, verify k8s MinIO ingress + Cloudflare Access + SigV4
# using the chessverse model_train venv (same cf_patch as ClearML pipeline steps).
#
# Requires: kubectl, uv, chessverse-monorepo model_train deps (uv sync once).
#
# Usage:
#   export CHESSVERSE_MODEL_TRAIN=/path/to/chessverse-monorepo/microservices/train/model_train
#   ./probe-local-uv.sh
#
# CF tokens: ../../secrets/cloudflare-access.env (relative to this script)

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CTX_ROOT="$(cd "${ROOT}/../.." && pwd)"

if [[ -f "${CTX_ROOT}/secrets/cloudflare-access.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${CTX_ROOT}/secrets/cloudflare-access.env"
  set +a
else
  echo "Missing ${CTX_ROOT}/secrets/cloudflare-access.env" >&2
  exit 1
fi

: "${CF_ACCESS_CLIENT_ID:?}"
: "${CF_ACCESS_CLIENT_SECRET:?}"

if [[ -n "${CHESSVERSE_MODEL_TRAIN:-}" ]]; then
  MT="${CHESSVERSE_MODEL_TRAIN}"
else
  # Default: sibling checkout next to cursor-context
  PARENT="$(cd "${CTX_ROOT}/.." && pwd)"
  MT="${PARENT}/chessverse-monorepo/microservices/train/model_train"
fi
if [[ ! -f "${MT}/src/utils/cf_patch.py" ]]; then
  echo "Set CHESSVERSE_MODEL_TRAIN to model_train dir (has src/utils/cf_patch.py). Tried: ${MT}" >&2
  exit 1
fi

export AWS_ACCESS_KEY_ID="$(kubectl -n minio get secret minio-root-credentials -o jsonpath='{.data.rootUser}' | base64 -d)"
export AWS_SECRET_ACCESS_KEY="$(kubectl -n minio get secret minio-root-credentials -o jsonpath='{.data.rootPassword}' | base64 -d)"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_ENDPOINT_URL="${AWS_ENDPOINT_URL:-https://s3.multiagent.vision}"

echo "=== curl health + CF Access ==="
curl -sS -o /dev/null -w "HTTP %{http_code}\n" --connect-timeout 15 \
  -H "CF-Access-Client-Id: ${CF_ACCESS_CLIENT_ID}" \
  -H "CF-Access-Client-Secret: ${CF_ACCESS_CLIENT_SECRET}" \
  "${AWS_ENDPOINT_URL}/minio/health/live"

echo "=== boto3 list_buckets (cf_patch on botocore) ==="
cd "${MT}"
PYTHONPATH=. uv run python -c "
import os
from botocore.config import Config
from src.utils.cf_patch import patch_botocore_cf_access
patch_botocore_cf_access()
import boto3
cfg = Config(signature_version='s3v4', s3={'addressing_style': 'path'})
c = boto3.client(
    's3',
    endpoint_url=os.environ['AWS_ENDPOINT_URL'],
    aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
    aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'],
    region_name=os.environ.get('AWS_DEFAULT_REGION', 'us-east-1'),
    config=cfg,
)
out = c.list_buckets()
print('OK:', len(out.get('Buckets', [])), 'buckets')
for b in out.get('Buckets', [])[:20]:
    print(' ', b['Name'])
"

echo "=== probe-local-uv: done ==="
