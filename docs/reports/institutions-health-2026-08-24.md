# Institutions health check, 2026-08-24 — all 22 funds measured live, one real defect found and fixed

**Not investment advice.**

The owner reported the Institutions tab broken for "Cathie Wood" (`ARKINVEST`, ARK Investment
Management LLC, CIK `0001697748`). This report drives every one of the 22 tracked funds end to end
against live SEC EDGAR — both `app.institutions.service.load_latest`/`load_delta` directly and the
`/api/institutions/{key}/holdings` / `/{key}/changes` HTTP endpoints — before touching a line of
code, per the instruction that measurement precedes any fix. It also inspects `ARKINVEST`'s real
parsed holdings for the data-quality defect the repo already knows about (ARK's OpenAI Group PBC
Series C position with no CUSIP/ISIN/ticker/LEI), and reads its real 13F filing history.

**Headline finding: `ARKINVEST` is not broken.** Both the service layer and the HTTP layer resolved
it cleanly against live EDGAR — 191 holdings, a 198-row delta, and no data-quality defects (no
sentinel-keyed rows, no duplicate CUSIPs, weights summing to 1, sensible dollar values). The
documented OpenAI hazard belongs to `ARKK`'s NPORT-P (the ETF), not `ARKINVEST`'s 13F (the manager,
"Cathie Wood") — those are different filings from different entities under different CIKs, and the
OpenAI hazard was already fixed and covered by a regression test before this pass began (see
`tests/test_institutions_parse.py::TestNportSentinelIdentifiers`, and
`docs/reports/uat-runs-9-11.md`).

What *was* found, live: one transient `ProviderUnavailable` on `VTI`'s `load_latest` call — EDGAR's
browse-edgar Atom feed hit the client's 15-second timeout on the very first attempt of a completely
polite, serially-delayed probe, then succeeded on every later call for the same fund, including
`VTI`'s own `load_delta` call moments later. `EdgarClient` had no retry for this class of failure:
one slow SEC response anywhere in a call — and `load_latest`/`load_delta` for an NPORT fund can issue
up to ten sequential document fetches, since NPORT candidates carry no period metadata and every one
must be opened to learn what it reports (`app.institutions.service._snapshots_nport`) — failed the
entire request with no recovery. That is fixed below.

## 1. Before table — every fund, live, before any code change

Measured serially with a 1.5s delay between calls (SEC EDGAR rate-limits, and `RateLimited` is one
of the failure modes under test, so a polite pace matters). Service-layer columns are
`service.load_latest` / `service.load_delta`; API columns are the HTTP status of
`GET /api/institutions/{key}/holdings` and `/{key}/changes`, measured in a second, separate pass
immediately afterward (so `VTI`'s API row reflects the retry-free code, seconds after its one
transient failure had already cleared on its own).

| Key | Source | `load_latest` | `load_delta` | `/holdings` | `/changes` | Holdings | Error (if any) |
|---|---|---|---|---|---|---:|---|
| QQQ | NPORT | OK | OK | 200 | 200 | 102 | — |
| IVV | NPORT | OK | OK | 200 | 200 | 506 | — |
| VOO | NPORT | OK | OK | 200 | 200 | 518 | — |
| VTI | NPORT | **FAIL** | OK | 200 | 200 | — | `ProviderUnavailable: edgar timed out fetching https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=S000002848&type=NPORT-P&dateb=&owner=include&count=10&output=atom` (15.0s, hit the timeout ceiling exactly) |
| IWM | NPORT | OK | OK | 200 | 200 | 1946 | — |
| SCHD | NPORT | OK | OK | 200 | 200 | 102 | — |
| ARKK | NPORT | OK | OK | 200 | 200 | 46 | — |
| XLE | NPORT | OK | OK | 200 | 200 | 24 | — |
| BRK | 13F | OK | OK | 200 | 200 | 29 | — |
| **ARKINVEST** | **13F** | **OK** | **OK** | **200** | **200** | **191** | **—** |
| PERSHING | 13F | OK | OK | 200 | 200 | 11 | — |
| SCION | 13F | OK | OK | 200 | 200 | 8 | — |
| APPALOOSA | 13F | OK | OK | 200 | 200 | 27 | — |
| DUQUESNE | 13F | OK | OK | 200 | 200 | 95 | — |
| SOROS | 13F | OK | OK | 200 | 200 | 266 | — |
| THIRDPOINT | 13F | OK | OK | 200 | 200 | 43 | — |
| ELLIOTT | 13F | OK | OK | 200 | 200 | 29 | — |
| TIGERGLOBAL | 13F | OK | OK | 200 | 200 | 46 | — |
| COATUE | 13F | OK | OK | 200 | 200 | 66 | — |
| LONEPINE | 13F | OK | OK | 200 | 200 | 34 | — |
| BRIDGEWATER | 13F | OK | OK | 200 | 200 | 997 | — |
| RENTECH | 13F | OK | OK | 200 | 200 | 3140 | — |

