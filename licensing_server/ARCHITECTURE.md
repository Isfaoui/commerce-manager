# Commerce Manager — Licensing System Architecture (v1)

## 1. Trust model in one paragraph

The desktop app ships with an **Ed25519 public key**. It trusts nothing else.
Every fact the app relies on — license type, expiration, device binding,
enabled features, active/disabled/revoked status — lives inside a JSON
payload that the server signs with the matching **private key** (which
never leaves the server). On every launch the app re-derives the current
device fingerprint, re-verifies the signature against the embedded public
key, and only then reads the fields. If the signature check fails for any
reason (edited file, wrong key, corrupted bytes), the app treats the
license as absent — never as "trust it anyway."

This is why this system needs no internet after activation: validation is
pure math against locally embedded, unforgeable data.

## 2. Component map

```
commerce_manager/
├── license/                  # ships INSIDE the .exe (client-side)
│   ├── crypto.py              # Ed25519 sign (server) / verify (client)
│   ├── device.py               # hardware fingerprint -> device_id
│   ├── models.py                # LicensePayload dataclass, enums, feature lists
│   ├── storage.py                # DPAPI-wrapped license.dat read/write
│   ├── validator.py               # pure offline validation state machine
│   ├── manager.py                   # orchestrates online activation + offline gate
│   └── public_key.py                 # AUTO-GENERATED, public key constant only
│
├── server/                   # runs on YOUR infrastructure, never shipped to users
│   ├── db.py                   # sqlite3 connection + repository functions
│   ├── schema.sql               # users / licenses / devices / license_logs / admin_sessions
│   ├── auth.py                    # POST /api/auth/login (customer login + trial issuance)
│   ├── licenses.py                  # reactivate + all /api/admin/licenses,/devices endpoints
│   ├── admin_auth.py                  # admin session login + require_admin decorator
│   ├── admin_views.py                   # server-rendered dashboard (search/issue/revoke/reset)
│   ├── templates/                        # admin_login.html, admin_dashboard.html
│   ├── rate_limit.py                       # in-memory sliding window limiter
│   └── app.py                                # Flask application factory
│
├── client/
│   └── main.py                # PyInstaller entry point: pywebview + local Flask + license gate
│
├── scripts/
│   ├── generate_keys.py       # one-time Ed25519 keypair generation
│   └── embed_public_key.py    # bakes public_key.pem into license/public_key.py at build time
│
└── requirements.txt
```

## 3. Database schema (SQLite, server-side only)

| Table            | Purpose                                                                 |
|-------------------|--------------------------------------------------------------------------|
| `users`            | Customer + admin accounts. `is_admin` flag distinguishes the two.         |
| `licenses`          | Every license ever issued (append-only audit trail; old ones get `status='revoked'` on upgrade, never deleted). Stores `payload_json` + `signature` verbatim — the exact bytes that were signed — so you can always re-verify what was actually shipped to a customer. |
| `devices`             | Which device_id(s) each customer has activated on. `is_active` flips to 0 on admin "Reset Device." |
| `license_logs`          | Full audit log: logins, issuances, reactivations, device resets, disables, revokes, failed validations. |
| `admin_sessions`          | Short-lived (8h) admin dashboard session tokens. |

See `server/schema.sql` for full DDL with constraints and indexes.

## 4. The signed payload (what's inside `license.dat`)

```json
{
  "payload": {
    "license_id": "uuid",
    "customer_id": "uuid",
    "license_type": "trial | professional",
    "status": "active | disabled | revoked",
    "device_id": "sha256 hex string",
    "features": ["pos_sales", "inventory_full", ...],
    "issued_at": 1735500000,
    "expires_at": 1736104800,
    "issued_by": "admin@company.com | self-service",
    "schema_version": 1
  },
  "signature": "base64-encoded-ed25519-signature"
}
```

`canonical_json()` (sorted keys, fixed separators) is what actually gets
signed — this guarantees the server and client hash identical bytes
regardless of dict ordering.

## 5. Device lock design

