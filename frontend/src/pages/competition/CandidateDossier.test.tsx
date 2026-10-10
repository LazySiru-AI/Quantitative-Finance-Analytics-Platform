import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import type { Dossier } from "@/api/evolution";

// --- module mock -------------------------------------------------------------------------------------

const dossierMock = vi.fn<(genomeId: string) => Promise<Dossier>>();

vi.mock("@/api/evolution", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/evolution")>();
  return {
    ...actual,
    evolutionApi: {
      ...actual.evolutionApi,
      dossier: (genomeId: string) => dossierMock(genomeId),
    },
  };
});

const { default: CandidateDossier } = await import("@/pages/competition/CandidateDossier");

// --- fixtures ----------------------------------------------------------------------------------------
// Field names below match the contract verified live against `app.main` on 2026-08-26 (see
// `src/test/fixtures/live-dossiers.json`, exercised end-to-end by `liveData.test.tsx`) -- there is no
// `rule_summary`/`template_id` on the wire, and `discipline` is `discipline_label` +
// `discipline_label_note`.

function makeDossier(overrides: Partial<Dossier> = {}): Dossier {
  return {
    genome_id: "g1859-fd7c2c196f35",
    agent_id: "g1859-fd7c2c196f35",
    headline: "EMA 13/21 crossover, 135-day regime filter · CSCO/AMAT/LRCX +3 · Roth",
    short_id: "g1859·fd7c",
    purpose: "roth",
    // A self-declared label -- deliberately NOT what CandidateDossier renders as the description.
    // See candidateName.ts's module docstring: g1815-d05786e4c611 -> g1823-e2a3d5060b09 changed only
    // this field (and display_name) across an otherwise byte-identical rule.
    discipline_label: "mean-reversion",
    discipline_label_note:
      "Self-declared tag from the card's own genome record. It is not derived from the entry/exit rule and is known to disagree with it on real cards.",
    stage: "pending",
    requested_at: "2026-08-26T15:42:17.852832Z",
    what_it_does: {
      universe: ["CSCO", "AMAT", "LRCX", "KLAC", "INTU", "IGV"],
      universe_note: "6 names: 5 US semiconductor/software large caps and 1 sector ETF.",
      entry_plain:
        "Buys when the price is above its 135-day average (a rising-market filter) and the 13-day average crosses above the 21-day average.",
      exit_plain: "Sells when the 13-day average crosses back below the 21-day average.",
      risk_plain:
        "Cuts a losing position at -8%. No profit target. Force-closes any position still open after 93 trading days.",
      sizing_plain: "At most 3 positions at once, 20% of the book each -- so at most 60% invested, the rest in cash.",
      raw: { entry: "...", exit: "...", stop_loss_pct: "0.08" },
    },
    thesis: "Semiconductor demand mean-reverts faster than the broad index during capex cycles.",
    origin: {
      generation: 1859,
      origin_kind: "crossover",
      parents: ["g1855-2ff5b8e319dd", "g1855-abc123"],
      note: "Crossed two generation-1855 cards; inherits its universe from the first parent.",
    },
    evidence: [
      {
        generation: 1855,
        round_id: "r16-auto-x",
        rank: 3,
        field_size: 10,
        windows: ["bear-2022", "chop-2015"],
        median_excess: "0.18",
        worst_excess: "-0.09",
        hit_rate: 0.55,
        total_trades: 40,
        holdout_median_excess: "0.11",
        holdout_windows: ["covid"],
        q_value: 0.03,
      },
      {
        generation: 1859,
        round_id: "r17-auto-y",
        rank: 1,
        field_size: 10,
        windows: ["bear-2022", "chop-2015", "bull-2024", "recent", "gfc"],
        median_excess: "0.2465",
        worst_excess: "-0.1093",
        hit_rate: 0.6,
        total_trades: 51,
        holdout_median_excess: "0.1488",
        holdout_windows: ["covid", "q4-2018"],
        q_value: 0.010976,
      },
    ],
    context: {
      field_median_excess_this_generation: "0.18",
      field_median_excess_same_purpose: "0.0224",
      field_median_excess_all_purposes: "0.0565",
      field_holdout_median_same_purpose: "0.1288",
      field_holdout_median_all_purposes: "0.1502",
      field_holdout_positive_fraction_same_purpose: 0.9005,
      field_holdout_positive_fraction_all_purposes: 0.9433,
      holdout_measurements_same_purpose: 1196,
      holdout_measurements_all_purposes: 2364,
      percentile_all_time: 0.9975,
      candidates_ever_run: 1887,
      generations_with_outcomes: 231,
      noise_floor_pp: "21.2",
      margin_over_noise_pp: "3.45",
    },
    cautions: [
      { code: "narrow-universe", severity: "note", text: "Fewer than 5 tickers." },
      {
        code: "holdout-does-not-discriminate",
        severity: "serious",
        text: "94.3% of the 2364 holdout measurements this search has recorded, across every purpose, also came back positive. This card's +14.88% is above its own purpose's field holdout median (+12.88%), so a positive holdout here is not evidence that this card is better than a coin flip from the same generator.",
      },
      {
        code: "single-window-set",
        severity: "blocking",
        text: "Fewer than 2 distinct window sets were actually run.",
      },
      // The two codes added alongside PendingSeat.rule_template_id and Dossier.discipline_label(_note)
      // once discipline was shown not to describe the rule (2026-08-26) -- see candidateName.ts's
      // module docstring for the case.
      {
        code: "label-does-not-match-rule",
        severity: "serious",
        text: "This card's self-declared discipline (\"mean-reversion\") does not match its own rule template.",
      },
      {
        code: "template-is-not-distinct",
        severity: "serious",
        text: "24 other candidates in this queue share this exact entry/exit template.",
      },
    ],
    overlap: {
      with_shelved: [
        { genome_id: "g1850-aaa111", headline: "Trend · AMAT/LRCX · Roth", shared_tickers: ["AMAT", "LRCX"], jaccard: 0.33 },
      ],
      with_seated: [],
      note: "One shelved card already trades AMAT and LRCX; shelving this one concentrates the shelf further into semiconductors.",
    },
    what_a_decision_does: {
      shelve: "Keeps the card, names it, and tracks it. It places no orders and does not join the desk.",
      reject: "Declines it permanently. The loop will not re-file this genome even if it clears the gate again.",
      seat: "Adds it to the simulated paper desk's roster. The desk holds no real money and approving places no order.",
      retire: "Removes it from the shelf without ever seating it. Also permanent.",
    },
    ...overrides,
  };
}