**21 of 22 funds succeeded on every call, on the first live pass, before any code change.** The one
failure (`VTI`) was not fund-specific and not reproducible on retry — the identical call, made
seconds later for the same fund, succeeded, and every other call this probe made (43 of 44
service-layer calls, all 44 API-layer calls) succeeded outright.

## 2. What was actually wrong with ARKINVEST / "Cathie Wood"

**Nothing, measured live on 2026-08-24.** In detail:

- `service.load_latest("ARKINVEST", ...)` returned period `2026-06-30`, filed `2026-08-14`,
  accession `0001104659-26-096910`, `total_value=$15,402,788,184`, 191 holdings, in 0.52s.
- `service.load_delta("ARKINVEST", ...)` diffed `2026-03-31` → `2026-06-30`: 198 changes
  (16 new, 7 exit, 79 add, 95 trim, 1 hold).
- Data-quality inspection of the parsed snapshot found: weights summing to 1 (to 24 decimal
  places), zero duplicate CUSIP keys, zero sentinel-keyed rows (`N/A`/`ROW:`/`NAME:`/`LEI:` etc. —
  the one row with a non-9-character key, `00214Q104-CALL`, is a long call option on ARK's own
  ARKK ETF, correctly suffixed per `parse_13f` point 5, not a defect), zero non-positive values or
  negative share counts, and dollar figures in the expected range top to bottom (Tesla at
  $1.16bn/7.5% down to a $344 SPDR position at 0.000002%).
- `EdgarClient.holdings_document_url` resolved cleanly: ARKINVEST's real filing directory
  (`https://www.sec.gov/Archives/edgar/data/1697748/000110465926096910/index.json`) contains
  exactly one non-`primary_doc.xml` XML file (`infotable.xml`) — no ambiguity in the
  alphabetical-first candidate selection that a filer with multiple auxiliary XML exhibits could in
  principle create.
- Its last 20 quarterly 13F-HR filings (`0001104659-21-137564` through `-26-096910`) are a clean,
  unbroken quarterly cadence with no amendments and no missing `reportDate` — nothing in the
  filing history that the candidate-selection window in `service.load_snapshots` could mishandle.
- A cold-cache, concurrent simulation of the realistic browser case — `/holdings` and `/changes`
  requested at the same instant, against a freshly emptied cache directory, the way a first tab
  switch to ARKINVEST actually behaves — completed both in 1.1–1.4s with no rate limiting.

**The documented "OpenAI" hazard is a different fund.** `ARK's OpenAI Group PBC Series C position
has no CUSIP, ISIN, ticker or LEI` (`backend/app/institutions/parse.py:107` and `:454`, and
`docs/reports/uat-runs-9-11.md`) is a real defect that was found and fixed in **`ARKK`'s NPORT-P**
(`backend/app/institutions/parse.py::_resolve_nport_key`, exercised by
`tests/test_institutions_parse.py::TestNportSentinelIdentifiers`, including
`test_a_named_position_without_identifiers_keys_on_its_name` naming that exact $177,028,452.35
position). `ARKINVEST` — ARK Investment Management LLC, the 13F manager labeled "Cathie Wood" in
`catalog.py` — is a completely different entity, different CIK, different filing form, and a 13F's
Section 13(f) scope would not carry a private placement like OpenAI Group PBC Series C in the first
place. Confusing the two is an easy mistake for a reader (`tests/test_institutions_deltas.py
::TestCatalogPrincipals::test_the_requested_names_are_present_and_correctly_attached` exists
specifically to keep them straight in the catalog), but it means the already-fixed OpenAI defect is
not, and never was, an ARKINVEST defect.

