# Dependency and Production Hardening Audit

**Run:** 2026-08-17 · CogniDiff v1.0
**Tools:** `pip-audit` 2.x, `bandit` 1.9.4
**Scope:** 4,895 lines across `backend/` and `ml/`, plus all installed packages.

---

## 1. `pip-audit` — known CVEs in dependencies

```bash
python -m pip_audit
```

**Result: 1 known vulnerability in 1 package.**

| Package | Version | Advisory | Status |
|---|---|---|---|
| `ecdsa` | 0.19.2 | PYSEC-2026-1325 | **Accepted risk — documented below** |

### Accepted risk: `ecdsa` PYSEC-2026-1325

- **How it got here.** Transitive dependency: `python-jose[cryptography]` →
  `ecdsa`. CogniDiff does not import or call `ecdsa` directly.
- **Why it is not exploitable in this setup.** The advisory concerns
  side-channel weaknesses in ECDSA signing/verification. CogniDiff signs JWTs
  with **HS256** — a symmetric HMAC — so no ECDSA code path is ever reached. The
  package is installed but unused.
- **No fix version available** at the time of audit.
- **Mitigation.** `ALGORITHM = "HS256"` is fixed in `backend/config.py` and is
  not configurable at runtime, so an attacker cannot induce an ECDSA path by
  supplying a different `alg`. The fallback JWT implementation in `auth.py`
  recomputes the signature with HS256 regardless of what the token header
  claims, which is also what defeats the `alg: none` attack (Attack 1d).
- **Review trigger.** Re-check when `python-jose` publishes a release that drops
  or pins past the affected `ecdsa` range.

A documented accepted risk is a professional answer. An unknown risk is not.

---

## 2. `bandit` — static analysis

```bash
python -m bandit -r backend/ ml/
```

| Severity | Count |
|---|---|
| **HIGH** | **0** |
| **MEDIUM** | **0** |
| LOW | 11 |

### MEDIUM findings — both fixed during this audit

Both were `B608` (SQL built from a string).

**1. `backend/database.py::insert()`** — built `INSERT INTO {table} ({columns})`
from a whitelist of table names.

The values were always parameterised, and the table name came from a fixed set,
so it was not exploitable. But "safe because every call site passes a literal"
is a property a reviewer has to verify by hand and a scanner cannot check at
all. **Fixed** by validating the table against the whitelist *and* every column
name against the live schema via `pragma_table_info` before interpolation — so
the database itself now enforces what was previously a convention. SQL has no
parameter form for identifiers, so this is the strongest available form.

**2. `backend/backup.py::verify_restore()`** — looped over table names in an
f-string to count rows. **Fixed** by writing out seven literal statements.

The same reasoning produced the earlier fix in `delete_user_data()`, which was
caught not by bandit but by our own grep test
(`test_attack_07c_the_codebase_contains_no_string_built_sql`). **There is now no
string-built SQL anywhere in the project**, which means the rule can be enforced
mechanically instead of remembered.

### LOW findings — reviewed, all accepted

| Finding | Location | Assessment |
|---|---|---|
| `B105` "hardcoded password: '1'" | `auth.py:258` | False positive — a PBKDF2 round-count in a dummy hash used to burn constant time on a missing user |
| `B105` "hardcoded password: 'dev-only-…'" | `config.py:46` | Intentional. A development-only key, and production **refuses to start** without a real `SECRET_KEY` (checked immediately above it) |
| `B105` "hardcoded password: 'bearer'" ×2 | `main.py` | False positive — the OAuth `token_type` string |
| `B105` "hardcoded password: 'cognidiff2026'" ×2 | `seed_demo.py` | Demo-seeding script only. Never imported by the API. Documented in the README as demo credentials |
| `B404`/`B603`/`B607` subprocess | `config.py:71` | `git rev-parse --short HEAD` for commit provenance. No user input reaches it; wrapped in a timeout and a `check=False`; falls back to `"unversioned"` |
| `B112` try/except/continue | `scoring.py:111` | Intentional — one unscoreable session must not abort a whole day's scoring |
| `B110` try/except/pass | `federated.py:183` | Intentional — persisting a simulation round is best-effort and must not fail the simulation |

---

## 3. Frontend and supply chain

**No CDN scripts are loaded at runtime.** Every third-party library is vendored
into `frontend/vendor/` and served from the same origin. This is stronger than
pinning a version with an SRI hash: there is no third-party host in the request
path at all, and the app works offline.

