#!/usr/bin/env bash
# Simulate ClearML-style S3 access from the Proxmox host using throwaway Docker
# containers (bridge network, like typical agent step jobs).
#
# Usage:
#   cp env.example .env && edit .env
#   ./docker-s3-probe.sh
#
# With Cloudflare Access headers on the health check curl only:
#   CF_ACCESS_CLIENT_ID=... CF_ACCESS_CLIENT_SECRET=... ./docker-s3-probe.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${ROOT}/.env" ]]; then
  # shellcheck source=/dev/null
  set -a
  source "${ROOT}/.env"
  set +a
fi

: "${AWS_ACCESS_KEY_ID:?Set AWS_ACCESS_KEY_ID (e.g. in .env)}"
: "${AWS_SECRET_ACCESS_KEY:?Set AWS_SECRET_ACCESS_KEY}"

ENDPOINT="${AWS_ENDPOINT_URL:-https://s3.multiagent.vision}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"

CURL_IMAGE="${CURL_IMAGE:-curlimages/curl:8.5.0}"
AWSCLI_IMAGE="${AWSCLI_IMAGE:-amazon/aws-cli:2.15.0}"

echo "=============================================="
echo "S3 endpoint: ${ENDPOINT}"
echo "Region:      ${REGION}"
echo "=============================================="

echo ""
echo "=== [1] TCP reachability (curl image, no AWS creds) ==="
if [[ "${ENDPOINT}" =~ ^https:// ]]; then
  BASE="${ENDPOINT}"
else
  BASE="${ENDPOINT}"
fi
# MinIO health path (works on many deployments)
docker run --rm "${CURL_IMAGE}" \
  -sS -o /dev/null -w "minio/health/live HTTP %{http_code}\n" \
  --connect-timeout 10 \
  "${BASE}/minio/health/live" || echo "(health path failed — try checking endpoint URL / CF Access)"

echo ""
echo "=== [2] Optional: same request with Cloudflare Access headers ==="
if [[ -n "${CF_ACCESS_CLIENT_ID:-}" && -n "${CF_ACCESS_CLIENT_SECRET:-}" ]]; then
  docker run --rm "${CURL_IMAGE}" \
    -sS -o /dev/null -w "with CF Access HTTP %{http_code}\n" \
    -H "CF-Access-Client-Id: ${CF_ACCESS_CLIENT_ID}" \
    -H "CF-Access-Client-Secret: ${CF_ACCESS_CLIENT_SECRET}" \
    --connect-timeout 10 \
    "${BASE}/minio/health/live" || true
else
  echo "Skipped (set CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET to test)."
fi

echo ""
echo "=== [3] AWS CLI: list buckets (validates SigV4 + endpoint) ==="
docker run --rm \
  -e AWS_ACCESS_KEY_ID \
  -e AWS_SECRET_ACCESS_KEY \
  -e AWS_DEFAULT_REGION="${REGION}" \
  "${AWSCLI_IMAGE}" \
  s3 ls --endpoint-url "${ENDPOINT}"

echo ""
echo "=== OK: host → k8s MinIO path works for this endpoint/credentials ==="
