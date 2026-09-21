# TASK — web-sourcing inc3a-r2: version-independent SSRF rejection of IPv6 transition/reserved forms

## Context
`sdk/sfvf/media/web.py` already has an SSRF-guarded download (`fetch`). Its IP guard
(`_public_addr` + `_validated_pin_ip`) currently rejects non-global resolved IPs and unwraps
three IPv6-embedded-IPv4 forms (IPv4-mapped `::ffff:/96`, well-known NAT64 `64:ff9b::/96`,
IPv4-compat `::/96`) before validating. But for a class of IPv6 transition/reserved forms the
guard currently leans on CPython's `ipaddress.is_global`, which **misclassifies several of them
as global on CPython 3.12.0–3.12.3**. A cached workflow venv (see `app/core/env.py`) can run
this new fetch code on such an interpreter, so the guard must reject these forms
**version-independently** — by explicit range membership / address property, NOT by `is_global`.

Cross-family review flagged this on PR #142. A **frozen RED contract** is already committed in
`tests/integration/test_media_web_fetch.py` (do not edit it).

## Scope
- **Edit ONLY**: `sdk/sfvf/media/web.py`.
- **Do NOT** edit any test file (the contract is frozen), and **do NOT** create notes files
  (e.g. no `docs/BUILDER_NOTES.md`).
- No new dependencies. Standard library `ipaddress` only.

## Required behaviour (make the frozen contract pass)
1. **6to4 unwrap** — in `_public_addr`, additionally unwrap 6to4 (`2002::/16`): if the resolved
   address is IPv6 and falls in `2002::/16`, the embedded IPv4 is bytes 2–6 of the address:
   `ipaddress.IPv4Address(addr.packed[2:6])`. Treat it like the existing NAT64/`::/96` unwrap —
   the **returned** (embedded) address is what `_validated_pin_ip` then validates, so a 6to4
   embedding a private IPv4 (e.g. `2002:a9fe:a9fe::` → 169.254.169.254) is rejected by the
   existing `not addr.is_global` check on ALL interpreters.
   Contract: `_public_addr("2002:0a00:0001::") == ipaddress.ip_address("10.0.0.1")`.
2. **Explicit range/property rejection** (independent of `is_global`) — reject a resolved
   address when the ORIGINAL (pre-unwrap) IPv6 address is any of:
   - **Teredo** `2001::/32` (embedding is XOR-obfuscated — reject the whole range, do not unwrap),
   - **RFC 8215 local-use NAT64** `64:ff9b:1::/48` (RFC 6052 variable-prefix embedding — reject
     the whole range, do not unwrap),
   - **site-local** — `addr.is_site_local` True (deprecated `fec0::/10`; note it is
     `is_global=True` on current CPython, so `is_global` alone does NOT catch it),
   - **reserved** — `addr.is_reserved` True (e.g. discard-only `0100::/64`).
   Raise `ValueError` with a clear "non-public address" style message, consistent with the
   existing reject in `_validated_pin_ip`. Put this check where it sees the original IPv6 address
   (either a raise inside `_public_addr` before unwrapping, or an explicit check in
   `_validated_pin_ip` on `ipaddress.ip_address(ip)`), so it runs before any request. Keep the
   existing `not addr.is_global or addr.is_multicast` reject on the (possibly unwrapped) address.
3. Suggested module constants alongside the existing `_NAT64_NET` / `_V4COMPAT_NET`:
   `_6TO4_NET = ipaddress.ip_network("2002::/16")`, `_TEREDO_NET = ipaddress.ip_network("2001::/32")`,
   `_NAT64_LOCAL_NET = ipaddress.ip_network("64:ff9b:1::/48")`.

Do not weaken or remove any existing guarantee (https-only, IP-pin + Host/SNI, redirect
re-validation, byte cap, existing unwraps, `fe80::` scoped-literal reject).

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_fetch.py -q` → **all pass**
  (the 5 currently-RED cases plus the existing 20 stay green).
- `python -m ruff format --check sdk/sfvf/media/web.py` and
  `python -m ruff check sdk/sfvf/media/web.py` → clean.
- `git diff --name-only` shows **only** `sdk/sfvf/media/web.py`.