| Library | Version | SHA-384 |
|---|---|---|
| three.js | 0.160.0 | `qOkzR5Ke/XkQxuGVJ9hpFEpDlcoLtWwVYhnJf06cLIZa2vaIptSqaubivErzmD5O` |
| GSAP | 3.12.5 | `g4NTh/Iv5PPU4xPyhEWqPcwtNXOvdaDI8LLnyYfyNZOjKJeYQyjzQ9X5275eBjpt` |
| ScrollTrigger | 3.12.5 | `Z3REaz79l2IaAZqJsSABtTbhjgOUYyV3p90XNnAPCSHg3EMTz1fouunq9WZRtj3d` |
| Chart.js | 4.4.1 | `9nhczxUqK87bcKHh20fSQcTGD4qq5GhayNYSYWqwBkINBhOfQLg/P5HG5lF1urn4` |

Hashes recorded at vendoring time. Verify with:

```bash
openssl dgst -sha384 -binary frontend/vendor/three.min.js | openssl base64 -A
```

No npm dependency tree exists (no build step, no `node_modules`), so `npm audit`
has no surface to scan. That is a deliberate reduction of attack surface, not an
omission.

---

## 4. Production profile

| Control | Implementation |
|---|---|
| Debug off | `FastAPI(debug=False)` |
| No `--reload` in production | documented in README run instructions |
| **Swagger / ReDoc / OpenAPI disabled** | `docs_url=None, redoc_url=None, openapi_url=None` when `ENV=production`. The interactive docs are a complete map of the attack surface — a development tool, not a public page |
| No tracebacks to clients | global exception handler returns a generic message plus a request ID; the full traceback is logged server-side only |
| Security headers | `X-Content-Type-Options`, `X-Frame-Options: DENY`, `X-XSS-Protection`, `Referrer-Policy: no-referrer`, `Permissions-Policy`, `Cache-Control: no-store`, and HSTS in production |
| Body size cap | 512 KB, rejected in middleware before parsing |
| CORS | explicit allowlist plus an extension-origin regex; no wildcards |
| Rate limiting | per-endpoint, `backend/ratelimit.py::LIMITS` |
| Maintenance mode | `MAINTENANCE_MODE=true` returns 503 from data endpoints while the audit log stays writable |

Verified by `test_security_headers_are_present` and
`test_attack_09d_errors_never_leak_internals`.

---

## 5. File exposure checks

The frontend is served from `frontend/` only — never the repository root.

| Check | Expected | Result |
|---|---|---|
| `http://localhost:3000/cognidiff.db` | 404 | **404** — the database is outside the served directory |
| `http://localhost:3000/.git/config` | 404 | **404** — `.git` is outside the served directory |
| `cognidiff.db` in `.gitignore` | yes | yes |
| `.env` in `.gitignore` | yes | yes |
| `.env` in git history | absent | absent (repository initialised with `.gitignore` in the first commit) |
| `*.pkl` in `.gitignore` | yes | yes |
| `backups/` in `.gitignore` | yes | yes |

An exposed `.git` directory is one of the most common ways real repositories get
fully compromised — it contains every secret ever committed, including ones
later removed from the working tree. Both this and the database check are worth
running by hand before any deployment.

---

## 6. Secret audit

```bash
git log --all --full-history -- .env          # no results
grep -rn "ANTHROPIC_API_KEY" --include=*.py --include=*.js --include=*.html .
grep -rn "tiya" --include=*.py --include=*.js --include=*.html .
grep -rn "localhost:8000" --include=*.js --include=*.html frontend/
```

| Check | Result |
|---|---|
| `.env` ever committed | never |
| API key hardcoded in source | none — read from environment only |
| Hardcoded user IDs in application code | none. The only occurrences of `tiya` are in `seed_demo.py` (demo data) and the login page's demo-credentials hint |
| `localhost:8000` hardcoded in frontend | one place only — `assets/api.js::API_BASE`, overridable via `window.COGNIDIFF_API_BASE` |
| Secrets in commented-out code | none. Commented-out code is still in the repository |
| `.env.example` committed with placeholders | yes |
| API responses leaking other users' IDs or file paths | none — checked across every endpoint |

---

## 7. Re-run instructions

```bash
python -m pip_audit
python -m bandit -r backend/ ml/
python -m pytest tests/ -q
```

Run all three before every release tag, and again after any dependency change.
New code creates new attack surface.