`license/device.py` combines four Windows identifiers (Machine GUID, CPU
ID, motherboard serial, disk serial), SHA-256-hashes each individually,
then SHA-256-hashes the sorted, concatenated set into one `device_id`.
Individual collectors degrade gracefully (`_safe()` catches WMI/registry
failures so one blocked query doesn't crash fingerprinting) — but the
license validator itself always requires an **exact** `device_id` match;
there is no fuzzy acceptance at the security boundary. A separate
`matches_with_tolerance()` helper exists only to help an admin diagnose
*why* a match failed (e.g. "3 of 4 components matched, might be a RAM/CPU
swap") before deciding whether to grant a manual device reset.

## 6. Anti-tamper layers, in order of importance

1. **Ed25519 signature** — the real boundary. Any edit to the payload
   invalidates it. This is what makes the system secure even if the file
   is fully readable/copyable.
2. **DPAPI encryption at rest** (`storage.py`) — defense in depth against
   casual copying of `license.dat` to another machine or user profile;
   scoped to the Windows user via `CryptProtectData`.
3. **ProgramData storage location** — machine-scoped, requires elevated
   rights to write, harder to sync via OneDrive/Dropbox than a roaming
   profile folder.
4. **Clock-rollback guard** (`validator.py`) — a `state.json` sidecar
   records the last successfully-validated timestamp; if the OS clock is
   now *earlier* than that, validation fails. Stops the classic "roll the
   clock back before trial expiry" bypass.
5. **PyInstaller build hardening** (recommended, not code in this repo):
   - Build with `--key` obfuscation is *not* real protection (PyInstaller's
     bytecode encryption was removed/weak); treat the client as
     reverse-engineerable and never rely on client-side secrecy for
     anything except UX. The private key is what actually matters, and it
     never ships.
   - Strip debug symbols, consider PyArmor/Themida if you need extra
     friction against casual tampering (optional, not a v1 blocker).

## 7. Why the flows stay offline

- **Every launch**: `LicenseManager.bootstrap()` only reads a local file,
  hashes local hardware IDs, and does public-key math. Zero network calls.
- **Login/Activation/Renewal**: the only three flows that hit
  `POST /api/auth/login`, `POST /api/licenses/reactivate` (and a future
  `/api/licenses/renew`). All other endpoints under `/api/admin/*` are
  called by the ADMIN's browser against the server — never by the customer's
  desktop app.

## 8. Step-by-step implementation plan

1. **Generate the keypair** (offline, once): `python scripts/generate_keys.py`.
   Store `keys/private_key.pem` in your server's secrets manager (or at
   minimum an `.env` excluded from git + restrictive file permissions).
2. **Stand up the server**: `pip install -r requirements.txt`, set
   `FLASK_SECRET_KEY` and `LICENSE_PRIVATE_KEY_PATH` env vars, run
   `python -m server.app`. First run auto-creates `server/licensing.db`
   from `schema.sql`.
3. **Seed an admin user** manually (small one-off script or a `flask
   shell` snippet) — hash a password with `argon2.PasswordHasher().hash(...)`
   and insert into `users` with `is_admin = 1`.
4. **Embed the public key** into the client:
   `python scripts/embed_public_key.py keys/public_key.pem`.
5. **Wire up the pywebview frontend**: your login HTML/JS calls
   `POST /api/license/login` (the LOCAL Flask app in `client/main.py`,
   port 8765) which internally calls the remote server. On success,
   reload the webview to `/pos`.
6. **Protect every POS route** with the `require_valid_license` decorator
   shown in `client/main.py` — never gate access purely in JavaScript.
7. **Build with PyInstaller**: bundle `license/`, `client/`, your HTML/JS
   assets, and the `cryptography`/`pywin32`/`pywebview` packages. Test the
   built `.exe` on a clean VM without your dev Python environment.
8. **Test the full lifecycle**: fresh install → login → trial issued →
   close/reopen app offline (airplane mode) → still works → let trial
   expire (or fast-forward `expires_at` in a test DB row) → blocked with
   the correct message → admin issues Professional → reactivate → unlimited
   access.
9. **Test device lock**: activate on VM A, copy `license.dat` to VM B →
   must fail with `WRONG_DEVICE`. Use admin "Reset Device" → VM B can now
   activate; VM A's local file remains but will now itself fail
   `WRONG_DEVICE` if it tries to reactivate elsewhere... note VM A itself
   still holds a validly-signed license bound to its own device_id, so it
   keeps working offline until you also revoke that specific license_id
   from the admin panel if you need to hard-cut it off.
10. **Set up TLS** in front of the server (nginx/Caddy reverse proxy or a
    managed load balancer) — `/api/auth/login` sends a plaintext password
    over the wire and must never run on bare HTTP in production.

## 9. Security recommendations checklist

- [ ] Private key stored in a secrets manager, never in the repo, never on
      any machine besides the signing server.
- [ ] TLS termination in front of Flask (HSTS enabled).
- [ ] `argon2id` for password hashing (already wired via `argon2-cffi`),
      never plain SHA/MD5.
- [ ] Rate limiting on `/api/auth/login` and `/api/admin/login` (basic
      in-memory limiter included; move to Redis-backed if you scale to
      multiple server processes).
- [ ] Generic "Invalid email or password" message — never reveal whether
      the email exists.
- [ ] All admin mutation endpoints behind `require_admin` + logged to
      `license_logs` with actor + IP.
- [ ] `license.dat` treated as append-of-audit-trail on the server
      (`licenses` table rows are superseded, not deleted) so you can
      always investigate a disputed activation.
- [ ] Plan a key-rotation runbook now, even though v1 won't need it:
      generate new keypair → ship client update with new public key
      (supporting BOTH old+new public keys during a transition window) →
      re-issue all active licenses signed with the new key on next
      validation/reactivation → retire the old key after the transition
      window closes.
- [ ] Consider a short-lived local "grace period" (e.g. allow N days past
      `expires_at` before hard-blocking) only if your business wants that
      UX — the current implementation hard-blocks exactly at `expires_at`.

## 10. Explicitly out of scope for v1 (flagged, not built)

- License **renewal** endpoint (`/api/licenses/renew`) — schema and
  `license_type`/`expires_at` fields already support it; wire up a
  dedicated route + admin UI when you define renewal business rules
  (grace periods, proration, etc.).
- Multi-seat / floating licenses (current model is strictly one device
  per license, matching your stated requirement).
- Payment processing / billing — "Admin upgrades customer" is modeled as
  a manual admin action (`POST /api/admin/licenses/professional`); wire a
  webhook from your payment provider into that same endpoint when ready.
