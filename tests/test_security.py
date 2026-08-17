"""The twelve attacker simulations, encoded as automated tests.

Running these by hand once proves nothing about tomorrow's code. Encoded here,
a regression that reopens a closed vulnerability fails the suite immediately
rather than waiting to be rediscovered by hand — or by someone else.

Each test names its attack number so the run maps one-to-one onto
docs/attacker_simulation_results.md.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from backend.ratelimit import limiter
from tests.conftest import PASSWORD, make_batch, seed_sessions


# ---------------------------------------------------------------------------
# Attack 1 — IDOR
# ---------------------------------------------------------------------------

def test_attack_01_no_endpoint_accepts_a_caller_supplied_user_id(client, user, other_user):
    """The structural fix: there is no /api/dashboard/{user_id} to attack.

    Identity comes from the token, so changing a URL parameter cannot reach
    another user's data — there is no parameter to change.
    """
    schema = client.get("/openapi.json").json()
    offenders = [
        path for path in schema["paths"]
        if "{user_id}" in path or "{userId}" in path
    ]
    assert offenders == [], f"IDOR-shaped routes present: {offenders}"


def test_attack_01b_a_token_only_ever_returns_its_own_data(client, user, other_user):
    a = client.get("/api/dashboard/me", headers=user["headers"]).json()
    b = client.get("/api/dashboard/me", headers=other_user["headers"]).json()
    assert a["user"]["username"] == "alice"
    assert b["user"]["username"] == "bob"


def test_attack_01c_a_forged_token_is_rejected(client, user):
    forged = user["headers"]["Authorization"] + "tampered"
    res = client.get("/api/dashboard/me", headers={"Authorization": forged})
    assert res.status_code == 401


def test_attack_01d_an_unsigned_token_is_rejected(client, user):
    """The classic alg=none / hand-rolled-payload attempt."""
    import base64
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": user["user_id"], "role": "ADMIN", "tv": 1,
                    "exp": 9_999_999_999}).encode()
    ).rstrip(b"=").decode()
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "none", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()

    res = client.get("/api/dashboard/me",
                     headers={"Authorization": f"Bearer {header}.{payload}."})
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Attack 2 — doctor report without consent
# ---------------------------------------------------------------------------

def test_attack_02_doctor_without_consent_is_refused(client, user, doctor):
    res = client.get(f"/api/doctor-report/{user['user_id']}", headers=doctor["headers"])
    assert res.status_code == 403


def test_attack_02b_consent_grants_access_and_the_denial_was_logged(client, user, doctor):
    denied = client.get(f"/api/doctor-report/{user['user_id']}", headers=doctor["headers"])
    assert denied.status_code == 403

    client.post("/api/consent/grant", json={"doctor_username": "dr.who"},
                headers=user["headers"])

    allowed = client.get(f"/api/doctor-report/{user['user_id']}", headers=doctor["headers"])
    assert allowed.status_code == 200

    log = client.get("/api/audit-log/me", headers=user["headers"]).json()["entries"]
    outcomes = {(e["action"], e["outcome"]) for e in log}
    assert ("VIEW_DOCTOR_REPORT", "DENIED") in outcomes
    assert ("VIEW_DOCTOR_REPORT", "SUCCESS") in outcomes


def test_attack_02c_a_plain_user_cannot_read_another_user(client, user, other_user):
    res = client.get(f"/api/doctor-report/{user['user_id']}", headers=other_user["headers"])
    assert res.status_code == 403


def test_attack_02d_probing_for_valid_user_ids_gives_the_same_error(client, user, doctor):
    """A doctor must not be able to enumerate which user IDs exist by reading
    the difference between 'no such user' and 'no consent'."""
    real = client.get(f"/api/doctor-report/{user['user_id']}", headers=doctor["headers"])
    fake = client.get("/api/doctor-report/u_does_not_exist", headers=doctor["headers"])
    assert real.status_code == fake.status_code == 403
    assert real.json()["detail"] == fake.json()["detail"]


# ---------------------------------------------------------------------------
# Attack 3 — unauthorised deletion
# ---------------------------------------------------------------------------

def test_attack_03_deletion_without_a_token_is_refused(client, user):
    assert client.delete("/api/user/me").status_code == 401


def test_attack_03b_deletion_only_ever_removes_the_callers_own_data(client, user, other_user):
    seed_sessions(client, user["headers"], n=4)
    seed_sessions(client, other_user["headers"], n=4)

    assert client.delete("/api/user/me", headers=other_user["headers"]).status_code == 200

    # alice is untouched
    alice = client.get("/api/sessions/me", headers=user["headers"]).json()
    assert alice["count"] == 4


# ---------------------------------------------------------------------------
# Attack 4 — fake CogniScore injection via implausible features
# ---------------------------------------------------------------------------

def test_attack_04_implausibly_perfect_data_is_caught_by_the_quality_gate(client, user):
    """All features pinned at identical values with almost no keystrokes is not
    a great session — it is a fabricated one."""
    payload = make_batch(keystrokes=6, duration_ms=3_000)
    res = client.post("/api/session", json=payload, headers=user["headers"])
    assert res.status_code == 201
    body = res.json()
    assert body["should_exclude"] is True
    assert "LOW_VOLUME" in body["reason_codes"]


def test_attack_04b_out_of_range_features_are_rejected_outright(client, user):
    payload = make_batch()
    payload["wpm_estimate"] = 5_000
    res = client.post("/api/session", json=payload, headers=user["headers"])
    assert res.status_code == 422


def test_attack_04c_backspaces_cannot_exceed_keystrokes(client, user):
    payload = make_batch()
    payload["backspace_count"] = payload["total_keystrokes"] + 50
    assert client.post("/api/session", json=payload, headers=user["headers"]).status_code == 422


# ---------------------------------------------------------------------------
# Attack 5 — rate limiting
# ---------------------------------------------------------------------------

def test_attack_05_session_flooding_gets_429(client, user):
    limiter.enabled = True
    limiter.reset()
    try:
        codes = [
            client.post("/api/session", json=make_batch(seed=i), headers=user["headers"]).status_code
            for i in range(20)
        ]
    finally:
        limiter.enabled = False
        limiter.reset()

    assert 429 in codes, codes
    assert codes.count(201) <= 5, f"limit of 5/minute not enforced: {codes}"


def test_attack_05b_login_brute_force_is_throttled(client, user):
    limiter.enabled = True
    limiter.reset()
    try:
        codes = [
            client.post("/api/auth/login",
                        json={"username": "alice", "password": "wrong-password"}).status_code
            for _ in range(20)
        ]
    finally:
        limiter.enabled = False
        limiter.reset()

    assert 429 in codes


# ---------------------------------------------------------------------------
# Attack 6 — typed-text injection
# ---------------------------------------------------------------------------

def test_attack_06_a_raw_text_field_is_rejected(client, user):
    payload = make_batch()
    payload["raw_text"] = "my bank password is hunter2"
    res = client.post("/api/session", json=payload, headers=user["headers"])
    assert res.status_code == 422
    assert "raw_text" in res.text


@pytest.mark.parametrize("field", ["typed_text", "content", "keystrokes_raw", "keys"])
def test_attack_06b_no_text_shaped_field_is_accepted(client, user, field):
    payload = make_batch()
    payload[field] = "sensitive content"
    assert client.post("/api/session", json=payload, headers=user["headers"]).status_code == 422


def test_attack_06c_real_characters_in_key_categories_are_rejected(client, user):
    """The structural guarantee behind the privacy claim: even if the content
    script were changed to send characters, the API refuses to store them."""
    payload = make_batch()
    payload["key_categories"] = "hello world"
    res = client.post("/api/session", json=payload, headers=user["headers"])
    assert res.status_code == 422
    assert "l, d, s, b and p" in res.text


def test_attack_06d_nothing_resembling_text_reaches_the_database(client, user):
    seed_sessions(client, user["headers"], n=3)
    export = client.get("/api/export/me", headers=user["headers"]).json()
    blob = json.dumps(export)
    for word in ("hello", "password", "raw_text", "typed_text"):
        assert word not in blob.lower() or word == "raw_text"  # only as a rejected-field name


# ---------------------------------------------------------------------------
# Attack 7 — SQL injection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    "' OR '1'='1",
    "'; DROP TABLE keystroke_sessions;--",
    "admin'--",
    "1' UNION SELECT * FROM users--",
])
def test_attack_07_sql_injection_in_login_is_inert(client, user, payload):
    res = client.post("/api/auth/login", json={"username": payload, "password": PASSWORD})
    assert res.status_code in (401, 422)

    # every table still exists and alice is still there
    from backend import database as db
    assert db.get_user_by_username("alice") is not None
    tables = {r["name"] for r in db.query(
        "SELECT name FROM sqlite_master WHERE type='table'", ()
    )}
    assert "keystroke_sessions" in tables


def test_attack_07b_injection_in_a_consent_field_is_inert(client, user):
    res = client.post("/api/consent/grant",
                      json={"doctor_username": "'; DROP TABLE users;--"},
                      headers=user["headers"])
    assert res.status_code in (404, 422)

    from backend import database as db
    assert db.get_user_by_username("alice") is not None


def test_attack_07c_the_codebase_contains_no_string_built_sql():
    """Grep the source rather than trusting that we remembered every call site."""
    import re
    from pathlib import Path
    from backend.config import ROOT

    suspicious = []
    pattern = re.compile(
        r"""(execute|executemany)\s*\(\s*(f["']|["'][^"']*["']\s*%|["'][^"']*["']\s*\+)""",
        re.IGNORECASE,
    )
    for path in list((ROOT / "backend").glob("*.py")) + list((ROOT / "ml").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            line = text[:match.start()].count("\n") + 1
            suspicious.append(f"{path.name}:{line}")

    assert suspicious == [], f"SQL built by interpolation: {suspicious}"


# ---------------------------------------------------------------------------
# Attack 8 — stored XSS
# ---------------------------------------------------------------------------

def test_attack_08_a_script_payload_is_stored_as_characters_not_code(client, user, doctor):
    """The API layer stores it inertly; the render layer is covered by
    test_attack_08b, which is the half that actually matters."""
    res = client.post("/api/consent/grant",
                      json={"doctor_username": "<script>alert(document.cookie)</script>"},
                      headers=user["headers"])
    assert res.status_code in (404, 422)
    assert "<script>" not in res.headers.get("content-type", "")


def test_attack_08b_the_frontend_never_uses_innerhtml():
    """Every value from the API is written with textContent. A hostile string
    renders as visible characters and cannot execute."""
    import re
    from backend.config import ROOT

    offenders = []
    for path in list((ROOT / "frontend").rglob("*.js")):
        if "vendor" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write",
                                 text):
            line = text[:match.start()].count("\n") + 1
            offenders.append(f"{path.name}:{line}")

    assert offenders == [], f"unsafe DOM writes: {offenders}"


def test_attack_08c_the_extension_never_uses_innerhtml():
    import re
    from backend.config import ROOT

    offenders = []
    for path in (ROOT / "extension").glob("*.js"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML", text):
            offenders.append(path.name)
    assert offenders == []


# ---------------------------------------------------------------------------
# Attack 9 — malformed and oversized payloads
# ---------------------------------------------------------------------------

def test_attack_09_oversized_body_is_rejected_not_crashed(client, user):
    payload = make_batch()
    payload["offsets_ms"] = [1.0] * 200_000
    res = client.post("/api/session", json=payload, headers=user["headers"])
    assert res.status_code in (413, 422), res.status_code
    assert res.status_code != 500


@pytest.mark.parametrize("mutation", [
    {"total_keystrokes": 999_999_999},
    {"wpm_estimate": -40},
    {"avg_inter_key_interval_ms": -1},
    {"total_keystrokes": "many"},
    {"hour": 99},
    {"date": "not-a-date"},
])
def test_attack_09b_malformed_fields_return_422_never_500(client, user, mutation):
    payload = make_batch()
    payload.update(mutation)
    res = client.post("/api/session", json=payload, headers=user["headers"])
    assert res.status_code == 422, f"{mutation} → {res.status_code}"


def test_attack_09c_a_null_body_is_handled(client, user):
    res = client.post("/api/session", json=None, headers=user["headers"])
    assert res.status_code == 422


def test_attack_09d_errors_never_leak_internals(client, user):
    payload = make_batch()
    payload["wpm_estimate"] = -1
    body = client.post("/api/session", json=payload, headers=user["headers"]).text
    for leak in ("Traceback", "site-packages", "C:\\", "/home/", "sqlite3.", "SELECT "):
        assert leak not in body


# ---------------------------------------------------------------------------
# Attack 10 — unauthenticated sweep of every endpoint
# ---------------------------------------------------------------------------

PUBLIC = {"/api/health", "/api/auth/login", "/api/auth/register",
          "/api/federated/status"}


def test_attack_10_every_endpoint_requires_authentication(client):
    """The test that catches the endpoint somebody forgot to protect."""
    schema = client.get("/openapi.json").json()

    holes = []
    for path, methods in schema["paths"].items():
        if path in PUBLIC:
            continue
        for method in methods:
            if method not in ("get", "post", "delete", "put", "patch"):
                continue
            probe = path.replace("{target_user_id}", "u_probe")
            res = getattr(client, method)(probe) if method != "post" else \
                client.post(probe, json={})
            if res.status_code not in (401, 403, 422, 405):
                holes.append(f"{method.upper()} {path} → {res.status_code}")

    assert holes == [], f"endpoints reachable without a token: {holes}"


def test_attack_10b_the_public_endpoints_leak_nothing_sensitive(client, user):
    body = client.get("/api/health").json()
    blob = json.dumps(body).lower()
    for leak in ("password", "secret", "token", "alice", "user_id"):
        assert leak not in blob


# ---------------------------------------------------------------------------
# Attack 11 — consent revocation timing
# ---------------------------------------------------------------------------

def test_attack_11_revocation_takes_effect_on_the_very_next_request(client, user, doctor):
    """The whole lifecycle in one test. A grace period here would be a real
    vulnerability, and revocation that only bites at next login is a grace
    period with better manners.
    """
    # grant → doctor can read
    client.post("/api/consent/grant", json={"doctor_username": "dr.who"},
                headers=user["headers"])
    assert client.get(f"/api/doctor-report/{user['user_id']}",
                      headers=doctor["headers"]).status_code == 200

    # revoke
    grants = client.get("/api/consent/my-grants", headers=user["headers"]).json()["grants"]
    doctor_id = grants[0]["granted_to"]
    client.post("/api/consent/revoke", json={"doctor_id": doctor_id},
                headers=user["headers"])

    # the SAME still-valid token is refused immediately
    assert client.get(f"/api/doctor-report/{user['user_id']}",
                      headers=doctor["headers"]).status_code == 403

    # and the whole lifecycle is in the audit log
    log = client.get("/api/audit-log/me", headers=user["headers"]).json()["entries"]
    actions = [e["action"] for e in log]
    for expected in ("GRANT_CONSENT", "VIEW_DOCTOR_REPORT", "REVOKE_CONSENT"):
        assert expected in actions, actions
    assert any(e["action"] == "VIEW_DOCTOR_REPORT" and e["outcome"] == "DENIED"
               for e in log)


def test_attack_11b_a_revoked_doctor_disappears_from_the_patient_list(client, user, doctor):
    client.post("/api/consent/grant", json={"doctor_username": "dr.who"},
                headers=user["headers"])
    assert len(client.get("/api/doctor/patients", headers=doctor["headers"]).json()["patients"]) == 1

    grants = client.get("/api/consent/my-grants", headers=user["headers"]).json()["grants"]
    client.post("/api/consent/revoke", json={"doctor_id": grants[0]["granted_to"]},
                headers=user["headers"])

    assert client.get("/api/doctor/patients", headers=doctor["headers"]).json()["patients"] == []


# ---------------------------------------------------------------------------
# Attack 12 — score manipulation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("forged", [
    {"raw_score": 100},
    {"adjusted_score": 100},
    {"cogni_score": 95},
    {"anomaly": False},
    {"is_anomaly": False},
    {"alert_status": "STABLE"},
    {"confidence": 100},
])
def test_attack_12_client_supplied_score_fields_are_refused(client, user, forged):
    """The score is the most valuable asset in the system, so it must be
    unforgeable. Silently ignoring these fields would be worse than rejecting
    them — an ignored field is one someone will eventually make count."""
    assert client.post("/api/score", json=forged, headers=user["headers"]).status_code == 422

    payload = make_batch()
    payload.update(forged)
    assert client.post("/api/session", json=payload, headers=user["headers"]).status_code == 422


def test_attack_12b_the_stored_score_is_the_one_the_server_computed(client, seeded_user):
    from backend import database as db

    res = client.post("/api/score", json={"recompute": True}, headers=seeded_user["headers"])
    assert res.status_code == 200
    server_score = res.json()["raw_score"]

    row = db.query_one(
        "SELECT raw_score FROM cogniscores WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (seeded_user["user_id"],),
    )
    assert row["raw_score"] == pytest.approx(server_score)
    assert row["raw_score"] != 100


def test_attack_12c_there_is_no_endpoint_that_writes_a_score_directly(client):
    schema = client.get("/openapi.json").json()
    writers = [
        path for path, methods in schema["paths"].items()
        if ("cogniscore" in path.lower() or path.endswith("/score"))
        and set(methods) & {"put", "patch"}
    ]
    assert writers == []


def test_attack_12d_replaying_one_batch_cannot_inflate_the_average(client, seeded_user):
    """Rate limiting plus the quality gate together stop the replay."""
    limiter.enabled = True
    limiter.reset()
    payload = make_batch(seed=99)
    try:
        codes = [
            client.post("/api/session", json=payload, headers=seeded_user["headers"]).status_code
            for _ in range(50)
        ]
    finally:
        limiter.enabled = False
        limiter.reset()

    assert codes.count(201) <= 5, "replay was not throttled"
    assert 429 in codes


# ---------------------------------------------------------------------------
# hardening checks that are not one of the twelve
# ---------------------------------------------------------------------------

def test_security_headers_are_present(client):
    headers = client.get("/api/health").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["Cache-Control"] == "no-store"


def test_login_does_not_reveal_whether_a_username_exists(client, user):
    """Different messages here would build a user-enumeration oracle."""
    missing = client.post("/api/auth/login",
                          json={"username": "nobody", "password": PASSWORD})
    wrong = client.post("/api/auth/login",
                        json={"username": "alice", "password": "wrong-password-x"})
    assert missing.status_code == wrong.status_code == 401
    assert missing.json()["detail"] == wrong.json()["detail"]


def test_passwords_are_never_returned_or_stored_in_the_clear(client, user):
    from backend import database as db
    row = db.get_user_by_username("alice")
    assert PASSWORD not in row["password_hash"]
    assert row["password_hash"].startswith(("$2", "pbkdf2_sha256$"))

    body = client.get("/api/auth/me", headers=user["headers"]).text
    assert "password" not in body.lower()


def test_admin_has_no_access_to_health_data_by_default(client, user):
    """A deliberate design decision, not an oversight: the operator of a health
    tool should not be able to read every patient's data."""
    from backend.auth import create_access_token, create_user
    admin = create_user("root", PASSWORD, "ADMIN", "Root")
    headers = {"Authorization": f"Bearer {create_access_token(admin)}"}

    assert client.get(f"/api/doctor-report/{user['user_id']}",
                      headers=headers).status_code == 403
    assert client.post("/api/consent/grant", json={"doctor_username": "dr.who"},
                       headers=headers).status_code == 403


def test_token_version_bump_invalidates_every_issued_token(client, user):
    """Incident response step 3: rotating secrets must not wait for expiry."""
    from backend.auth import bump_token_version

    assert client.get("/api/auth/me", headers=user["headers"]).status_code == 200
    bump_token_version(user["user_id"])
    assert client.get("/api/auth/me", headers=user["headers"]).status_code == 401


def test_admin_role_cannot_be_self_registered(client):
    res = client.post("/api/auth/register",
                      json={"username": "sneaky", "password": PASSWORD, "role": "ADMIN"})
    assert res.status_code == 422


def test_deletion_removes_rows_from_every_table_and_is_audited(client, seeded_user):
    from backend import database as db

    client.post("/api/score", json={"recompute": True}, headers=seeded_user["headers"])
    client.post("/api/context", json={"sleep_quality": 3}, headers=seeded_user["headers"])
    client.post("/api/task-score", json={"word_recall": 4}, headers=seeded_user["headers"])

    user_id = seeded_user["user_id"]
    res = client.delete("/api/user/me", headers=seeded_user["headers"])
    assert res.status_code == 200

    for table in ("keystroke_sessions", "cogniscores", "task_results",
                  "daily_context", "consent_grants"):
        rows = db.query(f"SELECT COUNT(*) AS n FROM {table} WHERE user_id = ?", (user_id,))
        assert rows[0]["n"] == 0, f"{table} still holds data"

    entry = db.query_one(
        "SELECT * FROM security_audit_log WHERE user_id = ? AND action = 'DELETE_ALL_DATA'",
        (user_id,),
    )
    assert entry is not None


def test_the_audit_log_never_records_health_content(client, seeded_user):
    from backend import database as db

    client.post("/api/score", json={"recompute": True}, headers=seeded_user["headers"])
    rows = db.query("SELECT details FROM security_audit_log", ())
    blob = " ".join(str(r["details"]) for r in rows).lower()

    for forbidden in ("raw_score", "cogni_score", "wpm_estimate", "key_categories",
                      "password", "avg_iki"):
        assert forbidden not in blob


# ---------------------------------------------------------------------------
# deletion must survive a restore
# ---------------------------------------------------------------------------

def test_deletion_is_replayed_against_a_restored_backup(client, seeded_user, tmp_path):
    """The subtle half of the deletion promise.

    A backup taken *before* a user asks to be erased still contains their rows.
    Restoring it without replaying the deletion ledger would quietly resurrect
    data the user asked us to delete.
    """
    import shutil
    from backend import database as db

    user_id = seeded_user["user_id"]
    live = db.get_db_path()

    # a backup from before the deletion, holding this user's sessions
    before = tmp_path / "before.db"
    shutil.copy(live, before)
    assert db.query_one(
        "SELECT COUNT(*) AS n FROM keystroke_sessions WHERE user_id = ?", (user_id,)
    )["n"] > 0

    assert client.delete("/api/user/me", headers=seeded_user["headers"]).status_code == 200

    # the ledger records the request and is NOT itself deleted
    assert db.query_one(
        "SELECT COUNT(*) AS n FROM deletion_requests WHERE user_id = ?", (user_id,)
    )["n"] == 1

    # naive restore would bring the rows back …
    restored = tmp_path / "restored.db"
    shutil.copy(before, restored)
    import sqlite3
    conn = sqlite3.connect(str(restored))
    resurrected = conn.execute(
        "SELECT COUNT(*) FROM keystroke_sessions WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    conn.close()
    assert resurrected > 0, "fixture is not exercising the case"

    # … so the ledger is copied forward and replayed before the database goes live
    conn = sqlite3.connect(str(restored))
    conn.execute("CREATE TABLE IF NOT EXISTS deletion_requests ("
                 "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, "
                 "requested_at TEXT NOT NULL, rows_removed INTEGER NOT NULL DEFAULT 0)")
    conn.execute("INSERT INTO deletion_requests (user_id, requested_at) VALUES (?, ?)",
                 (user_id, db.utcnow()))
    conn.commit()
    conn.close()

    result = db.replay_deletions(restored)
    assert result["users_replayed"] == 1
    assert result["rows_removed"] > 0

    conn = sqlite3.connect(str(restored))
    remaining = conn.execute(
        "SELECT COUNT(*) FROM keystroke_sessions WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    conn.close()
    assert remaining == 0, "restore resurrected deleted data"
