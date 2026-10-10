"""The manager desk -- an agent-curated second Overview with a chat and self-commissioned research.

Design: `docs/MANAGER-DESK-PLAN.md`. Wire contract: `app.manager.models` (pinned; every other module
in this package and the frontend mirror it field-for-field).

Package layout, one module per layer of the design:

- `models`     -- the pinned wire + on-disk shapes (layer-agnostic; nothing else defines a shape)
- `sources`    -- layer A, the information bus: `collect()` reads every app surface in-process
- `snapshots`  -- layer B, persist one snapshot per day per scope and `diff()` two into a `ChangeSet`
- `rules`      -- layer B, the change-detector catalogue `diff()` runs (one pure function per rule)
- `evidence`   -- layer C, mint an `EvidencePack` from a snapshot + change set for `run_grounded`
- `pipeline`   -- layer C, the manager `DeskRun`: collect -> triage -> synthesis -> research_plan ->
                  commission -> brief
- `chat`       -- layer C, grounded manager chat threads
- `service`    -- the thin policy layer the router calls (caps, 404/409/503 translation)
- `loop`       -- the opt-in in-process daily-brief daemon
"""
