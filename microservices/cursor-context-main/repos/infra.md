# Infra repo — detailed overview

**Purpose:** Terraform-based Infrastructure-as-Code for Proxmox VMs and RKE2 Kubernetes. Terraform (bpg/proxmox provider) creates VMs; Ansible installs RKE2 and bootstraps ArgoCD. After bootstrap, app deployments use the **gitops** repo.

---

## Quick start (full cluster)

```bash
# On target Proxmox node (e.g. pve3)
export PROXMOX_VE_ENDPOINT="https://localhost:8006"
export PROXMOX_VE_API_TOKEN="root@pam!terraform=<TOKEN_UUID>"
export TF_VAR_template_id=9000
export TF_VAR_ssh_public_key_path="/root/.ssh/id_rsa.pub"

./scripts/deploy-pve3-rke2.sh
```

Script: (1) terraform apply (VMs), (2) generate Ansible inventory from Terraform outputs, (3) Ansible playbook RKE2 (server + agents), (4) ArgoCD bootstrap, (5) write kubeconfig and ArgoCD credentials.

**Outputs:**

- Kubeconfig: `ansible/artifacts/pve3-kubeconfig.yaml`
- ArgoCD credentials: `ansible/artifacts/argocd-credentials.txt`

**kubectl:** `export KUBECONFIG=ansible/artifacts/pve3-kubeconfig.yaml`

