# Strategy cards

One JSON per analyst, each loading into `app.tournament.models.StrategyCard`.

Every card declares `designed_through`, which the model refuses to accept past
`DESIGN_THROUGH` (2026-02-13). The trading window starts 2026-02-17. An analyst who
saw the trading window would be fitting the data they are about to be scored on, so
the cutoff is enforced by the type rather than by trust.