beforeEach(() => {
  dossierMock.mockReset();
});

describe("CandidateDossier", () => {
  it("shows a loading state before the dossier resolves", () => {
    dossierMock.mockReturnValue(new Promise(() => {})); // never resolves
    render(<CandidateDossier genomeId="g1859-fd7c2c196f35" />);
    expect(screen.getByTestId("dossier-loading")).toBeTruthy();
  });

  it("fetches by the genome id it was given", async () => {
    dossierMock.mockResolvedValue(makeDossier());
    render(<CandidateDossier genomeId="g1859-fd7c2c196f35" />);
    await screen.findByTestId("candidate-dossier");
    expect(dossierMock).toHaveBeenCalledWith("g1859-fd7c2c196f35");
  });

  it("renders 'What it does' -- the plain-English trading rules -- before any number on the page", async () => {
    dossierMock.mockResolvedValue(makeDossier());
    render(<CandidateDossier genomeId="g1859-fd7c2c196f35" />);
    const root = await screen.findByTestId("candidate-dossier");

    expect(screen.getByText(/Buys when the price is above its 135-day average/)).toBeTruthy();
    expect(screen.getByText(/Sells when the 13-day average crosses back below/)).toBeTruthy();
    expect(screen.getByText(/Cuts a losing position at -8%/)).toBeTruthy();
    expect(screen.getByText(/At most 3 positions at once/)).toBeTruthy();

    const text = root.textContent ?? "";
    const doesIndex = text.indexOf("What it does");
    const evidenceIndex = text.indexOf("The evidence");
    expect(doesIndex).toBeGreaterThanOrEqual(0);
    expect(evidenceIndex).toBeGreaterThan(doesIndex);
  });

  it("renders discipline_label only as an explicitly-marked self-declared label, with the backend's own caveat", async () => {
    dossierMock.mockResolvedValue(makeDossier());
    render(<CandidateDossier genomeId="g1859-fd7c2c196f35" />);
    const label = await screen.findByTestId("discipline-label");
    expect(label.textContent).toContain("mean-reversion");
    expect(label.textContent).toMatch(/self-declared/i);
    expect(label.textContent).toMatch(/not derived from the entry\/exit rule/i);
  });

  it("labels every field comparison with which population it is scoped to (same purpose vs all purposes)", async () => {
    dossierMock.mockResolvedValue(makeDossier());
    render(<CandidateDossier genomeId="g1859-fd7c2c196f35" />);
    const root = await screen.findByTestId("candidate-dossier");
    const text = root.textContent ?? "";

    expect(text).toMatch(/same purpose/i);
    expect(text).toMatch(/all purposes/i);
    // The real figures for this fixture -- both populations' medians must actually appear, not just
    // the words "same purpose"/"all purposes" floating free of a number.
    expect(text).toContain("+12.88%"); // field_holdout_median_same_purpose
    expect(text).toContain("+15.02%"); // field_holdout_median_all_purposes
  });

  it("states the all-purposes baseline before the same-purpose figures, and the card's own figure last, in the holdout callout", async () => {
    dossierMock.mockResolvedValue(makeDossier());
    render(<CandidateDossier genomeId="g1859-fd7c2c196f35" />);
    const check = await screen.findByTestId("holdout-reality-check");
    const text = check.textContent ?? "";

    const allPurposesIndex = text.indexOf("94.3%"); // field_holdout_positive_fraction_all_purposes
    const samePurposeIndex = text.indexOf("+12.88%"); // field_holdout_median_same_purpose
    const cardIndex = text.indexOf("+14.88%"); // this card's own latest holdout_median_excess
    expect(allPurposesIndex).toBeGreaterThanOrEqual(0);
    expect(samePurposeIndex).toBeGreaterThan(allPurposesIndex);
    expect(cardIndex).toBeGreaterThan(samePurposeIndex);
  });

  it("never asserts a direction (above/below) of its own composing in the holdout callout", async () => {
    // This card sits ABOVE its own purpose's field median (+14.88% vs +12.88%) -- the callout must not
    // claim the opposite, or claim any direction at all; that judgement belongs to cautions[].text,
    // copied verbatim, not recomposed. Regression guard for the 2026-08-26 correction where the first
    // version of this text hard-coded "is not evidence... inside the field's ordinary range", which
    // would have been backwards for this exact fixture.
    dossierMock.mockResolvedValue(makeDossier());
    render(<CandidateDossier genomeId="g1859-fd7c2c196f35" />);
    const check = await screen.findByTestId("holdout-reality-check");
    expect(check.textContent).not.toMatch(/inside the field's ordinary range/i);
    // "below" alone is not banned -- "see ... below" is an ordinary page reference, not a directional
    // claim about the card's figure. What must never appear is this component asserting the card sits
    // above/below the field itself.
    expect(check.textContent).not.toMatch(/\b(is|sits?|comes?\s+in)\s+(above|below)\b/i);
  });

  it("never prints a bare 0.00% for a null figure -- null is not zero", async () => {
    dossierMock.mockResolvedValue(
      makeDossier({
        evidence: [
          {
            generation: 1859,
            round_id: "r17",
            rank: 1,
            field_size: 5,
            windows: ["recent"],
            median_excess: null,
            worst_excess: null,
            hit_rate: null,
            total_trades: 0,
            holdout_median_excess: null,
            holdout_windows: [],
            q_value: null,
          },
        ],
      }),
    );
    render(<CandidateDossier genomeId="g1859-fd7c2c196f35" />);
    await screen.findByTestId("candidate-dossier");
    expect(screen.queryByText("0.00%")).toBeNull();
    expect(screen.getAllByText(/—/).length).toBeGreaterThan(0);
  });

  it("formats noise_floor_pp/margin_over_noise_pp (DecimalStrings, already in pp) with the pp suffix", async () => {
    dossierMock.mockResolvedValue(makeDossier());
    render(<CandidateDossier genomeId="g1859-fd7c2c196f35" />);
    await screen.findByTestId("candidate-dossier");
    expect(screen.getByText("+21.20pp")).toBeTruthy();
    expect(screen.getByText("+3.45pp")).toBeTruthy();
  });

  it("sorts cautions blocking, then serious, then note, regardless of input order", async () => {
    dossierMock.mockResolvedValue(makeDossier());
    render(<CandidateDossier genomeId="g1859-fd7c2c196f35" />);
    const list = await screen.findByTestId("dossier-cautions");
    const items = Array.from(list.querySelectorAll("li")).map((li) => li.getAttribute("data-testid"));
    expect(items).toEqual([
      "caution-single-window-set",
      "caution-holdout-does-not-discriminate",
      "caution-label-does-not-match-rule",
      "caution-template-is-not-distinct",
      "caution-narrow-universe",
    ]);
  });

  it("renders the two new discipline/template caution codes with no special-casing needed beyond severity", async () => {
    dossierMock.mockResolvedValue(makeDossier());
    render(<CandidateDossier genomeId="g1859-fd7c2c196f35" />);
    await screen.findByTestId("candidate-dossier");

    const labelCaution = screen.getByTestId("caution-label-does-not-match-rule");
    const templateCaution = screen.getByTestId("caution-template-is-not-distinct");
    expect(labelCaution.textContent).toMatch(/does not match its own rule template/);
    expect(templateCaution.textContent).toMatch(/share this exact entry\/exit template/);
    // Both are severity "serious" per the coordinator's spec -- same treatment as any other serious
    // caution, no bespoke styling of their own.
    expect(labelCaution.className).toContain("comp-review-caution-serious");
    expect(templateCaution.className).toContain("comp-review-caution-serious");
  });

  it("visually distinguishes a blocking caution from a serious one", async () => {
    dossierMock.mockResolvedValue(makeDossier());
    render(<CandidateDossier genomeId="g1859-fd7c2c196f35" />);
    await screen.findByTestId("candidate-dossier");
    const blocking = screen.getByTestId("caution-single-window-set");
    const serious = screen.getByTestId("caution-holdout-does-not-discriminate");
    expect(blocking.className).toContain("comp-review-caution-blocking");
    expect(serious.className).toContain("comp-review-caution-serious");
    expect(blocking.className).not.toBe(serious.className);
  });

  it("never hides the cautions section, even when there are none", async () => {
    dossierMock.mockResolvedValue(makeDossier({ cautions: [] }));
    render(<CandidateDossier genomeId="g1859-fd7c2c196f35" />);
    const section = await screen.findByTestId("dossier-cautions");
    expect(section.textContent).toMatch(/No deterministic caution rule fired/);
  });

  it("renders what each of the four decisions does, next to no button of its own -- not a tooltip", async () => {
    dossierMock.mockResolvedValue(makeDossier());
    render(<CandidateDossier genomeId="g1859-fd7c2c196f35" />);
    await screen.findByTestId("candidate-dossier");
    expect(screen.getByText(/Keeps the card, names it, and tracks it/)).toBeTruthy();
    expect(screen.getByText(/Declines it permanently/)).toBeTruthy();
    expect(screen.getByText(/Adds it to the simulated paper desk's roster/)).toBeTruthy();
    expect(screen.getByText(/Removes it from the shelf without ever seating it/)).toBeTruthy();
  });

  it("calls onLoaded once with the fetched dossier", async () => {
    const dossier = makeDossier();
    dossierMock.mockResolvedValue(dossier);
    const onLoaded = vi.fn();
    render(<CandidateDossier genomeId="g1859-fd7c2c196f35" onLoaded={onLoaded} />);
    await waitFor(() => expect(onLoaded).toHaveBeenCalledTimes(1));
    expect(onLoaded).toHaveBeenCalledWith(dossier);
  });

  it("renders a readable error rather than a blank body when the fetch fails", async () => {
    dossierMock.mockRejectedValue(new Error("not found"));
    render(<CandidateDossier genomeId="g-missing" />);
    expect(await screen.findByTestId("dossier-error")).toBeTruthy();
    expect(screen.getByText(/Could not load the dossier/)).toBeTruthy();
  });
});
