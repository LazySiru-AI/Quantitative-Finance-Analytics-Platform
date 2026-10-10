/**
 * The review queue and dossier, rendered against **captured production payloads** rather than
 * hand-written fixtures.
 *
 * **Why this file exists separately from `PendingSeatsPanel.test.tsx`.** That suite builds the
 * fixtures it asserts against, so it can only prove the component is consistent with what its author
 * expected the server to send. This repository has already been bitten by exactly that gap once: a
 * service-layer check reported a fund healthy, and the page died rendering one real value, taking
 * three other funds down with it. A green component suite is not a rendered page.
 *
 * The two fixtures under `src/test/fixtures/` are verbatim responses from the real
 * `app.main` application, captured over `TestClient` against the live `data/loop/` tree on
 * 2026-08-26: all 25 seat requests as `GET /api/competition/loop/pending-seats` actually returns
 * them, and three dossiers chosen for their awkwardness rather than their tidiness --
 *
 *   - `g1859-fd7c2c196f35` -- a `pending` row, the one the old UI pitched as "median excess 24.65".
 *   - `g1823-e2a3d5060b09` -- `shelved`, and the card whose rule is byte-identical to
 *     `g1815-d05786e4c611` under a different `discipline`, so it carries the extra
 *     `label-does-not-match-rule` caution.
 *   - `g009-30c484221799` -- the oldest promotion, from generation 9, with a lineage and window
 *     history unlike anything the later ones have.
 *
 * These payloads carry things a hand-written fixture reliably omits: `Decimal`-serialised strings
 * with 28 significant figures, real em-dashes and U+2212 minus signs in the plain-English rule text,
 * `null` holdout figures, and a 17-entry overlap list. If the components cannot render those, the
 * page is broken no matter how green the other suite is.
 *
 * Re-capture with the snippet in `docs/research/loop/` if the response shape changes on purpose; a
 * failure here after a deliberate contract change means the fixture is stale, not that the UI broke.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import liveDossiers from "@/test/fixtures/live-dossiers.json";
import livePendingSeats from "@/test/fixtures/live-pending-seats.json";

vi.mock("@/api/evolution", async () => {
  const actual = await vi.importActual<typeof import("@/api/evolution")>("@/api/evolution");
  return {
    ...actual,
    evolutionApi: {
      ...actual.evolutionApi,
      pendingSeats: vi.fn(),
      dossier: vi.fn(),
      shelveSeat: vi.fn(),
      rejectSeat: vi.fn(),
      seatCandidate: vi.fn(),
      retireSeat: vi.fn(),
    },
  };
});

import { evolutionApi } from "@/api/evolution";
import PendingSeatsPanel from "./PendingSeatsPanel";

type Dossiers = Record<string, unknown>;
const dossiers = liveDossiers as Dossiers;

beforeEach(() => {
  vi.mocked(evolutionApi.pendingSeats).mockResolvedValue(
    livePendingSeats as Awaited<ReturnType<typeof evolutionApi.pendingSeats>>,
  );
  vi.mocked(evolutionApi.dossier).mockImplementation(async (genomeId: string) => {
    const found = dossiers[genomeId];
    if (!found) throw new Error(`no captured dossier for ${genomeId}`);
    return found as Awaited<ReturnType<typeof evolutionApi.dossier>>;
  });
});

describe("the review queue against real captured payloads", () => {
  it("renders every real seat request without throwing", async () => {
    render(<PendingSeatsPanel />);
    await waitFor(() => expect(vi.mocked(evolutionApi.pendingSeats)).toHaveBeenCalled());
    const pending = await screen.findByTestId("review-group-pending");
    const shelved = await screen.findByTestId("review-group-shelved");
    // The migration left the live queue at 3 pending + 22 shelved.
    expect(within(pending).getAllByTestId(/^candidate-row-/)).toHaveLength(3);
    expect(within(shelved).getAllByTestId(/^candidate-row-/)).toHaveLength(22);
  });

  it("leads every row with a rule-derived name, before any dossier is fetched", async () => {
    render(<PendingSeatsPanel />);
    const names = await screen.findAllByText(/crossover/i);
    expect(names.length).toBeGreaterThan(20);
    // The readable name comes from the list endpoint itself -- that was the point of enriching it.
    expect(vi.mocked(evolutionApi.dossier)).not.toHaveBeenCalled();
    // ...and no row is named by its hash.
    expect(screen.queryByText(/^g\d+-[0-9a-f]{12}$/)).toBeNull();
  });

  it("renders a real dossier's field comparisons rather than em dashes", async () => {
    render(<PendingSeatsPanel />);
    const pending = await screen.findByTestId("review-group-pending");
    const rows = within(pending).getAllByTestId(/^candidate-row-/);
    const row = rows[0];
    expect(row, "the pending group must render at least one row").toBeTruthy();
    const toggle = row!.querySelector("summary, button[aria-expanded]");
    expect(toggle, "a queue row must be expandable into its dossier").not.toBeNull();
    (toggle as HTMLElement).click();

    const dossier = await screen.findByTestId("candidate-dossier");

    // THE CHECK THAT MATTERS. Every headline figure is supposed to be rendered beside the field's
    // own figure for the same statistic -- that pairing is the whole redesign. If the component
    // reads a `context` key the server does not send, `formatSignedPctFraction(undefined)` renders
    // an em dash and the comparison silently disappears while every unit test stays green. This is
    // exactly how the frontend and backend drifted apart once already on this feature: the client
    // was built in parallel against guessed names (`field_median_excess_all_time`) while the server
    // shipped `field_median_excess_same_purpose`/`_all_purposes`.
    const text = dossier.textContent ?? "";
    const emDashes = (text.match(/—/g) ?? []).length;
    const percentages = (text.match(/[+−-]?\d+\.\d+%/g) ?? []).length;
    expect(percentages, `dossier rendered ${percentages} figures: ${text.slice(0, 400)}`).toBeGreaterThan(4);
    expect(
      emDashes,
      `dossier rendered ${emDashes} em dashes -- an unmeasured figure renders as one, so a cluster ` +
        `of them means the client is reading context keys the server does not send`,
    ).toBeLessThan(4);
  });

  it("shows the holdout reality check and the cautions, un-collapsed", async () => {
    render(<PendingSeatsPanel />);
    const pending = await screen.findByTestId("review-group-pending");
    const rows = within(pending).getAllByTestId(/^candidate-row-/);
    const row = rows[0];
    expect(row, "the pending group must render at least one row").toBeTruthy();
    (row!.querySelector("summary, button[aria-expanded]") as HTMLElement).click();

    await screen.findByTestId("candidate-dossier");
    expect(screen.getByTestId("holdout-reality-check")).toBeTruthy();
    const cautions = screen.getByTestId("dossier-cautions");
    expect(cautions.textContent).toMatch(/template/i);
    // The self-declared label must be marked as such wherever it appears.
    expect(screen.getByTestId("discipline-label").textContent).toMatch(/self-declared|not derived/i);
  });
});

describe("the captured payloads themselves", () => {
  it("carry the awkward real values a hand-written fixture would omit", () => {
    const d = dossiers["g1859-fd7c2c196f35"] as {
      what_it_does: { risk_plain: string; sizing_plain: string };
      context: Record<string, unknown>;
      cautions: { code: string; severity: string }[];
      overlap: { with_shelved: unknown[] };
    };
    // A real U+2212 minus and a real em-dash, not ASCII stand-ins.
    expect(d.what_it_does.risk_plain).toMatch(/−/);
    expect(d.what_it_does.sizing_plain).toMatch(/—/);
    // Decimal-serialised strings, not JS numbers -- these must never be parsed with parseFloat.
    const decimals = Object.entries(d.context).filter(([k]) => k.startsWith("field_"));
    expect(decimals.length).toBeGreaterThan(2);
    for (const [key, value] of decimals) {
      if (value === null) continue;
      expect(["string", "number"], `context.${key}`).toContain(typeof value);
    }
    // The caution that is the entire point of the redesign.
    expect(d.cautions.map((c) => c.code)).toContain("holdout-does-not-discriminate");
  });

  it("flag the relabelled twin card with label-does-not-match-rule", () => {
    const twin = dossiers["g1823-e2a3d5060b09"] as { cautions: { code: string }[] };
    expect(twin.cautions.map((c) => c.code)).toContain("label-does-not-match-rule");
  });

  it("flag every queued card as running a non-distinct rule template", () => {
    for (const [genomeId, raw] of Object.entries(dossiers)) {
      const d = raw as { cautions: { code: string }[] };
      expect(
        d.cautions.map((c) => c.code),
        `${genomeId} should carry template-is-not-distinct`,
      ).toContain("template-is-not-distinct");
    }
  });

  it("give every list row a headline and a short id", () => {
    const { requests } = livePendingSeats as {
      requests: { genome_id: string; headline: string | null; short_id: string | null }[];
    };
    expect(requests).toHaveLength(25);
    for (const row of requests) {
      expect(row.headline, `${row.genome_id} has no headline`).toBeTruthy();
      expect(row.short_id, `${row.genome_id} has no short_id`).toBeTruthy();
      // The hash must not be the readable name.
      expect(row.headline).not.toBe(row.genome_id);
    }
  });
});
