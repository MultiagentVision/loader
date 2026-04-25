# GitOps repo — detailed overview

**Purpose:** Kubernetes manifests managed by ArgoCD. ArgoCD watches this repo; root Applications sync root-apps/ and create child Applications for apps/infra, apps/demo, apps/chessverse, apps/multiagent-platform. No app code here—only K8s YAML and Helm charts.

---

## Structure

```
gitops/
├── root-apps/                    # Root ArgoCD Applications (App of Apps)
│   ├── *.yaml                    # e.g. infra, demo, onprem-bs-cluster
├── apps/
│   ├── infra/                   # Vault, ESO, MinIO
│   │   ├── vault/
│   │   ├── external-secrets/
│   │   └── minio/                # ingress, ACCESS.md, DNS_SETUP.md, CLOUDFLARE_STEPS.md
│   ├── demo/                     # Demo apps (e.g. cloudflare-tunnel)
│   ├── chessverse/               # Chessverse stack
│   │   ├── *.yaml                # bff, tournament, alerts, postgres, redis, mongodb, rabbitmq,
│   │   │                         # rtsp-to-hls, rtsp-to-queue, simulation, frontend, frontend-mock,
│   │   │                         # reco, secrets; frontend-mock/ has deploy scripts, ingress, etc.
│   └── multiagent-platform/      # Copilot, learn, know, practice
│       ├── root-appset.yaml
│       ├── apps/                 # copilot.yaml, learn.yaml, know.yaml, practice.yaml
│       ├── copilot/              # openwebui, dify, llm-runtime (ollama), gpu-operator, README-ops, gpu-runtime-setup
│       ├── learn-openedx/        # app.yaml, admin-setup-job, README-ops, .github/workflows
│       ├── know-kb/              # wikijs, meilisearch, docusaurus (Dockerfile, deployment, service, ingress), README-ops
│       ├── practice-dmoj/       # app.yaml, helm/ (Chart, values, values-prod, templates: deployment-*, redis, mariadb, ingress, pvc, networkpolicy)
│       └── clusters/prod/       # namespaces, cert-manager, cert-issuer, external-secrets (openwebui, wikijs, dify, dmoj, meilisearch, openedx)
└── README.md
```

---

## Flow

1. **Infra repo** Terraform creates root-apps Application (points at this repo, path root-apps/).
2. ArgoCD syncs root-apps/*.yaml.
3. Each root app creates child Applications for its apps/... subtree.
4. Push to this repo → ArgoCD syncs changes.

**Prerequisites:** RKE2 + ArgoCD installed via **infra** repo; root-apps Application created via infra Terraform.

---

## Deployment steps (from README)

1. Terraform creates root-apps → ArgoCD syncs root-apps/.
2. ArgoCD creates infra + demo (and chessverse, multiagent-platform) Applications.
3. Wait for Vault and ESO: `kubectl get pods -n vault`, `kubectl get pods -n external-secrets`.
4. OCI credentials secret (manual): `sops --decrypt apps/infra/vault/oci-secret.sops.yaml | kubectl apply -f -` or kubectl create secret vault-oci-credentials in namespace vault.
5. Vault starts (OCI KMS auto-unseal).
6. Init Vault (one-time): `kubectl exec -n vault vault-0 -- vault operator init`; save root token.
7. Vault token for ESO: `kubectl create secret generic vault-token -n external-secrets --from-literal=token=hvs.xxxxx`.
8. vault-config Terraform: `cd infra/terraform/vault-config`, `export VAULT_TOKEN=hvs.xxxxx`, `terraform apply`.
9. ExternalSecret syncs; demo/chessverse/multiagent apps get secrets. Verify: `kubectl logs -n demo -l app=cloudflare-tunnel-demo`.

---

## Chessverse apps (apps/chessverse/)

- bff.yaml, tournament.yaml, alerts.yaml, simulation.yaml, rtsp-to-hls.yaml, rtsp-to-queue.yaml.
- postgres.yaml, redis.yaml, mongodb.yaml, rabbitmq.yaml, secrets.yaml.
- frontend.yaml, frontend-mock.yaml; frontend-mock/ has frontend-deployment, mock-server-deployment, ingress, services, configmap, namespace, external-secret, deploy.sh, README, SETUP_GHCR_SECRET, VAULT_SETUP, etc.
- reco.yaml.

---

## Multiagent platform (apps/multiagent-platform/)

- **copilot:** openwebui/app.yaml, dify/app.yaml, llm-runtime (deployment-ollama-*.yaml, service-ollama-*.yaml, pvc, gateway), gpu-operator.yaml; README-ops, gpu-runtime-setup.
- **learn-openedx:** app.yaml, admin-setup-job, README-ops, rendered/.gitkeep, .github/workflows/render-tutor.yml.
- **know-kb:** wikijs/app.yaml, postgres; meilisearch/app.yaml, cronjob-indexer; docusaurus (Dockerfile, deployment, service, app, ingress); README-ops.
- **practice-dmoj:** app.yaml, helm chart (values, values-prod, templates: deployment-web, deployment-judge, deployment-workers, deployment-bridge, redis, mariadb, ingress, pvc, networkpolicy); README-ops.
- **clusters/prod:** namespaces.yaml, cert-manager.yaml, cert-issuer.yaml, external-secrets/*.yaml (openwebui, wikijs, dify, dmoj, meilisearch, openedx).
- **DAY2-OPS.md** — operations notes.

---

## Source

Repo README for structure, components table, and exact kubectl/sops commands. Per-app README-ops and MD files in apps/* for app-specific steps.
