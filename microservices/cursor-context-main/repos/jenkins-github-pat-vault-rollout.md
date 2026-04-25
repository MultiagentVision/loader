# Rollout plan: corporate GitHub PAT in Vault → all Jenkins jobs green

This document is the operator runbook. **Do not** put PAT strings in Git, Cursor, or tickets—only in **Vault** (or `kubectl` from a secure workstation).

## 1. Scope — which GitHub repos Jenkins touches

| GitHub repo | Jenkins job | Clone / SCM | Pipeline git push (if any) | Jenkins credential ID(s) |
|-------------|-------------|---------------|----------------------------|---------------------------|
| `MultiagentVision/chessverse-monorepo` | `chessverse-monorepo` (multibranch) | HTTPS + PAT | **Update metadata** → `deploy/metadata.yaml` on `main` | **`jenkins-token`** |
| `MultiagentVision/chessverse-monorepo` | `chessverse/<service>` (9 pipeline jobs: `bff`, `train`, …) | HTTPS + PAT | **Update metadata** (same file; last build wins on SHA) | **`jenkins-token`** |
| `MultiagentVision/mvat` | `mvat` (multibranch) | SSH **`mvat-github-deploy-key`** | **Update deploy/metadata.yaml** (HTTPS PAT) | **`mvat-github-pat`** (secret text) |
| `MultiagentVision/frontend` | `frontend` (Pipeline from SCM) | HTTPS + PAT | none in `Jenkinsfile` | **`github-frontend`** (JCasC; same PAT as **`jenkins-token`**, typically GitHub bot **`multiagent-ci`**) |

**Application repos** (`chessverse-monorepo`, `mvat`, `frontend`) are the ones that need GitHub auth in Jenkins today. Other git repos in your workspace without a `Jenkinsfile` in this setup are **out of scope** until you add jobs.

## 2. PAT permissions (one token or two)

Use a **classic** PAT with scope **`repo`**, or fine-grained with **Contents: Read and write** on every repo Jenkins must clone and push.

- **Single PAT (recommended):** must allow **read + write** on `chessverse-monorepo`, **`mvat`**, and **`frontend`**. Then set **both** Kubernetes secret keys `token` and `mvat_github_pat` to the **same** value (JCasC maps them to `jenkins-token` / `github-frontend` and `mvat-github-pat`).
- **Split PATs:** use different Vault fields / secret keys only if policy requires it; JCasC still expects `token`, `mvat_github_pat`, and optionally the same `token` for `github-frontend`.

Authorize **SSO** for the org if applicable.

## 3. Vault — write secrets (operator only)

Adjust **mount** and **path** to your cluster (example uses KV v2 path `secret/` → logical path `secret/data/...` or `secret/jenkins/...` per your Vault UI).

**Example (CLI, KV v2):**

```bash
# Login to Vault as appropriate, then (replace placeholders — do not commit real values):
vault kv put secret/jenkins/github \
  token='<PAT>' \
  mvat_github_pat='<same PAT or MVAT-only PAT>'
```

If your team uses a different path, keep the **property names** `token` and `mvat_github_pat` so the ExternalSecret below maps without changes—or update `remoteRef` in `external-secret-github-token.yaml` to match.

## 4. Kubernetes — sync Vault → `github-token` secret

**GitOps:** The chart includes `templates/external-secret-github-token.yaml`, which creates an **ExternalSecret** that populates Secret **`github-token`** in namespace **`jenkins`** from Vault path **`jenkins/github`** (keys `token`, `mvat_github_pat`).

1. Merge/push GitOps so ArgoCD application **`jenkins`** syncs the new template.
2. Confirm the secret exists and keys are non-empty:

```bash
kubectl get externalsecret -n jenkins github-token
kubectl get secret github-token -n jenkins -o jsonpath='{.data.token}' | base64 -d | wc -c   # expect > 0
```

3. If you previously created **`github-token` manually**, either:
   - Prefer **`creationPolicy: Merge`** on the ExternalSecret `target` so ESO can **merge** Vault-backed keys into the existing secret without requiring delete/recreate, or
   - Delete the manual secret only when ExternalSecret is healthy and will recreate it (`kubectl delete secret github-token -n jenkins`).

**Conflict rule:** Do **not** put `mvat_github_pat` on both `github-token` and `jenkins-credentials` ExternalSecrets (duplicate env keys on the controller). This rollout uses **`github-token`** only for PAT keys.

### 4a. Writing Vault from the cluster (optional)

If the Vault CLI is not on your laptop but you have **`kubectl`**: the controller pod can run `vault kv put` when authenticated. One pattern that has worked operationally:

1. Read a **Vault token** that External Secrets uses: Secret **`vault-token`** in namespace **`external-secrets`** (key `token`) — same token the **`ClusterSecretStore`** `vault-backend` references.
2. `kubectl exec -n vault vault-0 -- env VAULT_TOKEN="…" vault kv put secret/jenkins/github token='…' mvat_github_pat='…'`

