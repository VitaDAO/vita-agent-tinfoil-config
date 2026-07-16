#!/usr/bin/env python3
"""Config parity check — staging vs prod tinfoil-config.yml.

Fails when the SHARED TURN-V2 CONTRACT diverges between the two enclaves. That
drift is exactly what silently broke staging chat: staging was missing the
capability/context-v2 env vars and two shim.paths, so the capability endpoint
503'd and every V2 chat failed with chat_agent_error — undetected for weeks.

Design: an INVERTED allowlist. We enumerate only the small, stable contract set
and ignore everything else, so prod's ~20 env-specific tuning keys (latency
levers, history budgets, redpill pins, canary %) never trip the check. Adding a
new shared-contract key is a deliberate edit to the lists below.

Usage: parity_check.py <staging-config.yml> <prod-config.yml>
Exit 0 = parity OK, 1 = contract drift, 2 = usage error.
"""
from __future__ import annotations

import re
import sys

import yaml

# Present AND byte-identical in BOTH envs (the capability/context/safety contract).
MATCH_KEYS = [
    "VITA_TURN_ENVELOPE_V2",
    "VITA_CONTEXT_OWNER_BACKEND",
    "VITA_SESSION_V2",
    "VITA_HEALTH_RESOLVER_V2",
    "VITA_AGENT_POLICY_VERSION",
    "VITA_CONTEXT_V2_COHORT_POLICY_VERSION",
    "VITA_AGENT_PINNED_SAFETY",
    "VITA_AGENT_EXACT_MATCH",
    "VITA_AGENT_INPUT_FILTER",
    "VITA_AGENT_TOOLCALL_SALVAGE",
]
# Present AND non-empty in both, but value legitimately differs per env.
PRESENT_KEYS = ["VITA_AGENT_DEPLOYMENT_ID"]
# The 4 context-v2 flags are all-or-none: a partial set makes the app raise
# partial_context_v2_bundle → capability endpoint 503.
CONTEXT_V2_FLAGS = [
    "VITA_TURN_ENVELOPE_V2",
    "VITA_CONTEXT_OWNER_BACKEND",
    "VITA_SESSION_V2",
    "VITA_HEALTH_RESOLVER_V2",
]
# Identity vars the capability doc emits; must match this regex (mirrors
# turn_capabilities._SAFE_VERSION_RE) or build_capability_document 503s.
SAFE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
IDENTITY_KEYS = ["VITA_AGENT_DEPLOYMENT_ID", "VITA_AGENT_POLICY_VERSION"]
# A shim route that has no meaning without its backing secret.
SHIM_SECRET_REQUIRES = {
    "/api/v1/turn-protocol-ticket": "VITA_PROTOCOL_TICKET_HMAC_KEY",
}


def load(path: str) -> tuple[dict[str, object], set[str], set[str]]:
    doc = yaml.safe_load(open(path))
    container = doc["containers"][0]
    env = {k: v for entry in container.get("env", []) for k, v in entry.items()}
    secrets = set(container.get("secrets", []))
    paths = set(doc.get("shim", {}).get("paths", []))
    return env, secrets, paths


def _check_single(name: str, env, secrets, paths, fails: list[str]) -> None:
    present = [f for f in CONTEXT_V2_FLAGS if str(env.get(f, "")).strip()]
    if present and len(present) != len(CONTEXT_V2_FLAGS):
        fails.append(f"[{name}] partial context-v2 bundle: only {present} set (need all 4 or none)")
    for k in IDENTITY_KEYS:
        v = str(env.get(k, ""))
        if v and not SAFE_VERSION_RE.fullmatch(v):
            fails.append(f"[{name}] {k}={v!r} fails capability regex → endpoint would 503")
    for route, secret in SHIM_SECRET_REQUIRES.items():
        if route in paths and secret not in secrets:
            fails.append(f"[{name}] shim exposes {route} but secrets lacks {secret}")


def main(staging_path: str, prod_path: str) -> int:
    se, ss, sp = load(staging_path)
    pe, ps, pp = load(prod_path)
    fails: list[str] = []

    for k in MATCH_KEYS:
        if k not in se or k not in pe:
            fails.append(f"contract key {k} missing (staging={k in se}, prod={k in pe})")
        elif str(se[k]) != str(pe[k]):
            fails.append(f"contract key {k} diverges: staging={se[k]!r} prod={pe[k]!r}")
    for k in PRESENT_KEYS:
        for label, env in (("staging", se), ("prod", pe)):
            if not str(env.get(k, "")).strip():
                fails.append(f"identity key {k} empty/missing in {label}")
    if sp != pp:
        fails.append(f"shim.paths differ: only-staging={sorted(sp - pp)} only-prod={sorted(pp - sp)}")

    _check_single("staging", se, ss, sp, fails)
    _check_single("prod", pe, ps, pp, fails)

    if fails:
        print("PARITY FAIL:\n  " + "\n  ".join(fails))
        return 1
    print("parity OK — staging and prod agree on the turn-v2 contract")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: parity_check.py <staging.yml> <prod.yml>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
