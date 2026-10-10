# Basis reconstruction — read this first

**The full document moved to `docs/local/basis-reconstruction.md`, tracked nowhere.** It quotes the
real ledger — per-lot dollar figures, named accounts and the reconstruction of transferred lots
against the owner's own statements — so it lives only on machines that already hold that ledger
(PII audit 2026-09-10, PII-03). This stub is tracked so other docs have something to link to.

## What carries over without the money

- Shares that arrive by transfer with the basis stripped are the whole source of phantom realised
  gain; tracing each to its original purchase and applying it via `TransferBasis` / `opening_position`
  removes it.
- Any lot whose acquisition is in no collected document stays `$0`-basis and is listed in the
  manifest as needing the broker's 1099-B, never guessed.
- The tooling is `app.tax.basis_audit`; the engine path is `data/accounts.toml` + `python -m app.ingest`.
