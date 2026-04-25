# Keys repo overview

**Purpose:** This repo holds sensitive key and credential files used by other workspace repos. Typical contents (do not rely on this list; it may change): keys_oci.txt, key.pem, public_key.pem. Referenced by infra (e.g. Proxmox/OCI), gitops, or other repos for API tokens, SSH keys, or cloud credentials.

**Critical:** No content from the keys repo is stored or described in cursor-context. Do not copy, paste, or document any key material here. Use this overview only to know that the keys repo exists and is referenced elsewhere—never expose its contents. When writing automation or docs that need credentials, point to “keys repo” or env/secrets, not to key values.
