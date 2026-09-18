# Stella Implementation Ledger

## Checkpoint

- Verified at: 2026-09-18 08:23:17 +0700
- Repository: `D:/10_Projects/Project_Stella/stellarium`
- Branch: `main`
- Baseline HEAD before this working batch: `fc533dd0c7`
- Scope: migration hardening, stable profile identity, active-profile runtime binding, and one-click web migration wizard.
- Safety: no migration or rollback was run against the original Hermes installation; no commit or push has been made for this batch.

## Implemented in this batch

- Rollback validates the complete manifest before destructive work.
- Staging, backup, and per-file receipt paths are bound to the generated migration ID and exact internal directory templates.
- New v2 manifests persist `planned` then `committed` intent records and receipts; interrupted commits can be recovered safely.
- Legacy v1 manifests remain parseable but rollback is explicitly non-destructive because they lack authenticated receipts.
- Malformed manifest collections/records fail closed.
- Non-config sensitive/opaque files are excluded fail-closed; config query credentials are redacted structurally.
- Source auto-detection and inspection reject symlinks, junctions, reparse points, and unsafe ancestors.
- Gateway status and startup watchdog process-home paths follow the active Stella profile.
- Named child migrations are bound to their parent migration ID.
- Profile directory names are the canonical immutable profile IDs; unsafe directory names are ignored.
- `STELLA_HOME` keeps its lexical path until filesystem safety checks reject junctions/reparse points.
- Active-profile resolution has a non-mutating path for process startup.
- Explicit `HERMES_HOME` takes precedence; otherwise Hermes process-home resolution follows the active Stella profile when one exists.
- FastAPI migration preview/execute reject blank `source_path` values.
- Web client has typed Stella migration API calls.
- Web UI has `/profiles/migrate`, linked from Profiles as `Import Hermes`, with detect, component selection, preview, conflict/overwrite decision, execute progress, and rollback controls.

## Evidence

### Python

- `pytest tests/test_stella_architecture.py -q -ra`: `37 passed, 4 skipped` after receipt, crash-recovery, legacy, secret, junction, and parent-binding fixes.
- `pytest tests/test_hermes_constants.py tests/test_hermes_home_profile_warning.py tests/gateway/test_startup_watchdog.py -q -ra`: `116 passed, 13 skipped`.
- `compileall` on touched Python files: passed.
- Ruff on touched Python files: passed.
- `git diff --check`: passed.
- Full `pytest -q --tb=short`: after installing declared ACP/aiohttp/Telegram test dependencies, collection still has two unrelated Windows POSIX errors (`os.geteuid`, `fcntl`). Excluding those, the first broad failure is the pre-existing ACP Windows file-URI path conversion (`WinError 3`); the run was stopped before a complete total.
- Web: `43 files / 308 tests passed`; typecheck, lint, and production build passed.

### Web

- `npm run test -- --run`: `43` files, `308 passed`.
- `npm run typecheck`: passed.
- `npm run lint -- --quiet`: passed.
- `npm run build`: passed after correcting Badge tone types.

### Manual/security probes

- Windows junction creation/detection/manager rejection: passed.
- Malicious rollback path probe: now covered by a passing regression test; user file remains intact.
- Metadata ID mismatch: now covered by a passing regression test; directory identity wins.
- Blank API source paths: now covered by passing direct Pydantic tests.
- Non-mutating active-profile resolver: now covered by a passing regression test.

## Review state

- Latest independent review before the final fixes: `REQUEST_CHANGES`; it identified non-config secret leakage, junction auto-detection, watchdog scope, legacy manifest rollback, and crash consistency.
- Those findings are now covered by code changes and regression tests; a fresh read-only review of the current working tree is dispatched and still pending.
- Production-ready/approve/push: **not authorized** until the fresh review is approved.

## Remaining gates

1. Fresh independent reviewer must inspect the current post-fix diff and return `APPROVE`.
2. Full repository pytest remains a separate Windows/platform gate: two POSIX-only collection errors remain, and the first excluded run failure is an unchanged ACP Windows file-URI conversion test.
3. No migration or rollback against the original Hermes installation is permitted in this batch.
4. After independent approval, optionally create a local commit; do not push without explicit authorization.

## Closed gates

- Combined Stella architecture/security, Hermes constants, classic fallback warning, startup watchdog, gateway status, and startup-fast: `252 passed, 17 skipped in 230.22s` after HMAC receipts, backup hash validation, parent-child intent and receipt interruption recovery, early resolver reparse protection, dangling-root rejection, nested JSON/query/fragment/PEM filtering, and strict explicit environment references.
- Web acceptance: `43 test files / 308 tests passed` with `--testTimeout=30000`; typecheck, lint, and production build passed.
- Latest quality: Ruff, compileall, `git diff --check`, and source-sensitive scan passed.
- Final current-tree read-only review dispatched after these latest changes; no approval is claimed yet.
- Gateway status after resolver/fallback fixes: `78 passed`.
- Startup-fast guard suite after restoring Hermes engine label: `4 passed`.
- Web suite/typecheck/lint/production build remain green: `308 tests passed`; all checks pass.
- Compileall, Ruff, diff check, and source secret-assignment scan passed.
- Windows junction probe and active-profile/runtime probes passed.
- No credential values are recorded in this ledger.
