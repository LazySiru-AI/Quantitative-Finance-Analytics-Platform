# `data/` — raw brokerage exports

Drop broker CSV exports here. The ingestion layer detects the right adapter by header signature.

> **Remote mode** (`INVDASH_DATA_SOURCE=remote`): this folder is only an inbox. Imported rows,
> the account manifest and sector labels are stored by the data service, not here.

## Importing

```bash
python -m app.ingest --init      # write accounts.toml covering the files here
python -m app.ingest --dry-run   # show which account each file resolves to
python -m app.ingest             # import
```

Or from the **Activity** page, once the manifest exists. Either way the files are read from this
directory — nothing is uploaded.

### `accounts.toml` — which account each file belongs to

A file's header identifies its *broker*, and nothing identifies its *account*: `RH taxable.csv` and
`RH Roth.csv` are structurally identical, and only you know which is which. So each file gets an
entry:

```toml
[[account]]
file = "RH Roth.csv"
account_id = "rh-roth"
label = "RH Roth"
tax_treatment = "roth_ira"     # required — no default
account_type = "retirement"    # default: cash
```

`--init` writes this for you with the broker already detected, leaving `tax_treatment` blank.
Fill it in rather than guessing from the filename: it decides whether an account's gains are
reported at all, and whether a repurchase inside it destroys a loss permanently under
Rev. Rul. 2008-5 instead of merely deferring it.

`account_type` matters less but is not cosmetic — a cash account is checked for a negative running
balance and a margin account is not.

In local mode the manifest is gitignored along with the exports; in remote mode it is stored by the
data service.

## These files are deliberately untracked

`.gitignore` excludes `data/*.csv` and friends. They contain real account activity, positions, and dollar
amounts, so they stay local and never enter git history — a repo that gets pushed somewhere cannot leak
them. The app reads them straight off disk; nothing depends on them being tracked.

Tests use **redacted fixtures** under `tests/fixtures/`, which *are* tracked. Those preserve each broker's
structural quirks (column names, row shapes, edge cases) with scrambled symbols and amounts.

If you want the raw exports versioned anyway, remove the `data/*.csv` line from `.gitignore` — but only do
that on a repo you are certain will stay private.

## Supported exports

| Broker | Export | Notes |
|---|---|---|
| Robinhood | Account activity CSV | Full activity ledger: trades, dividends, fees, transfers |
| Webull | Orders Records CSV | **Orders only** -- no dividends, fees or transfers, so declare cash in the manifest |
| SoFi | Activity CSV | Activity ledger |

## Re-importing is safe

Exports are ingested idempotently — every file is hashed and every row gets a deterministic ID, so
re-importing an overlapping export is a no-op rather than a source of duplicate lots. Just drop the newer
export in alongside the old one.