## 3. Every other broken fund, with its real error

Only one: **`VTI`**, `service.load_latest`, live SEC EDGAR call:

```
ProviderUnavailable: edgar timed out fetching
https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=S000002848&type=NPORT-P&dateb=&owner=include&count=10&output=atom
(15.02s elapsed — the client's own 15.0s httpx timeout)
```

This is the client's `list_series_filings` call (the very first HTTP request `load_latest` makes for
an NPORT fund) hitting SEC's own 15-second-plus response time on one particular request. It is not
`VTI`-specific — SEC EDGAR's browse-edgar endpoint is known to be slower and less consistent than
`data.sec.gov`'s submissions JSON, and every NPORT fund in the catalog goes through it. It self-healed
immediately: `VTI`'s own `load_delta` call, made ~1.5s later in the same probe run, succeeded; a
second full live probe (see the after-table, §5) succeeded on the first attempt for every one of the
22 funds including `VTI`. Before this pass, `EdgarClient` had no retry for this failure class at all
— a single slow response anywhere in a request chain (and an NPORT `load_latest`/`load_delta` can
issue up to ten sequential document fetches on top of the listing call, since
`_snapshots_nport` must open every NPORT candidate to learn its reporting period) failed the whole
call outright. That gap is real, general (not `VTI`- or `ARKINVEST`-specific), and is the fix in §4.

## 4. Files changed

- `backend/app/institutions/edgar.py` — `EdgarClient._get` now retries once (`_MAX_ATTEMPTS = 2`,
  `_RETRY_BACKOFF_SECONDS = 0.3`) on a timeout, a transport-level error, or a 5xx response — the
  failure modes that are ordinarily a momentary SEC blip, per the `VTI` failure captured live in
  this pass. A 429 (`RateLimited`) and any non-429 4xx (`ProviderResponseError`) are deliberately
  **never** retried: SEC is explicitly asking for less traffic on a 429, and a malformed request or
  changed endpoint shape does not become well-formed on a second try. The retry is small and bounded
  on purpose — one extra attempt for a blip, not a hammering loop, consistent with the "polite,
  serial, delayed" posture the rest of this feature already takes toward SEC's fair-access policy.
- `tests/test_institutions_edgar.py` — adds `TestRetryOnTransientFailure` (7 tests): a
  timeout-then-success and a transport-error-then-success and a 5xx-then-success each recover on
  the retry and make exactly 2 requests; a persistent timeout and a persistent 5xx still raise
  `ProviderUnavailable` after exhausting the budget (exactly `_MAX_ATTEMPTS` requests, never
  hanging or retrying forever); a 429 and a non-429 4xx are each confirmed to make exactly **one**
  request, never retried. Also adds an autouse `_no_retry_backoff` fixture that zeroes
  `_RETRY_BACKOFF_SECONDS` for every test in the file (mirroring the existing precedent in
  `backend/app/db/duck.py::_replace_with_retry` / `tests/test_stores.py`), so the suite stays fast
  and deterministic — no test in this file makes a real network call or depends on real wall-clock
  timing.
- `docs/reports/institutions-health-2026-08-24.md` — this report.

No other file was touched. `app.institutions.parse`, `app.institutions.deltas`,
`app.institutions.catalog`, `app.institutions.holders`, and `app.api.institutions` were read and
measured against but needed no change — every honesty invariant they encode (share-count-only
`Action` classification, CUSIP-only position matching, `InsufficientHistory` as 409 not an empty 200,
the `N/A`-sentinel guards in `parse_nport`) held up against all 22 funds' real, live filings.

## 5. After table — every fund, live, after the fix

Re-run in full against live SEC EDGAR after the `edgar.py` change landed (some responses served from
the same 6-hour HTTP cache the app always uses; this validates the fixed code path end to end, not
just that a stale cache masked the earlier gap — the probe calls `service.load_latest` and
`service.load_delta` directly, so a retry would fire the same way whether the underlying response was
freshly fetched or cache-served).

