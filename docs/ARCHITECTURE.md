# Architecture

## Processes

| Process | Repo | Owns | Talks to |
|---|---|---|---|
| Frontend (React + Vite, served by nginx in Docker) | this repo, `frontend/` | UI state only | Backend `/api/*` with a session cookie |
| Backend (FastAPI) | this repo, `backend/` | Computation, auth, market-data cache, research records | Data service; Yahoo, SEC EDGAR, FRED; Anthropic (optional) |
| Data service (FastAPI) | `investing-dashboard-db` | **All personal data**: ledger, account manifest, sector labels, Planner board | Nothing outbound |

The browser never talks to the data service. The backend reaches it with a bearer token over
loopback or a private network.

## The personal-data boundary: `app.datasource`

Every backend module that needs personal data goes through four functions:

```python
ledger_db_path(settings) -> Path          # read-only SQLite path, fresh
ledger_writer(settings)  -> ContextManager[Path]   # writable; committed on clean exit
read_document(key, settings) -> str | None # "accounts-manifest" | "sectors" | "planner-board"
write_document(key, content, settings)
```

`Settings.data_source` selects the implementation:

| Mode | Ledger | Documents | Used by |
|---|---|---|---|
| `local` | `data/store/ledger.sqlite` | files under `data/` | test suite, offline development |
| `demo` | as `local`, seeded on first use with an invented portfolio (`app/datasource/demo.py`) | seeded if absent | fresh clones, screenshots |
| `remote` | replica pulled from the data service | REST | real use |

### Remote reads

```
request ─▶ ledger_db_path()
            │  (at most every INVDASH_DB_SERVICE_POLL_S)
            ├─▶ GET /v1/ledger            → {revision}
            │     same as local replica?  → use cache/ledger-replica/r{rev}.sqlite
            └─▶ GET /v1/ledger/snapshot   → build r{new}.sqlite via the app's own migrate(), swap in
```

- Each revision gets its own replica file. On Windows, a file another request still has open
  can't be replaced, and a reader mid-query must never see a half-written ledger. Old replicas
  are pruned as soon as they're no longer open.
- If the service is down, the last replica keeps serving and a warning is logged. If there's no
  replica at all, the request gets `503 data_service_unavailable`.
- The snapshot carries `schema_version`. A mismatch refuses the data, so a client can't misread
  it.

### Remote writes (imports)

```
ledger_writer() ─▶ copy replica r{N} to a private working file
                   existing ingest pipeline writes into it (unchanged code)
                   diff working copy vs r{N} on primary keys, table by table
                   POST /v1/ledger/changesets {base_revision: N, tables: {...}}
                       200 → refresh replica
                       412 → someone else wrote first; nothing applied; re-run the import
                       409 → an append-only row would be rewritten; nothing applied
```

Transactions, raw imports and raw rows are append-only. Accounts, instruments and symbol aliases
can be updated.

## Ledger → figures

```
broker CSV ─▶ adapter (per broker) ─▶ canonical Transaction rows ─▶ ledger (append-only, provenance)
                                                                      │
             canonicalize (cross-broker instrument identity) ◀────────┘
                       │
                       ├─▶ lots / cash roll-forward ─▶ Portfolio, Account, Planner
                       └─▶ disposals + wash-sale engine ─▶ Tax report, Form 8949, wash-sale tracker
```

Nothing derived is persisted. Every page recomputes from the ledger, so a cached tax figure can't
disagree with the ledger underneath it.

## Research side

The research side has no personal data, so everything here can be committed.

- `rules/`, `indicators/` are a decision-table DSL over daily and intraday bars (DuckDB/Parquet
  store).
- `backtest/`, `tournament/` run round-based competitions between strategy cards. Every round's
  brief, cards, trade logs and reports are kept under `data/rounds/`.
- `evolution/` proposes, tests and promotes cards. Promotions need multiple-comparison-corrected
  evidence, and a person approves seating a card on the paper desk.
- `paperdesk/` trades seated cards forward on paper to build live records.
- `agents/`, `tradingagents/`, `vibedesk/`, `workflow/`, `manager/` are Claude-backed desks. They
  write prose, never orders. Their output passes a grounding gate that rejects numbers absent
  from the evidence they were given.

## Auth

`app/auth` provides scrypt password hashes, server-side sessions, and per-user and per-IP login
throttling. A raw-ASGI gate keeps server-sent-event streams working. Roles are `owner` and
`member`:

- Holdings, tax and manager prefixes are owner-only.
- Model-spending and long-running write routes need the owner.
- Security headers are added to every `/api` response.
