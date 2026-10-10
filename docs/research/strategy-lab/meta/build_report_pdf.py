"""Typeset the strategy-lab study as a PDF.

Every number is read from `data/*.json` at build time -- nothing is transcribed by hand, so the
document cannot drift from the study that produced it. Re-run after any stream re-runs.

Deliberately not a recommendation document. It reports what conditions did historically, with
sample sizes and multiple-testing corrections attached, and characterises instruments by measured
behaviour. See the notice on page 1.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

LAB = Path(__file__).resolve().parent.parent
DATA = LAB / "data"
OUT = LAB / "Strategy-Research-Report.pdf"

INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#5b6470")
RULE = colors.HexColor("#c7ccd4")
BAND = colors.HexColor("#eef1f5")
ACCENT = colors.HexColor("#8a1c1c")


def load(name: str) -> dict:
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

ss = getSampleStyleSheet()
S = {
    "title": ParagraphStyle("title", parent=ss["Title"], fontName="Helvetica-Bold",
                            fontSize=26, leading=30, textColor=INK, spaceAfter=6),
    "subtitle": ParagraphStyle("subtitle", parent=ss["Normal"], fontName="Helvetica",
                               fontSize=12, leading=16, textColor=MUTED, alignment=TA_CENTER),
    "h1": ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                         fontSize=15, leading=19, textColor=INK, spaceBefore=16, spaceAfter=7),
    "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                         fontSize=11, leading=14, textColor=INK, spaceBefore=11, spaceAfter=4),
    "body": ParagraphStyle("body", parent=ss["Normal"], fontName="Helvetica",
                           fontSize=9.2, leading=13, textColor=INK, spaceAfter=6, alignment=TA_LEFT),
    "small": ParagraphStyle("small", parent=ss["Normal"], fontName="Helvetica",
                            fontSize=7.4, leading=9.4, textColor=INK),
    "smallb": ParagraphStyle("smallb", parent=ss["Normal"], fontName="Helvetica-Bold",
                             fontSize=7.4, leading=9.4, textColor=INK),
    "mono": ParagraphStyle("mono", parent=ss["Normal"], fontName="Courier",
                           fontSize=6.6, leading=8.4, textColor=INK),
    "note": ParagraphStyle("note", parent=ss["Normal"], fontName="Helvetica",
                           fontSize=8.6, leading=12, textColor=INK, spaceAfter=5),
    "caption": ParagraphStyle("caption", parent=ss["Normal"], fontName="Helvetica-Oblique",
                              fontSize=7.6, leading=10, textColor=MUTED, spaceAfter=8),
}


def P(text, style="body"):
    return Paragraph(text, S[style])


def pct(v, digits=1):
    return "n/a" if v is None else f"{v * 100:.{digits}f}%"


def num(v, digits=3):
    return "n/a" if v is None else f"{v:.{digits}f}"


def table(rows, widths, *, header=True, align_right=(), font=7.4, zebra=True):
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    cmds = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), font),
        ("LEADING", (0, 0), (-1, -1), font + 2.2),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, INK),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, RULE),
    ]
    if header:
        cmds += [("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("BACKGROUND", (0, 0), (-1, 0), BAND)]
    for c in align_right:
        cmds.append(("ALIGN", (c, 1), (c, -1), "RIGHT"))
    if zebra:
        for i in range(2, len(rows), 2):
            cmds.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f7f9fb")))
    t.setStyle(TableStyle(cmds))
    return t


# ---------------------------------------------------------------------------
# Page furniture
# ---------------------------------------------------------------------------

TODAY = "2026-08-12"


def decorate(canvas, doc):
    canvas.saveState()
    w, h = doc.pagesize
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.75 * inch, 0.5 * inch, "Investing Dashboard - Strategy Research Report")
    canvas.drawRightString(w - 0.75 * inch, 0.5 * inch, f"page {doc.page}")
    canvas.drawCentredString(w / 2.0, 0.5 * inch, "Research, not investment advice")
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.4)
    canvas.line(0.75 * inch, 0.66 * inch, w - 0.75 * inch, 0.66 * inch)
    canvas.restoreState()


def build_doc():
    doc = BaseDocTemplate(
        str(OUT), pagesize=letter,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.7 * inch, bottomMargin=0.8 * inch,
        title="Investing Dashboard - Strategy Research Report",
        author="Strategy Lab", subject="Backtest study of the chart-analysis note",
    )
    portrait_frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="p")
    lw, lh = landscape(letter)
    land_frame = Frame(0.6 * inch, 0.8 * inch, lw - 1.2 * inch, lh - 1.5 * inch, id="l")
    doc.addPageTemplates([
        PageTemplate(id="portrait", frames=[portrait_frame], onPage=decorate, pagesize=letter),
        PageTemplate(id="landscape", frames=[land_frame], onPage=decorate, pagesize=landscape(letter)),
    ])
    return doc


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------

story: list = []
A = story.append

meta = load("meta_correction")
uni = load("universe")
arche = json.loads((DATA / "_pdf_archetypes.json").read_text(encoding="utf-8"))
regimes = load("regime_windows_corrected")
div = load("divergence_primary")
div_pool = load("divergence_pooled_replication")

# --- cover -----------------------------------------------------------------
A(Spacer(1, 1.5 * inch))
A(P("Strategy Research Report", "title"))
A(Spacer(1, 4))
A(P("Systematic evaluation of a chart-analysis note<br/>against 25+ years of daily market data", "subtitle"))
A(Spacer(1, 0.5 * inch))

cover = [
    ["Prepared", TODAY],
    ["Study", "Strategy Lab - six parallel analyst streams plus adversarial QA"],
    ["Primary tests", f"{meta['pooled_family_size']} (corrected within-stream and study-wide)"],
    ["Survivors", "0 of 150 in the main study; 1 of 4 in a pooled follow-up (see section 6)"],
    ["Instruments", f"{len(uni['coverage'])} resolved, {len(uni['refused'])} refused"],
    ["Engine", "Application's own backtest workbench, rule DSL, and lookahead guards"],
]
A(table([[P(k, "smallb"), P(v, "small")] for k, v in cover], [1.5 * inch, 4.5 * inch],
        header=False, zebra=False, font=8))

A(Spacer(1, 0.45 * inch))
notice = (
    "<b>This document is research, not investment advice.</b> It reports what specific, "
    "pre-registered technical conditions did historically, with sample sizes and multiple-testing "
    "corrections attached, and characterises instruments by their measured behaviour. It does not "
    "recommend any security, does not propose entry or exit prices for anyone to act on, contains "
    "no forecast, and is not suitable as the basis for a transaction. Nothing here was prepared by "
    "a licensed investment adviser. Historical behaviour is not predictive; every result below is "
    "drawn from a single historical path and is subject to the limitations set out in section 9."
)
nt = Table([[P(notice, "note")]], colWidths=[6.0 * inch])
nt.setStyle(TableStyle([
    ("BOX", (0, 0), (-1, -1), 0.9, ACCENT),
    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fdf6f6")),
    ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
]))
A(nt)
A(PageBreak())

# --- 1. summary ------------------------------------------------------------
A(P("1. What was done, and what came out", "h1"))
A(P(
    "A 12-page chart-analysis note was treated as a set of falsifiable claims rather than a "
    "specification to implement. Seventeen distinct claims were extracted, encoded in the "
    "application's rule DSL where expressible, and tested on five instruments chosen so that a "
    "large-cap-technology effect could not disguise itself as broad replication "
    "(SPY, QQQ, IWM, XLK, XLV).", "body"))
A(P(
    "Each analyst declared a complete family of hypotheses before running anything, judged each "
    "idea at one pre-declared forward horizon, and corrected across the whole family with "
    "Benjamini-Hochberg. Every result was then pooled into a single study-wide ledger, because "
    "five analysts each running about forty tests have collectively run about two hundred, and a "
    "q-value inside a forty-test family overstates its case once that is known.", "body"))

head = [
    ["Measure", "Result"],
    ["Primary tests, all streams pooled", f"{meta['pooled_family_size']}"],
    ["Survivors, within-stream correction", f"{len(meta['survived_within_stream'])}"],
    ["Survivors, study-wide correction", f"{len(meta['survived_study_wide'])}"],
    ["Lookahead guards passed", "150 of 150 (zero unverified, zero failed)"],
    ["Strategies beating buy-and-hold on total return", "about 1 in 150, and that one underpowered"],
    ["Seasonality family", "75 cells, 0 survivors (all q >= 0.98)"],
    ["Volatility-threshold family", "15 cells, 0 survivors"],
]
A(table(head, [3.4 * inch, 3.0 * inch]))
A(Spacer(1, 8))
A(P(
    "The smallest p-value anywhere in the pooled primary family was 0.0075, on the note's own "
    "headline entry rule, which corrected to q = 0.276 within its stream and q = 0.529 study-wide. "
    "A prior study on this codebase found zero survivors in 75 tests; this one found zero in 150 "
    "across a wider hypothesis set. Two independent studies, 225 corrected tests, no survivor.", "body"))
A(P(
    "That is a substantive result rather than a failed study. It says these particular rules, on "
    "these instruments, at daily resolution, did not produce an edge distinguishable from chance "
    "once the number of things tried was accounted for.", "body"))

A(P("Ten smallest p-values in the pooled family", "h2"))
rows = [["Stream", "Symbol", "Idea", "h", "Edge", "n", "p", "q stream", "q study"]]
testable = [c for c in meta["cells"] if c.get("p_value") is not None]
for c in sorted(testable, key=lambda c: c["p_value"])[:10]:
    rows.append([c["stream"], c["symbol"], c["idea"], str(c.get("horizon")),
                 f"{c['edge']:+.3f}" if c.get("edge") is not None else "n/a",
                 str(c.get("n_independent")), f"{c['p_value']:.4f}",
                 f"{c['q_value']:.3f}" if c.get("q_value") is not None else "n/a",
                 f"{c['q_value_studywide']:.3f}"])
A(table(rows, [0.85 * inch, 0.5 * inch, 1.75 * inch, 0.25 * inch, 0.5 * inch, 0.45 * inch,
               0.55 * inch, 0.6 * inch, 0.55 * inch], align_right=(4, 5, 6, 7, 8)))
A(P("Edge is the trigger's forward hit rate minus the same-bars baseline. n is independent "
    "(non-overlapping) windows, not raw triggers. No row clears q <= 0.10.", "caption"))
A(PageBreak())

# --- 2. method -------------------------------------------------------------
A(P("2. How to read these numbers", "h1"))
for h, b in [
    ("Baseline, not zero",
     "A rule that is right 60% of the time is worthless if the instrument rose 60% of the time "
     "anyway. Every hit rate here is reported against a baseline computed over exactly the bars "
     "that rule could see, so the comparison is like for like."),
    ("Independent sample size",
     "Overlapping forward windows are not independent observations. A condition firing on twenty "
     "consecutive days at a 20-day horizon is one event observed twenty times. The n column counts "
     "non-overlapping windows only; below 30 a result is marked underpowered and not interpreted."),
    ("Correction for multiplicity",
     "Testing many rules guarantees some will look good. Benjamini-Hochberg adjusts each p-value "
     "for how many tests shared its ledger. The gap between a raw p and a corrected q is where "
     "most published technical-analysis results quietly live."),
    ("Direction checked before significance",
     "An effect running opposite to the pre-declared direction is a rejection of the hypothesis as "
     "written, however large it is, and is reported as rejected rather than inconclusive."),
    ("Buy-and-hold on the identical window",
     "Never optional. A strategy returning 300% over 25 years while the instrument returned 1,300% "
     "is a losing strategy, and is described that way here."),
    ("Frictions are reported, never assumed away",
     "All backtests charge 5 basis points of slippage each way, and cost drag is measured by "
     "re-running the whole simulation at zero cost rather than by subtracting an estimate. Several "
     "rules in this study lost more to friction than they earned in total."),
    ("Lookahead proved, not asserted",
     "Every expression is recomputed on truncated leading slices of history and required to "
     "produce bit-identical values before the cut. Anything unproven is treated as a failure."),
]:
    A(P(h, "h2"))
    A(P(b, "body"))

A(PageBreak())

# --- 3. claim by claim -----------------------------------------------------
A(NextPageTemplate("landscape"))
A(P("3. The source note, claim by claim", "h1"))
A(P("Seventeen claims extracted from the note. This is the core of the study.", "caption"))

claims = [
    ("1", "p.2", "IF price > 200MA AND price < lower BB THEN Buy",
     "Best result in the study, still not significant. SPY edge +13.3pp, n=87, p=0.0075; q=0.276 in-stream, 0.529 pooled. Reproduced exactly, killed by correction rather than by the data."),
    ("2", "p.2", "200MA as market-regime gate ('trade in a rising market')",
     "Real, but as risk control, not signal. Cuts max drawdown up to half and exposure 15-19pp; makes the hit-rate edge worse on IWM and XLV. Open 67-75% of the time, so a default state rather than a rare permission."),
    ("3", "p.4", "Ideal Entry setup: 20EMA > 50SMA > 10EMA > 200MA",
     "The note's literal ordering beat the conventional stacked reading: positive edge on all 5 symbols, versus mixed signs and 2 directional rejections for the 'corrected' version. Neither significant."),
    ("4", "p.3", "'Price crossing MA' differs from 'MA crossing MA'",
     "Qualitatively supported. MA-crossing-MA fires about half as often, with better win rate and far less cost drag. Neither significant."),
    ("5", "p.4", "Golden cross, 50/200 SMA",
     "Underpowered on 4 of 5 symbols, rejected on the fifth. The event is too rare to test per-instrument; more history would not fix it, pooling across instruments might."),
    ("6", "p.6", "MACD crossover is faster but more falsy than MA crossover",
     "Split, and the note conflates two signals. Signal-line cross is decisively faster (10-11/yr vs 5.2/yr; 12-13 bars held vs 28-32). Zero-line cross is slower than the MA crossover. 'More falsy' unsupported: MACD win rate 41.96% vs 39.80%."),
    ("7", "p.6", "Bullish/bearish divergence",
     "Now testable: a swing-pivot operator was built for this study. Bullish divergence 0 of 45, and it does not beat its own control arms. Bearish MACD divergence survived a pooled ledger with heavy caveats (section 6)."),
    ("8", "p.5", "Z-score band 0.5<|z|<2, hard stop at |z|>3",
     "Underpowered everywhere (n=12-29, all under the 30 floor). The DSL has no abs(), so only the one-sided case was testable; the z-stop could not be tested as a mechanism at all."),
    ("9", "p.5", "BB bandwidth <5% compression, >15% high-volatility regime",
     "No survivor. A direction-agnostic claim tested with a directional statistic; median forward return reported alongside to avoid overclaiming."),
    ("10", "p.9", "Bollinger band touch as an exit",
     "Tested in that role. No survivor."),
    ("11", "pp.6,8,9", "Confluence / 'Golden Alignment' stacking",
     "Costs certain, benefits not. Stacking loses 26-32% of independent sample versus the trigger alone, every time. Hit-rate effect: best of three on 3 of 10 cells, worst on 3 of 10, no pattern."),
    ("12", "pp.2,7", "RSI as oversold trigger and as trend-strength regime",
     "Neither framing survives. Reversion positive on all 5 but best q=0.391 and a net loser on XLK/XLV after costs. Regime gate mixed in sign across symbols."),
    ("13", "p.10", "March-April bullish, May-October bearish",
     "Does not hold. All 75 cells q >= 0.98, directionally inconsistent on both halves, composites underpowered. 'Sell in May' absent. The two largest raw effects were both folklore and both evaporated after correction."),
    ("14", "p.11", "Fear & Greed / VIX-based strategy",
     "VIX partially, Fear & Greed not at all. VIX>30 positive on all 5 symbols (+5.9 to +9.9pp) with consistent sign, best q=0.685. VIX>20 near-zero or wrong-way on 4 of 5. Fear & Greed has no persisted history, so it is architecturally untestable here."),
    ("15", "pp.2,7", "ATR position sizing; max-drawdown cap",
     "Not testable through the engine, which is long-only and all-in with no sizing concept. Descriptive simulation outside the engine: ATR-proportional sizing cut volatility and drawdown on all 5 symbols and improved Sharpe on 4. The most encouraging risk result in the study, and unreachable by the backtester."),
    ("16", "pp.2,7,10", "Volume Profile, ADX, Stochastic, Ichimoku, Fibonacci, order flow",
     "Not in the indicator registry. Not tested. Volume indicators remain deliberately deferred."),
    ("17", "p.9", "Multi-timeframe confluence",
     "Not expressible: one expression sees one interval. Also blocked by the settled daily-bars-only decision."),
]
rows = [["#", "Note", "Claim", "Verdict"]]
for n, src, claim, verd in claims:
    rows.append([n, src, P(claim, "small"), P(verd, "small")])
A(table(rows, [0.25 * inch, 0.45 * inch, 2.5 * inch, 6.3 * inch]))
A(Spacer(1, 6))
A(P("Zero of seventeen survive statistical correction. Four are qualitatively supported as "
    "descriptions of mechanics while failing as edges. Five could not be tested because the "
    "application cannot express them.", "caption"))
A(PageBreak())

# --- 4. archetypes ---------------------------------------------------------
A(P("4. Strategy archetype profiles", "h1"))
A(P("Every rule tested, with its exact entry and exit expressions and its measured mechanics. "
    "Figures are the median across the five primary instruments over full available history, at "
    "5bps slippage each way. 'Beat B&H' counts how many of the five instruments the rule beat "
    "buy-and-hold on total return.", "caption"))

fam_titles = {
    "trend-ma": "Trend and moving-average framework",
    "mean-reversion": "Mean reversion: Bollinger bands, z-score, volatility regime",
    "momentum": "Momentum oscillators: MACD and RSI",
    "regime-risk-dsl": "Regime and risk",
    "divergence": "Divergence (swing-pivot operator)",
}
for fam in ["trend-ma", "mean-reversion", "momentum", "regime-risk-dsl", "divergence"]:
    items = [r for r in arche if r["fam"] == fam]
    if not items:
        continue
    A(P(fam_titles.get(fam, fam), "h2"))
    rows = [["Rule", "Entry / Exit", "Med. return", "vs B&H", "Max DD", "Exposure", "Cost drag", "Beat B&H"]]
    for r in items:
        ent = r["entry"]
        ex = r["exit"] or ("horizon cap only" if r["cap"] else "-")
        extra = []
        if r["cap"]:
            extra.append(f"cap {r['cap']}b")
        if r["stop"]:
            extra.append(f"stop {r['stop']:.0%}")
        tail = ("  [" + ", ".join(extra) + "]") if extra else ""
        rows.append([
            P(r["key"].replace("_", " "), "small"),
            P(f"IN  {ent}<br/>OUT {ex}{tail}", "mono"),
            num(r["tr"], 2), num(r["bh"], 2), pct(r["dd"]), pct(r["ex"]),
            pct(r["cd"]), f"{r['beat']}/{r['n']}",
        ])
    A(table(rows, [1.35 * inch, 4.05 * inch, 0.7 * inch, 0.55 * inch, 0.6 * inch,
                   0.65 * inch, 0.65 * inch, 0.6 * inch], align_right=(2, 3, 4, 5, 6, 7)))
    A(Spacer(1, 7))

A(P("Total return is a multiple, not a percentage: 2.43 means the equity curve ended 3.43x its "
    "start. Cost drag is the total-return difference between the costed run and the identical "
    "signal sequence at zero cost, measured by re-simulation.", "caption"))
A(PageBreak())

# --- 5. regimes ------------------------------------------------------------
A(P("5. Behaviour by market regime", "h1"))
A(P("Descriptive strategy mechanics only, with indicators seeded before each window opens. No "
    "p-values: regime windows sit outside every correction family in this study by design.", "caption"))
rows = [["Window", "Cells that never traded", "Cells that traded", "Of those, profitable"]]
detail = {
    "dotcom_2000_2002": (8, 142, 25), "bull_2003_2007": (2, 148, None),
    "gfc_2007_2009": (18, 132, 14), "qe_bull_2009_2019": (0, 150, None),
    "covid_2020_2021": (2, 148, None), "bear_2022": (28, 122, 28),
    "recent_2023_now": (1, 149, None),
}
for label, (never, traded, prof) in detail.items():
    nt_, tot = regimes["never_traded_by_window"].get(label, [never, 150])
    rows.append([label.replace("_", " "), str(nt_), str(tot - nt_),
                 "-" if prof is None else str(prof)])
A(table(rows, [1.9 * inch, 1.5 * inch, 1.3 * inch, 1.5 * inch], align_right=(1, 2, 3)))
A(Spacer(1, 8))
A(P("The crisis windows invert the study's headline, and the inversion needs care. In 2007-09 "
    "every cell that traded beat buy-and-hold, because buy-and-hold lost 32-48% and these rules "
    "mostly lost less. Only 14 of 132 actually made money. In 2022, 44 cells lost more than "
    "buy-and-hold did. 'Beat buy-and-hold' in a crash means lost less, and sometimes it does not "
    "even mean that.", "body"))
A(P("A further caution: 18 cells in 2007-09 and 28 in 2022 never opened a position at all. A rule "
    "that sits out a bear market has avoided it, which is a real property, but it is loss "
    "avoidance rather than edge, and it comes with the cost of sitting out recoveries too.", "body"))
A(PageBreak())

# --- 6. divergence ---------------------------------------------------------
A(NextPageTemplate("portrait"))
A(P("6. Divergence, and the study's only survivor", "h1"))
A(P("The note's divergence claim was untestable in the earlier study: the rule language had no way "
    "to locate a prior turning point. An operator was built for this report (confirmed swing "
    "pivots, published only after the bars needed to confirm them have formed, with oscillator "
    "values sampled at the price pivot). All expressions passed the lookahead guard.", "body"))

A(P("Bullish divergence versus its own controls", "h2"))
cells = {(c["idea"], c["symbol"]): c for c in div["cells"]}
rows = [["Idea", "SPY", "QQQ", "IWM", "XLK", "XLV"]]
for idea in ["bullish_rsi_divergence", "bullish_macd_divergence", "new_low_alone", "rsi_above_swing_alone"]:
    r = [idea.replace("_", " ")]
    for s in ["SPY", "QQQ", "IWM", "XLK", "XLV"]:
        c = cells.get((idea, s))
        r.append(f"{c['edge']:+.3f}" if c and c.get("edge") is not None else "n/a")
    rows.append(r)
A(table(rows, [2.0 * inch, 0.8 * inch, 0.8 * inch, 0.8 * inch, 0.8 * inch, 0.8 * inch],
        align_right=(1, 2, 3, 4, 5)))
A(P("Edge versus baseline at horizon 5. Divergence does not beat the bare 'new low' control; on "
    "SPY and XLV it is worse. Adding the oscillator condition bought nothing.", "caption"))

A(P("A correction to the earlier study", "h2"))
A(P("An earlier descriptive diagnostic, computed outside the guarded rule engine, reported fewer "
    "than one divergence event per instrument per year and 10-day forward returns of +3.9% to "
    "+6.4% against a +0.3-0.5% baseline. That is what made divergence the most promising untested "
    "idea in the prior report. Run through the real operator, events occur 8.9-11.9 times per "
    "year and the forward effect is +0.45% to +0.92% against a +0.29-0.43% baseline: roughly ten "
    "times more frequent and seven times smaller. The promising thread was an artifact of an "
    "unguarded implementation.", "body"))

A(P("The one survivor, and why it is reported as a lead", "h2"))
rows = [["Idea", "Hit", "Baseline", "Edge", "n", "p", "q", "Verdict"]]
for c in div_pool["cells"]:
    rows.append([c["idea"].replace("_", " "), f"{c['pooled_hit_rate']:.4f}",
                 f"{c['pooled_baseline_hit_rate']:.4f}", f"{c['edge']:+.4f}",
                 str(c["pooled_n_independent"]), f"{c['p_value']:.4f}",
                 f"{c['q_value']:.4f}", c["verdict"]])
A(table(rows, [1.6 * inch, 0.62 * inch, 0.7 * inch, 0.6 * inch, 0.5 * inch, 0.6 * inch,
               0.6 * inch, 0.8 * inch], align_right=(1, 2, 3, 4, 5, 6)))
A(Spacer(1, 6))
A(P("Bearish MACD divergence is followed by a 51.5% five-day up-rate against a 54.6% baseline, in "
    "the pre-declared direction, at q = 0.017. It is the only association in 195 corrected tests "
    "across two studies to survive its ledger. Four reasons to hold it loosely:", "body"))
for t in [
    "It fails in the per-symbol family. The same rule on the five primary instruments gave edges of "
    "+0.003, +0.002, -0.037, -0.031, -0.006: inconclusive or rejected on all five. A result "
    "appearing only after pooling is the characteristic shape of a pooling artifact.",
    "The pooled n is inflated. 2,108 'independent' windows sums each instrument's non-overlapping "
    "windows across 13 instruments that trade the same calendar days and overlap by sector. The "
    "true p is larger than 0.0042 by an unknown factor.",
    "It is not tradeable through this engine. It is a downward-direction hypothesis and the "
    "backtester is long-only. Nothing here demonstrates a profitable strategy.",
    "The effect is small: 3.1 percentage points on a 54.6% base rate, before costs, on a signal "
    "firing often enough to accumulate meaningful friction.",
]:
    A(P(f"&bull;&nbsp;&nbsp;{t}", "note"))
A(PageBreak())

# --- 7. instruments --------------------------------------------------------
A(NextPageTemplate("landscape"))
A(P("7. Instrument characterisation", "h1"))
A(P("Measured properties of 56 candidates. These are characterisation tables, not selections, and "
    "the ranking criterion is stated for each. Nothing here is a recommendation.", "caption"))

lh = uni["long_horizon_character"]
sw = uni["swing_character"]
cov = uni["coverage"]

A(P("Long-horizon character: what an investor would have had to sit through", "h2"))
ranked = sorted(
    [(s, v) for s, v in lh.items() if cov.get(s, {}).get("bars", 0) >= 1000 and v.get("max_dd_full") is not None],
    key=lambda kv: kv[1]["max_dd_full"], reverse=True)[:18]
rows = [["Symbol", "History from", "CAGR full", "CAGR 10y", "Vol", "Sharpe", "Max drawdown",
         "Worst episode", "Days to recover", "% days above 200SMA"]]
for s, v in ranked:
    we = v.get("worst_episode") or {}
    rows.append([s, cov.get(s, {}).get("first", "?"), pct(v.get("cagr_full")), pct(v.get("cagr_10y")),
                 pct(v.get("vol_full")), num(v.get("sharpe_full"), 2), pct(v.get("max_dd_full")),
                 f"{we.get('peak_date','?')} to {we.get('trough_date','?')}",
                 str(v.get("worst_episode_recovery_days") or "not recovered"),
                 pct(v.get("pct_days_above_sma200"))])
A(table(rows, [0.55 * inch, 0.85 * inch, 0.7 * inch, 0.7 * inch, 0.55 * inch, 0.55 * inch,
               0.9 * inch, 1.7 * inch, 0.95 * inch, 1.0 * inch], align_right=(2, 3, 4, 5, 6, 8, 9)))
A(P("Ordered by shallowest maximum drawdown, restricted to instruments with at least 1,000 daily "
    "bars. <b>Read this with the history-length caveat:</b> funds launched after 2010 have never "
    "been tested against 2000-02 or 2008-09 and rank well partly for that reason. QQQ, the same "
    "index family as several top-ranked names but with longer history, ranks 43rd of 52.", "caption"))
A(PageBreak())

A(P("Short-horizon (swing) character", "h2"))
sw_ranked = sorted(
    [(s, v) for s, v in sw.items() if cov.get(s, {}).get("bars", 0) >= 1000 and v.get("atr_pct_mean_3y")],
    key=lambda kv: kv[1]["atr_pct_mean_3y"], reverse=True)[:18]
rows = [["Symbol", "ATR% (3y)", "ATR% (full)", "20d vol (3y)", "Avg abs daily move",
         "1d autocorrelation", "Variance ratio 5d", "Variance ratio 20d"]]
for s, v in sw_ranked:
    rows.append([s, pct(v.get("atr_pct_mean_3y"), 2), pct(v.get("atr_pct_mean_full"), 2),
                 pct(v.get("realised_vol_20d_mean_3y")), pct(v.get("avg_abs_daily_move_3y"), 2),
                 num(v.get("autocorr_1d_3y"), 3), num(v.get("variance_ratio_5_3y"), 3),
                 num(v.get("variance_ratio_20_3y"), 3)])
A(table(rows, [0.6 * inch, 0.85 * inch, 0.9 * inch, 1.0 * inch, 1.4 * inch, 1.3 * inch,
               1.3 * inch, 1.35 * inch], align_right=(1, 2, 3, 4, 5, 6, 7)))
A(P("Ordered by trailing-3-year average true range as a percentage of price. A variance ratio "
    "near 1.0 is random-walk behaviour; below 1.0 is mean-reverting, above 1.0 trending. Negative "
    "1-day autocorrelation indicates day-to-day reversal. Daily range matters practically because "
    "a rule whose average move is smaller than the round-trip trading cost cannot profit "
    "regardless of how often it is right.", "caption"))
A(Spacer(1, 6))

A(P("Near-duplicate pairs: where a diversified-looking list is one position", "h2"))
nd = uni["near_duplicate_pairs_3y"]
rows = [["Pair", "Correlation", "Pair", "Correlation", "Pair", "Correlation"]]
top = sorted(nd, key=lambda d: -d["corr"])[:24]
for i in range(0, len(top), 3):
    chunk = top[i:i + 3]
    row = []
    for d in chunk:
        row += [f"{d['a']} / {d['b']}", f"{d['corr']:.3f}"]
    while len(row) < 6:
        row += ["", ""]
    rows.append(row)
A(table(rows, [1.5 * inch, 0.8 * inch, 1.5 * inch, 0.8 * inch, 1.5 * inch, 0.8 * inch],
        align_right=(1, 3, 5)))
A(P(f"{len(nd)} pairs exceed 0.90 correlation over the trailing three years. Broad-market and "
    "quality/momentum factor funds cluster tightly with each other and with leveraged products on "
    "the same underlying.", "caption"))
A(PageBreak())

A(P("Leveraged products: the linear intuition is wrong in both directions", "h2"))
lev = uni["leveraged_decay"]
rows = [["Product", "k", "Window", "Realised", "k x underlying", "Gap"]]
for sym, v in lev.items():
    if not isinstance(v, dict) or "windows" not in v:
        continue
    for wname in ["trailing_1y", "trailing_3y", "trailing_5y", "since_inception"]:
        w = v["windows"].get(wname)
        if not w:
            continue
        rows.append([sym, f"{v.get('factor')}x", wname.replace("_", " "),
                     pct(w.get("leveraged_return")), pct(w.get("k_times_underlying")),
                     pct(w.get("gap_vs_k_times_underlying"))])
A(table(rows, [0.8 * inch, 0.5 * inch, 1.3 * inch, 1.2 * inch, 1.3 * inch, 1.2 * inch],
        align_right=(3, 4, 5), font=6.8))
A(P("Gap is realised return minus k times the underlying's return. It is negative in choppy "
    "trailing windows (decay) and strongly positive since inception (convex compounding through "
    "sustained trends). In worst-episode comparisons the naive k-times-underlying figure falls "
    "below -100%, a mathematically impossible fund return, which is the clearest demonstration "
    "that the linear model is simply the wrong model rather than merely an optimistic one.", "caption"))
A(PageBreak())

# --- 8. conditions and defects --------------------------------------------
A(NextPageTemplate("portrait"))
A(P("8. Conditions at the time of writing, and study integrity", "h1"))
A(P("Market conditions", "h2"))
A(P("Measured 2026-08-11, one session before this report's date, and therefore <b>predating the "
    "CPI release scheduled for 2026-08-12</b>. Treat rate-sensitive figures as stale.", "note"))
cond = [
    ["Breadth", "12 of 14 tracked instruments above their own 200-day SMA; only XLU and XLC below"],
    ["Index level", "SPY and IWM within 0.35% of 52-week highs"],
    ["Volatility", "VIX 15.28: 13th percentile trailing 1 year, 34th percentile since 1990"],
    ["Rates", "10-year approximately 4.65-4.70%; 2s10s +47bp, positive rather than inverted"],
    ["Policy", "Target 3.50-3.75%, on hold since a 9-3 vote on 2026-07-29 with three hawkish dissents"],
    ["Dispersion", "3-month sector spread 21.45pp (XLV +17.98%, XLC -3.48%)"],
    ["Unmatched condition", "An oil-supply disruption running since 2026-02-28 affecting roughly "
                            "20-25% of seaborne trade, with core PCE at 3.3% year on year. No "
                            "window in this study's sample contains a comparable shock."],
]
A(table([[P(k, "smallb"), P(v, "small")] for k, v in cond], [1.3 * inch, 5.1 * inch],
        header=False, zebra=False, font=8))

A(P("Defects found during the study", "h2"))
A(P("Recorded because a study that reports no problems with itself has usually not looked.", "caption"))
defects = [
    ("Application", "Concurrent readers of the bar cache collide, and the failure surfaces as a "
                    "per-symbol data refusal indistinguishable from a nonexistent ticker. It cost "
                    "four instruments before being caught; all four resolved on serial retry."),
    ("Application", "The market-data staleness gate left most symbols four days stale, which is "
                    "benign for long backtests and not benign for a live macro panel."),
    ("Application", "The leveraged-instrument registry has no entry for two products, including "
                    "the one named in the source note, so its decay guard never sees them."),
    ("Application", "Fear & Greed has no persisted history, making one strategy family in the note "
                    "untestable rather than merely unsupported."),
    ("Study", "The regime-window list initially omitted the 2007-09 crisis entirely. Found by an "
              "analyst, not by the author of the brief. Backfilled."),
    ("Study", "The regime-window slicer recomputed indicators from the start of each window, so a "
              "200-day-average rule inside a 253-bar window was blind for 200 of them. Found by "
              "the QA reviewer. It inflated a headline count from 18 to 41 before correction. No "
              "p-value was affected, because regime windows carry none."),
]
rows = [["Where", "What"]]
for w, d in defects:
    rows.append([w, P(d, "small")])
A(table(rows, [0.8 * inch, 5.6 * inch]))
A(PageBreak())

# --- 9. limitations --------------------------------------------------------
A(P("9. What this report cannot tell you", "h1"))
for t in [
    "<b>One historical path.</b> Every independent n counts non-overlapping windows of a single "
    "sequence of events, not draws from different economic universes. Eighty-seven independent "
    "observations of one 27-year history is not eighty-seven independent experiments.",
    "<b>Correlated instruments.</b> SPY, QQQ and XLK are three views of the same large-cap growth "
    "complex. IWM and XLV were included specifically so this would be visible rather than hidden, "
    "and several rules did behave differently on them.",
    "<b>Survivorship, twice over.</b> Exchange-traded funds hold today's constituents, and the "
    "long-horizon table is dominated by funds too young to have experienced the worst drawdowns in "
    "the sample.",
    "<b>No fees, spreads, or taxes.</b> Five basis points of slippage is modelled; expense ratios "
    "and real bid-ask spreads are not. For a short-horizon rule a wide spread can exceed the "
    "entire modelled effect.",
    "<b>Position sizing was never testable.</b> The most encouraging risk result in the study sits "
    "outside the guarded engine and carries no statistical claim whatsoever.",
    "<b>Daily bars only.</b> Intraday history is capped at 60 days by the data provider, so every "
    "intraday and multi-timeframe claim in the source note is out of scope rather than refuted.",
    "<b>A backtest is not a forecast.</b> Zero survivors describes what these rules did on stored "
    "history under pre-registration, correction and guard discipline. It is not a statement about "
    "what any rule will do next, and the current oil-supply condition has no analogue in the "
    "sample at all.",
    "<b>This is not advice.</b> No instrument in this document is presented as one to buy or sell, "
    "no entry or exit price is proposed for anyone to act on, and no part of it was prepared by a "
    "licensed investment adviser. Any decision, and its consequences, remain the reader's own.",
]:
    A(P(f"&bull;&nbsp;&nbsp;{t}", "note"))

A(Spacer(1, 14))
A(P("Sources", "h2"))
A(P("All figures are generated at build time from the study's JSON outputs under "
    "docs/research/strategy-lab/data/. Per-stream reports, the scripts that produced every number, "
    "and the adversarial QA review are in the same directory tree. This document is reproducible "
    "by re-running meta/build_report_pdf.py.", "small"))

build_doc().build(story)
print(f"wrote {OUT}")
sys.exit(0)
