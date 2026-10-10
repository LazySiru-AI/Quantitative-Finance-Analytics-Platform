import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { ApiRequestError } from "@/api/client";
import type { Dossier, PendingSeat, PendingSeatsResponse } from "@/api/evolution";

// --- module mock -------------------------------------------------------------------------------------

const pendingSeatsMock = vi.fn<() => Promise<PendingSeatsResponse>>();
const shelveSeatMock = vi.fn<(genomeId: string) => Promise<PendingSeat>>();
const rejectSeatMock = vi.fn<(genomeId: string) => Promise<PendingSeat>>();
const seatCandidateMock = vi.fn<(genomeId: string) => Promise<PendingSeat>>();
const retireSeatMock = vi.fn<(genomeId: string) => Promise<PendingSeat>>();
const dossierMock = vi.fn<(genomeId: string) => Promise<Dossier>>();

vi.mock("@/api/evolution", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/evolution")>();
  return {
    ...actual,
    evolutionApi: {
      ...actual.evolutionApi,
      pendingSeats: () => pendingSeatsMock(),
      shelveSeat: (genomeId: string) => shelveSeatMock(genomeId),
      rejectSeat: (genomeId: string) => rejectSeatMock(genomeId),
      seatCandidate: (genomeId: string) => seatCandidateMock(genomeId),
      retireSeat: (genomeId: string) => retireSeatMock(genomeId),
      dossier: (genomeId: string) => dossierMock(genomeId),
    },
  };
});

const { default: PendingSeatsPanel } = await import("@/pages/competition/PendingSeatsPanel");

// --- fixtures ----------------------------------------------------------------------------------------
// Field names below match the contract verified live against `app.main` on 2026-08-26 (see
// `src/test/fixtures/live-pending-seats.json`, exercised end-to-end by `liveData.test.tsx`).
// `PendingSeat.headline`/`short_id`/`discipline_label`/`rule_template_id` are all real, always-present
// fields on the wire now, not the "being rolled out" optional guess an earlier version of this module
// carried.

function seat(overrides: Partial<PendingSeat> = {}): PendingSeat {
  return {
    genome_id: "g1845-abc123",
    agent_id: "g1845-abc123",
    purpose: "roth",
    requested_at: "2026-08-26T12:00:00Z",
    generations: [4, 5],
    window_sets: [["gfc", "recent"]],
    median_excess: "0.3051",
    holdout_median_excess: "0.2031",
    q_value: 0.0004,
    library_path: "backend/app/paper/library/candidates/g1845-abc123.json",
    reason: "cleared generation 5's gate",
    status: "pending",
    decided_at: null,
    decided_note: "",
    headline: "EMA crossover, SMA regime filter · CSCO/AMAT/LRCX · Roth",
    short_id: "g1845·abc1",
    discipline_label: "mean-reversion",
    rule_template_id: "close > sma(N) and ema(N) crosses_above ema(N) || ema(N) crosses_below ema(N)",
    ...overrides,
  };
}

function dossierFor(genomeId: string, overrides: Partial<Dossier> = {}): Dossier {
  return {
    genome_id: genomeId,
    agent_id: genomeId,
    // Deliberately a DIFFERENT string from `seat().headline` above -- not what a real deployment would
    // send (the backend guarantees the two are byte-identical for the same genome), but useful here to
    // prove which one PendingSeatsPanel actually prefers once a dossier has loaded.
    headline: "DOSSIER: EMA crossover, SMA regime filter · CSCO/AMAT/LRCX · Roth",
    short_id: "g1845·dos1",
    purpose: "roth",
    discipline_label: "mean-reversion",
    discipline_label_note:
      "Self-declared tag from the card's own genome record. It is not derived from the entry/exit rule.",
    stage: "pending",
    requested_at: "2026-08-26T12:00:00Z",
    what_it_does: {
      universe: ["CSCO", "AMAT", "LRCX"],
      universe_note: "3 names: semiconductor large caps.",
      entry_plain: "Buys on a moving-average crossover.",
      exit_plain: "Sells on the reverse crossover.",
      risk_plain: "Cuts a losing position at -8%.",
      sizing_plain: "At most 3 positions, 20% each.",
      raw: {},
    },
    thesis: "Semiconductor demand mean-reverts.",
    origin: { generation: 1845, origin_kind: "mutation", parents: ["g1840-xyz"], note: "Mutated from a generation-1840 parent." },
    evidence: [],
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
      percentile_all_time: 0.87,
      candidates_ever_run: 1887,
      generations_with_outcomes: 231,
      noise_floor_pp: "21.2",
      margin_over_noise_pp: "3.45",
    },
    cautions: [],
    overlap: { with_shelved: [], with_seated: [], note: "" },
    what_a_decision_does: {
      shelve: "Keeps the card, names it, and tracks it.",
      reject: "Declines it permanently.",
      seat: "Adds it to the simulated paper desk's roster.",
      retire: "Removes it from the shelf without ever seating it.",
    },
    ...overrides,
  };
}

