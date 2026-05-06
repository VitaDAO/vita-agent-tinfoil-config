# vita-agent-tinfoil-config

Public deployment manifest for the **vita-agent** confidential AI server.

## What this repo is

This repo contains everything needed for independent verification:

| File | Purpose |
|---|---|
| `tinfoil-config.yml` | Full deployment manifest: image digest, resource limits, secret names, exposed HTTP paths |
| `.github/workflows/tinfoil-build.yml` | Sigstore attestation workflow that runs on every release tag |

Source code lives in [`VitaDAO/vita-agent`](https://github.com/VitaDAO/vita-agent).
Container images are pulled from `ghcr.io/vitadao/vita-agent` and authenticated with `VITA_AGENT_GHCR_TOKEN`.

## What vita-agent does

vita-agent is a single Tinfoil enclave that handles the AI portion of the
Vita longevity app. Specifically:

- 6 LLM intents (chat, daily_insight, refine_protocol, generate_protocol,
  parse_supplement, suggest_condition) via the OpenAI Agents SDK against
  Tinfoil Inference
- Long-term encrypted memory (Active Memory pipeline + tools the LLM can call)
- Aubrai scientist routing (HPKE-sealed + x402 USDC-on-Base micropayment)
- Persona doc + auto fact extraction + thumbs-up/down feedback loop
- Per-request RLS into Supabase with asymmetric internal JWTs for control-plane writes — no service-role key in the enclave

It does NOT handle wearables or raw lab PDF/image parsing — those run in the
separate `vita-ingest` enclave. That split is intentional: vita-agent's privacy
claim depends on keeping ingestion and private-AI orchestration separate.

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
# 2. Edit tinfoil-config.yml: paste the new digest into containers[0].image.
# 3. Tag this repo, then deploy that tag as a non-debug Tinfoil container:
git tag v0.10.0
git push origin main v0.10.0
```

The workflow attests the image, creates a pre-release with the bundle,
and the Tinfoil container can be launched from the signed tag.

## Required secrets (set in the Tinfoil dashboard)

| Secret | Used by | Notes |
|---|---|---|
| `VITA_AGENT_GHCR_TOKEN` | image pull | Read-only PAT for `ghcr.io/vitadao/vita-agent` |
| `TINFOIL_API_KEY` | every LLM call | Tinfoil Inference auth |
| `SUPABASE_URL` | per-request RLS client | Same URL the browser uses |
| `SUPABASE_ANON_KEY` | per-request RLS client | RLS-scoped, anonymous role |
| `VITA_AGENT_INTERNAL_JWT_PRIVATE_JWK` | control-plane writes | Supabase asymmetric private JWK; signs short-lived `vita_agent_internal` JWTs |
| `AUBRAI_HPKE_PUBLIC_KEY` | aubrai_scientist tool | 32-byte hex pubkey |
| `X402_WALLET_PRIVATE_KEY` | aubrai_scientist tool | Funded Base mainnet wallet |
| `SENTRY_DSN` | PHI-safe error monitoring | Optional; enables scrubbed Sentry events |

`X402_WALLET_PRIVATE_KEY` is the highest-value secret — never log, never
store outside the dashboard's encrypted slot.

Sentry is optional and disabled when `SENTRY_DSN` is unset. The runtime scrubber
removes request bodies, headers, cookies, user identifiers, DEKs, prompts,
health/lab/research payloads, and stack locals before sending events.

`SUPABASE_SERVICE_ROLE_KEY` MUST NOT be added. `boot.py::_validate_storage_config`
rejects any non-empty value at startup unless the debug-only escape hatch is set;
`STRICT_PROD=1` rejects that escape hatch as well.

## Coexistence with `aubrai-tinfoil-config`

vita-agent runs alongside (not inside) the Aubrai enclave. Aubrai is a
separate confidential service this enclave CALLS via x402 + HPKE for
deep-research questions. They have different attestation chains, different
sigstore identities, and different secret slots.