**Security:** Do not paste real PATs or tokens into tickets or Git. Rotate anything that was ever exposed in chat or logs.

## 5. Jenkins controller — reload JCasC

JCasC reads **`${token}`** and **`${mvat_github_pat}`** from the controller environment (from `containerEnvFrom` → `github-token`).

1. Restart the controller after the secret syncs, e.g.:

```bash
kubectl rollout restart statefulset/jenkins -n jenkins
# or delete the controller pod if your chart uses a different workload name
```

2. In Jenkins UI: **Manage Jenkins → Configuration as Code** (or check logs) for CasC errors.

## 6. Credential IDs vs Jenkinsfiles (must match)

| Credential ID | Defined in | Used by |
|---------------|------------|---------|
| `jenkins-token` | `gitops/.../jenkins/values.yaml` JCasC | Multibranch `chessverse-monorepo`, folder **`chessverse/*`** pipeline SCM, + `chessverse-monorepo/Jenkinsfile` `withCredentials` |
| `mvat-github-pat` | JCasC | `mvat/Jenkinsfile` metadata push |
| `github-frontend` | JCasC (same `${token}` as corporate PAT) | `frontend` Pipeline SCM in `values.yaml` |
| `mvat-github-deploy-key` | JCasC + Vault (`external-secret-credentials.yaml`) | Multibranch `mvat` **clone** (SSH) |

If any ID is missing or misnamed, you get **“Could not find credentials entry”** or clone failures.

## 7. Pipeline code health (already addressed in repo)

- **`timestamps()`** in Declarative `options { }` requires the **Timestamper** plugin. Without it, the **pipeline fails at compile time**. Remove `timestamps()` from `Jenkinsfile` / `Jenkinsfile.preview` if the plugin is not installed (chessverse-monorepo).
- **Metadata-only commits** on `main` (`chore: update deploy metadata…`) should **skip** heavy build stages per `SKIP_CI` logic in `chessverse-monorepo/Jenkinsfile` so the webhook build does not fail on empty `SERVICE`.
- **Per-service jobs** (`chessverse/<service>`): `SERVICE` is inferred from **`JOB_NAME`** (see `jenkins-cicd.mdc`). Kubernetes agent pods for Kaniko should be named like **`chessverse-<service>-<build>-*`** — if you only see generic **`default-*`** pods for those jobs, the job path or Jenkinsfile detection may be wrong.

## 8. Verification checklist

- [ ] Vault KV contains `token` (and `mvat_github_pat` if MVAT push uses PAT).
- [ ] `ExternalSecret` `github-token` in `jenkins` is **Ready**; Secret `github-token` has data.
- [ ] Controller restarted; JCasC applied without errors.
- [ ] **Chessverse monorepo** branch scan succeeds (uses `jenkins-token`).
- [ ] Run one parameterized build with a real **`SERVICE`** on `main`; **Update metadata** completes or no-ops cleanly.
- [ ] **MVAT** `main` build: Kaniko + metadata push OK (`mvat-github-pat`).
- [ ] **Frontend** `main` build: SCM checkout OK (`github-frontend`).
- [ ] Delete legacy Jenkins UI credential **`git-deploy-multiagent-ci token`** (and any duplicate PAT for the same bot) **only after** the above pass, so **`github-frontend`** is supplied only by JCasC.

## 9. Related files

- `cursor-context/rules/jenkins-cicd.mdc` — overview + pointers.
- `gitops/apps/infra/jenkins/JENKINS_SETUP.md` — setup and secret keys.
- `gitops/apps/infra/jenkins/values.yaml` — JCasC credentials + job definitions.
- `gitops/apps/infra/jenkins/templates/external-secret-github-token.yaml` — Vault → `github-token`.

## 10. JCasC Job DSL: `chessverse` folder without child jobs

**Symptom:** After ArgoCD sync / JCasC reload, **`chessverse`** exists but **no** `bff`, `train`, … jobs appear.

**Cause:** Job DSL embedded in JCasC sometimes applies the **folder** block but not a subsequent **Groovy `.each { }`** that creates many `pipelineJob`s in one script (timing / seed job behavior varies by Jenkins version and chart).

**Fix (one-time or after upgrades):** In **Manage Jenkins → Script Console**, run Job DSL that creates the folder (idempotent) and each `pipelineJob("chessverse/${svc.id}") { … }` with the same `cpsScm` + `jenkins-token` as GitOps. Alternatively **restart** the Jenkins controller and confirm jobs appear; if not, use the console.

**Trigger builds (in-cluster example):** From `jenkins-0`, obtain crumb + cookie, then `POST /job/chessverse/job/<service>/build` for each service (HTTP **201** = queued). See `rules/cloudflare-access.mdc` for external curl + Cloudflare Access.
