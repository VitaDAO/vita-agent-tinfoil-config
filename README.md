# vita-agent-tinfoil-config

Public deployment manifest for the **vita-agent** confidential AI server.

## What this repo is

This repo contains everything needed for independent verification:

| File | Purpose |
|---|---|
| `tinfoil-config.yml` | Full deployment manifest: image digest, resource limits, secret names, exposed HTTP paths |
| `.github/workflows/tinfoil-build.yml` | Sigstore attestation workflow that runs on every release tag |

Source code lives in [`VitaDAO/vita-agent`](https://github.com/VitaDAO/vita-agent).
Container images are pulled from `ghcr.io/vitadao/vita-agent` and authenticated with `GHCR_TOKEN`.

## What vita-agent does

vita-agent is a single Tinfoil enclave that handles the AI portion of the
Vita longevity app. Specifically:

- 6 LLM intents (chat, daily_insight, refine_protocol, generate_protocol,
  parse_supplement, suggest_condition) via the OpenAI Agents SDK against
  Tinfoil Inference
- Long-term encrypted memory (Active Memory pipeline + tools the LLM can call)
- Aubrai scientist routing (HPKE-sealed + x402 USDC-on-Base micropayment)
- Persona doc + auto fact extraction + thumbs-up/down feedback loop
- Per-request RLS into Supabase — no service-role key in the enclave

It does NOT handle wearables (Oura/Whoop/Withings) — those run in a
separate `tinfoil-proxy` enclave with scoped service-role access.
That split is intentional: vita-agent's privacy claim depends on the
"no service-role key" invariant.

## Privacy model

- All LLM inference is HPKE-encrypted to Tinfoil hardware enclaves (AMD SEV-SNP)
- All Supabase rows are AEAD-encrypted with per-user keys (XChaCha20-Poly1305)
  — Supabase admins see only ciphertext
- Browser-side DEKs are HPKE-sealed to the enclave's static pubkey before
  transport (`X-Vita-User-DEK-Sealed` header), then opened in-enclave only
- Cross-user output guardrail blocks any response containing another user's
  identifiers (UUID, email, bytea, base64 secret)
- Provider-policy guardrail rejects any model client that isn't Tinfoil
  Inference at runtime; CI grep blocks `AsyncOpenAI(...)` outside the
  approved provider module
- Only routes listed under `shim.paths` are exposed; everything else is
  blocked at the reverse proxy

## Verify the running enclave

```bash
cosign verify-attestation \
  --type 'https://slsa.dev/provenance/v1' \
  --certificate-identity-regexp 'https://github\.com/VitaDAO/vita-agent-tinfoil-config/' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
  ghcr.io/vitadao/vita-agent@sha256:<digest>
```

The digest is pinned in `tinfoil-config.yml`. Every release tag creates a
GitHub pre-release with the sigstore attestation bundle.

## Deploy a new version

```bash
# 1. In the source repo (VitaDAO/vita-agent), wait for CI to publish a new
#    image to GHCR. Copy the sha256 digest.
# 2. Edit tinfoil-config.yml: paste the new digest into containers[0].image,
#    bump the version tag in the same string.
# 3. Tag this repo:
git tag v0.1.1
git push origin v0.1.1
```

The workflow attests the image, creates a pre-release with the bundle,
and the Tinfoil dashboard auto-deploys.

## Required secrets (set in the Tinfoil dashboard)

| Secret | Used by | Notes |
|---|---|---|
| `GHCR_TOKEN` | image pull | Read-only PAT for `ghcr.io/vitadao/vita-agent` |
| `TINFOIL_API_KEY` | every LLM call | Tinfoil Inference auth |
| `SUPABASE_URL` | per-request RLS client | Same URL the browser uses |
| `SUPABASE_ANON_KEY` | per-request RLS client | RLS-scoped, anonymous role |
| `AUBRAI_HPKE_PUBLIC_KEY` | aubrai_scientist tool | 32-byte hex pubkey |
| `X402_WALLET_PRIVATE_KEY` | aubrai_scientist tool | Funded Base mainnet wallet |

`X402_WALLET_PRIVATE_KEY` is the highest-value secret — never log, never
store outside the dashboard's encrypted slot.

`SUPABASE_SERVICE_ROLE_KEY` MUST NOT be added. `boot.py::_validate_storage_config`
rejects any non-empty value at startup.

## Coexistence with `aubrai-tinfoil-config`

vita-agent runs alongside (not inside) the Aubrai enclave. Aubrai is a
separate confidential service this enclave CALLS via x402 + HPKE for
deep-research questions. They have different attestation chains, different
sigstore identities, and different secret slots.