| Key | Source | `load_latest` | `load_delta` | Holdings |
|---|---|---|---|---:|
| QQQ | NPORT | OK | OK | 102 |
| IVV | NPORT | OK | OK | 506 |
| VOO | NPORT | OK | OK | 518 |
| VTI | NPORT | **OK** | OK | 3522 |
| IWM | NPORT | OK | OK | 1946 |
| SCHD | NPORT | OK | OK | 102 |
| ARKK | NPORT | OK | OK | 46 |
| XLE | NPORT | OK | OK | 24 |
| BRK | 13F | OK | OK | 29 |
| **ARKINVEST** | **13F** | **OK** | **OK** | **191** |
| PERSHING | 13F | OK | OK | 11 |
| SCION | 13F | OK | OK | 8 |
| APPALOOSA | 13F | OK | OK | 27 |
| DUQUESNE | 13F | OK | OK | 95 |
| SOROS | 13F | OK | OK | 266 |
| THIRDPOINT | 13F | OK | OK | 43 |
| ELLIOTT | 13F | OK | OK | 29 |
| TIGERGLOBAL | 13F | OK | OK | 46 |
| COATUE | 13F | OK | OK | 66 |
| LONEPINE | 13F | OK | OK | 34 |
| BRIDGEWATER | 13F | OK | OK | 997 |
| RENTECH | 13F | OK | OK | 3140 |

22 of 22, clean.

## 6. Verbatim final lines

`pytest`:

```
$ PYTHONPATH="backend;." .venv/Scripts/python.exe -m pytest tests -q
........................................................................ [ 52%]
........................................................................ [ 54%]
...  (thirteen more full dot rows) ...
........................................................................ [ 98%]
......................................                                   [100%]
2629 passed, 1 skipped in 213.84s (0:03:33)
```

`ruff`:

```
$ .venv/Scripts/python.exe -m ruff check backend tests
All checks passed!
```

Both fully green — no failures, no errors. An earlier run of the same full suite, taken as this
pass's true starting baseline before `edgar.py` was touched, showed 3 failures
(`test_paperdesk.py::TestThreeBooks::test_a_contribution_funded_book_opens_with_its_first_contribution_not_its_seed`,
`test_purposes.py::TestPurposeSpecs::test_trading_matches_the_owners_correction_not_the_plan_document`,
`test_purposes.py::TestPurposeSpecs::test_roth_matches_the_plan`, "2601 passed, 3 failed, 1 skipped").
`git status` at that time showed `backend/app/paperdesk/desk.py`, `backend/app/tournament/purposes.py`
and `backend/app/tournament/results.py` modified by concurrent work in this same checkout, entirely
outside this pass's scope fence (`backend/app/institutions/`, `backend/app/api/institutions.py`,
`tests/test_institutions_*.py`) — those three failures were never touched or investigated here, and
had cleared on their own (the concurrent work finished) by the time of the final run above. Every
`test_institutions_*` test passed in both runs (146 of 146, see below), unaffected either way.

```
$ PYTHONPATH="backend;." .venv/Scripts/python.exe -m pytest tests/test_institutions_edgar.py tests/test_institutions_api.py tests/test_institutions_deltas.py tests/test_institutions_parse.py tests/test_institutions_holders.py -q
........................................................................ [ 49%]
........................................................................ [ 98%]
..                                                                       [100%]
146 passed in 5.52s
```

## 7. Anything still broken

Nothing reproducible. To be precise about what that claim does and does not cover:

- **All 22 funds, live, both layers, both before and after the fix: clean.** No fund needs a
  workaround or a "known broken" flag in the catalog.
- **The one real failure observed (`VTI`, §3) was transient and is now retried automatically.**
  It cannot be guaranteed never to recur — SEC EDGAR's own latency is outside this application's
  control, and a `RateLimited`/`ProviderUnavailable` that outlasts the retry budget still surfaces
  as a 429/503, correctly, per `app.api.institutions._map_provider_error` (already tested,
  unchanged by this pass) — but a single momentary blip, the specific shape measured here, no
  longer fails the whole request.
- **The owner's original "Institutions tab is broken for Cathie Wood" report could not be
  reproduced against ARKINVEST specifically**, on this date, under either normal or adversarial
  (cold-cache, concurrent-request) live conditions. The most likely explanation this investigation
  can support is the general EDGAR-latency gap in §3/§4: any fund's tab, on a bad SEC response day,
  could have failed outright with no retry, and ARKINVEST — a large, diffuse 13F book fetched
  alongside a submissions listing — was simply the fund open at the time. That is inference, not a
  reproduced defect, and is reported as such rather than dressed up as a confirmed root cause.