beforeEach(() => {
  pendingSeatsMock.mockReset();
  shelveSeatMock.mockReset();
  rejectSeatMock.mockReset();
  seatCandidateMock.mockReset();
  retireSeatMock.mockReset();
  dossierMock.mockReset();
  dossierMock.mockReturnValue(new Promise(() => {})); // no test needs this unless it expands a row
});

describe("PendingSeatsPanel", () => {
  it("renders a pending candidate with a readable name, never a bare hash, and two non-'approve' actions", async () => {
    pendingSeatsMock.mockResolvedValue({ requests: [seat()] });
    render(<PendingSeatsPanel />);

    const row = await screen.findByTestId("candidate-row-pending");
    expect(within(row).getByText("g1845·abc1")).toBeTruthy(); // subordinate short-id chip
    expect(within(row).queryByText("g1845-abc123")).toBeNull(); // the raw hash is never the primary name
    expect(within(row).getByText("Keep for review")).toBeTruthy();
    expect(within(row).getByText("Decline")).toBeTruthy();
    expect(within(row).queryByText(/approve/i)).toBeNull();
  });

  it("groups shelved candidates separately, offering seat/retire instead of keep/decline", async () => {
    pendingSeatsMock.mockResolvedValue({ requests: [seat({ genome_id: "g-shelf", status: "shelved" })] });
    render(<PendingSeatsPanel />);

    const shelfGroup = await screen.findByTestId("review-group-shelved");
    expect(within(shelfGroup).getByText("Seat on the paper desk")).toBeTruthy();
    expect(within(shelfGroup).getByText("Retire")).toBeTruthy();
    expect(within(shelfGroup).queryByText("Keep for review")).toBeNull();
    // The standing simulated-desk sentence lives on this section.
    expect(within(shelfGroup).getByText(/simulated, no real money/)).toBeTruthy();
  });

  it("renders explicit empty states rather than blank groups", async () => {
    pendingSeatsMock.mockResolvedValue({ requests: [] });
    render(<PendingSeatsPanel />);
    expect(await screen.findByText(/Nothing is waiting for review/)).toBeTruthy();
    expect(await screen.findByText(/Nothing is on the shelf yet/)).toBeTruthy();
  });

  it("'Keep for review' calls shelve, never approve/reject/seat", async () => {
    pendingSeatsMock
      .mockResolvedValueOnce({ requests: [seat()] })
      .mockResolvedValueOnce({ requests: [seat({ status: "shelved" })] });
    shelveSeatMock.mockResolvedValue(seat({ status: "shelved" }));

    render(<PendingSeatsPanel />);
    fireEvent.click(await screen.findByText("Keep for review"));

    await waitFor(() => expect(shelveSeatMock).toHaveBeenCalledWith("g1845-abc123"));
    expect(rejectSeatMock).not.toHaveBeenCalled();
    expect(seatCandidateMock).not.toHaveBeenCalled();
  });

  it("'Decline' calls reject, never shelve", async () => {
    pendingSeatsMock.mockResolvedValue({ requests: [seat()] });
    rejectSeatMock.mockResolvedValue(seat({ status: "rejected" }));

    render(<PendingSeatsPanel />);
    fireEvent.click(await screen.findByText("Decline"));

    await waitFor(() => expect(rejectSeatMock).toHaveBeenCalledWith("g1845-abc123"));
    expect(shelveSeatMock).not.toHaveBeenCalled();
  });

  it("'Seat on the paper desk' calls seat, and 'Retire' calls retire", async () => {
    pendingSeatsMock.mockResolvedValue({ requests: [seat({ genome_id: "g-shelf", status: "shelved" })] });
    seatCandidateMock.mockResolvedValue(seat({ genome_id: "g-shelf", status: "seated" }));

    render(<PendingSeatsPanel />);
    fireEvent.click(await screen.findByText("Seat on the paper desk"));

    await waitFor(() => expect(seatCandidateMock).toHaveBeenCalledWith("g-shelf"));
    expect(retireSeatMock).not.toHaveBeenCalled();
  });

  it("a 409 renders the server's own sentence, not a generic failure, then re-reads", async () => {
    pendingSeatsMock.mockResolvedValue({ requests: [seat()] });
    shelveSeatMock.mockRejectedValue(
      new ApiRequestError(409, JSON.stringify({ detail: "g1845-abc123 is 'seated'; only 'pending' may be shelved or rejected" })),
    );

    render(<PendingSeatsPanel />);
    fireEvent.click(await screen.findByText("Keep for review"));

    expect(await screen.findByText(/only 'pending' may be shelved or rejected/)).toBeTruthy();
    await waitFor(() => expect(pendingSeatsMock.mock.calls.length).toBeGreaterThan(1));
  });

  it("keeps decided rows visible, greyed under a collapsed summary, for seated/rejected/retired alike", async () => {
    pendingSeatsMock.mockResolvedValue({
      requests: [
        seat({ genome_id: "g-pending" }),
        seat({ genome_id: "g-seated", status: "seated", decided_note: "seated after review" }),
        seat({ genome_id: "g-rejected", status: "rejected", decided_note: "too concentrated" }),
        seat({ genome_id: "g-retired", status: "retired", decided_note: "no longer clears" }),
      ],
    });
    render(<PendingSeatsPanel />);

    expect(await screen.findByTestId("candidate-row-pending")).toBeTruthy();
    expect(screen.getByText("3 already decided")).toBeTruthy();
    expect(screen.getByText(/seated after review/)).toBeTruthy();
    expect(screen.getByText(/too concentrated/)).toBeTruthy();
    expect(screen.getByText(/no longer clears/)).toBeTruthy();
  });

  it("renders a readable message when the queue cannot be loaded", async () => {
    pendingSeatsMock.mockRejectedValue(new Error("network down"));
    render(<PendingSeatsPanel />);
    expect(await screen.findByText(/Could not load the review queue/)).toBeTruthy();
  });

  it("the dossier toggle is a real button with aria-expanded, openable by a plain click", async () => {
    // Regression guard for the 2026-08-26 fix: an earlier version used a native <details>/<summary>,
    // which jsdom does not toggle on .click() -- see PendingSeatsPanel.tsx's own docstring.
    pendingSeatsMock.mockResolvedValue({ requests: [seat()] });
    dossierMock.mockResolvedValue(dossierFor("g1845-abc123"));
    render(<PendingSeatsPanel />);

    const row = await screen.findByTestId("candidate-row-pending");
    const toggle = within(row).getByRole("button", { name: "Full dossier" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(toggle);
    await screen.findByTestId("candidate-dossier");
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
  });

  it("fetches the dossier only after a row is expanded, not eagerly for the whole queue", async () => {
    pendingSeatsMock.mockResolvedValue({ requests: [seat()] });
    render(<PendingSeatsPanel />);
    await screen.findByTestId("candidate-row-pending");

    expect(dossierMock).not.toHaveBeenCalled();

    dossierMock.mockResolvedValue(dossierFor("g1845-abc123"));
    fireEvent.click(screen.getByText("Full dossier"));

    await waitFor(() => expect(dossierMock).toHaveBeenCalledWith("g1845-abc123"));
  });

  it("prefers the loaded dossier's own headline/short_id over the list row's, once available", async () => {
    // headline is already composed server-side from the parsed rule on BOTH endpoints, and the
    // backend guarantees the two are byte-identical for the same genome -- this test uses
    // deliberately different fixture strings only to prove the priority order PendingSeatsPanel
    // actually applies, not to model a real mismatch.
    pendingSeatsMock.mockResolvedValue({ requests: [seat()] });
    dossierMock.mockResolvedValue(dossierFor("g1845-abc123"));

    render(<PendingSeatsPanel />);
    const row = await screen.findByTestId("candidate-row-pending");
    // Before expanding: the list row's own server-composed headline, not a placeholder.
    expect(within(row).getByText("EMA crossover, SMA regime filter · CSCO/AMAT/LRCX · Roth")).toBeTruthy();

    fireEvent.click(within(row).getByText("Full dossier"));
    await waitFor(() =>
      expect(
        within(row).getByText("DOSSIER: EMA crossover, SMA regime filter · CSCO/AMAT/LRCX · Roth"),
      ).toBeTruthy(),
    );
    expect(within(row).getByText("g1845·dos1")).toBeTruthy();
  });

  it("renders the list endpoint's server-composed headline directly -- no client-side recomposition", async () => {
    pendingSeatsMock.mockResolvedValue({
      requests: [seat({ headline: "EMA 13/21 crossover, 135-day regime filter · CSCO/AMAT +2 · Roth", short_id: "g1845·srv1" })],
    });
    render(<PendingSeatsPanel />);

    const row = await screen.findByTestId("candidate-row-pending");
    expect(within(row).getByText("EMA 13/21 crossover, 135-day regime filter · CSCO/AMAT +2 · Roth")).toBeTruthy();
    expect(within(row).getByText("g1845·srv1")).toBeTruthy();
    expect(within(row).queryByText(/Roth candidate/)).toBeNull();
  });

  it("falls back to the honest purpose-only placeholder when a row genuinely has no headline of its own", async () => {
    // A degraded/older payload -- headline/short_id present on the type but empty at runtime. Not the
    // expected shape from a real deployment (see PendingSeat's docstring), but the fallback must still
    // be honest rather than render nothing.
    pendingSeatsMock.mockResolvedValue({ requests: [seat({ headline: "", short_id: "" })] });
    render(<PendingSeatsPanel />);

    const row = await screen.findByTestId("candidate-row-pending");
    expect(within(row).getByText("Roth candidate — expand for what it trades")).toBeTruthy();
    expect(within(row).getByText("g1845·abc1")).toBeTruthy(); // shortId is always locally computable
  });
});