**ArgoCD UI:** Port-forward `svc/argocd-server -n argocd 8080:443` or NodePort 30443 on nodes (e.g. https://10.0.0.201:30443).

---

## Environment and Terraform variables

| Variable | Description |
|----------|-------------|
| PROXMOX_VE_ENDPOINT | Proxmox API URL (e.g. https://pve3:8006) |
| PROXMOX_VE_API_TOKEN | API token `user@realm!token=uuid` |
| TF_VAR_template_id | VM ID of cloud-init template (e.g. 9000) |
| TF_VAR_ssh_public_key_path | SSH public key path |

Terraform variables (in variables.tf / terraform.tfvars): `proxmox_node` (e.g. pve3), `template_id`, `gateway` (e.g. 10.0.0.138), `ssh_public_key_path`.

---

## Directory layout

### terraform/

- **proxmox/pve3-rke2-cluster/** — main cluster (Beer-Sheva): main.tf, variables.tf, outputs.tf, versions.tf, terraform.tfvars.example. Nodes: master 311 (10.0.0.201), worker1 312 (10.0.0.202), worker2 313 (10.0.0.203); 8 vCPU, 16 GiB RAM, 150 GiB disk each.
- **proxmox/bs1-rke2-cluster/** — bs1 cluster: main.tf, variables.tf, outputs.tf, versions.tf, terraform.tfvars.
- **proxmox/bs2-new-rke2-cluster/** — bs2 cluster: main.tf, variables.tf, outputs.tf, versions.tf, terraform.tfvars.example.
- **proxmox/modules/vm-rke2-node/** — reusable VM module: main.tf, variables.tf, outputs.tf, versions.tf.
- **proxmox/UNIFIED_HA_CLUSTER_README.md** — HA cluster notes.
- **argocd-root-apps/** — Terraform to create root ArgoCD Application (points at gitops repo): main.tf, variables.tf, providers.tf, README.md. Syncs `gitops/root-apps/*.yaml` (include `mc-mv.yaml`); apply after Argo is installed.
- **collab-mc-mv-vault/** — Terraform for Vault KV used by MC/MV ExternalSecrets (`collab/mc/mongodb`, optional `collab/mv/jibri`): versions.tf, main.tf, variables.tf, providers.tf, outputs.tf, README.md. Apply via `VAULT_ADDR` / `VAULT_TOKEN` (SSH port-forward or Tailscale) **before** Rocket.Chat Mongo starts.
- **vault-config/** — Vault config (e.g. OCI KMS, GHCR): main.tf, variables.tf, providers.tf, apply-ghcr*.sh, README.md, SETUP_GHCR.md, RUN_NOW.md, QUICK_APPLY.md.

### ansible/

- **playbooks/** — rke2-pve3.yml (main RKE2 install), deploy-bs-cluster-temporary.yml, deploy-bs-cluster-rolling-add.yml, deploy-clearml-agents.yml, deploy-gpu-inference.yml, deploy-unified-ha-cluster.yml.
- **inventory/** — generated (e.g. pve3.ini) and examples: bs-cluster-temporary.ini.example, bs-cluster-rolling-add.ini.example, clearml-runners.ini(.example), unified-ha-cluster.ini, gpu-inference-hosts.ini, cluster-state.md.
- **roles/** — e.g. rke2-master-bootstrap (handlers/main.yml), etc.
- **artifacts/** — kubeconfig and argocd credentials after deploy.
- **playbooks/templates/** — e.g. clearml-agent-gpu.service.j2, gpu-inference.service.j2.

### scripts/

- deploy-pve3-rke2.sh — full deploy.
- generate-pve3-inventory.py — from Terraform outputs to ansible inventory.
- create-bs1-vms.sh, prepare-bs3-20tb-disk.sh, verify-bs-cluster-ha.sh, check-bs-cluster-readiness.sh, wait-for-bs1-vms.sh, check-vms-every-5min.sh, bs3-post-reboot-nvidia.sh, verify-bs3-disk-mount.sh, setup-clearml-agent.sh, check-minio-dns-and-ingress.sh, collect-minio-bs3-data.sh, clearml_enqueue_to_all_queues.py, clearml_test_worker.py.

### k8s/

- **minio-bs3-20tb/** — namespace, secret, storageclass, pv, pvc, external-secret, README, DEPLOYMENT_INSTRUCTIONS, STATUS.
- **gpu-inference/** — namespace, configmap, services-rg.yaml, services-bs.yaml, monitoring.yaml.
- gitops/apps/infra/minio/ — MinIO app in gitops (ingress, etc.).

### docs/

- BS_CLUSTER_HA_ARCHITECTURE.md, BS_CLUSTER_TEMPORARY_ARCHITECTURE.md, BS2_NEW_ROLLING_ADD.md, CLEARML_RUNNERS.md, EXTERNAL_ACCESS_CVAT_CLEARML.md, GITOPS_MIGRATION.md, MVAT_AND_CVAT_PARALLEL.md.

### CVAT on bs2 (Docker, not k8s)

- Public UI: `cvat.multiagent.vision` (Cloudflare Access + tunnel to host).
- If the UI says **Cannot connect** but API checks pass: see **`cursor-context/lessons/troubleshooting-log.md`** entry **[2026-03-28] CVAT UI "Cannot connect"** — often **`/api/server/health/`** returns 500 when **disk on the Docker host is ≥ ~90%** (django-health-check), not OPA/DB failure.

### Other

- gpu-inference-service/ — Dockerfile, docker-compose.yml, app/main.py, app/inference.py, requirements.txt.
- Many status/refinement MD files (TERRAFORM_DEPLOYMENT_STATUS.md, VM_FIX_COMPLETE.md, etc.) — operational notes.

---

## Manual deploy (step-by-step)

1. **Terraform:** `cd terraform/proxmox/pve3-rke2-cluster`, set env, `terraform init && terraform plan && terraform apply`.
2. **Inventory:** `terraform output -json > /tmp/pve3-outputs.json`, `python3 scripts/generate-pve3-inventory.py /tmp/pve3-outputs.json ansible/inventory/pve3.ini`.
3. **Ansible:** `cd ansible`, `ansible-playbook -i inventory/pve3.ini playbooks/rke2-pve3.yml`.

---

## Cloud-init template (Proxmox)

Before Terraform: create VM template with cloud-init (e.g. Ubuntu 22.04). Example: qm create 9000, importdisk, set scsi0, ide2 cloudinit, boot, qm template 9000. Use template_id 9000 in TF_VAR_template_id.

---

## Reusing for other nodes (rg1, rg2, rg3)

Copy terraform cluster dir (e.g. to rg1-rke2-cluster), update variables (proxmox_node, IPs, VM IDs, template_id). Copy and adapt playbook and deploy script. See README “Reusing for Other Nodes”.

---

## Prerequisites

Terraform >= 1.6, Ansible >= 2.14, Python >= 3.8, Proxmox VE 9.x with API, cloud-init template, SSH key. See repo README for full list and Vault+GitOps setup.
