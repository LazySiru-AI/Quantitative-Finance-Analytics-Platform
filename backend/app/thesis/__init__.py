"""Agent-proposed theses, adversarially tested.

**Read this before the code.** An agent that generates theses and tests them until one looks good is
a p-hacking machine. That is not a risk of this design, it is the *default behaviour* of this design.
A generator can produce fifty plausible theses about any ticker in a minute; at a 5% threshold, two
or three clear it on noise alone, and those are precisely the ones a naive loop reports back as
discoveries.

Three properties of this specific setup make it worse than ordinary multiple testing:

1. **The trial count is invisible.** A human running two hundred rule combinations knows they ran two
   hundred. A loop that discards weak theses mid-iteration and never mentions them leaves no
   denominator behind.
2. **The generator sees the data.** A thesis proposed after looking at the chart is a description of
   the sample dressed as a hypothesis about the process.
3. **Iteration is unbounded by default.** "Loop until the thesis is proven" always terminates
   successfully, because there is always another specification that works.

So this package is mostly machinery for saying *no*, and it adds no statistics of its own -- every
number comes from the Phase 6-8 engines. Four guards, none optional; removing any one turns the
feature into a confident liar, which is worse than not shipping it.

===========================  ===============================================================
Guard                        Mechanism
===========================  ===============================================================
Pre-registration             :mod:`~app.thesis.preregister` content-hashes the hypothesis,
                             its entry, exit, horizon, predicted direction and explicit
                             falsification criterion **before** any backtest runs. Results
                             join to the frozen hash. A thesis edited after seeing results is
                             a *new* thesis with a new hash and a new slot in the trial count.
Global trial ledger          :mod:`~app.thesis.ledger` persists every thesis ever registered
                             for a ticker in SQLite -- including abandoned and rejected ones.
                             Benjamini-Hochberg runs over the **whole ledger for that ticker**,
                             not the current session, so the q-value of thesis #40 reflects
                             the 39 before it and the denominator survives a restart.
Locked holdout               :mod:`~app.thesis.holdout` splits history into in-sample and a
                             holdout the loop cannot read. A thesis freezes on in-sample, then
                             gets **one** evaluation against the holdout. A second look burns
                             the holdout for that ticker and the refusal is surfaced.
Declared iteration budget    :mod:`~app.thesis.loop` declares its budget up front. Every
                             iteration decrements it whether or not it produced a result.
                             Exhausting the budget with nothing surviving is a **valid,
                             reportable outcome** -- "no thesis survived twelve attempts" is
                             real information about the ticker.
===========================  ===============================================================

**What this will not do.** It will not place orders -- read-only with respect to money, unchanged. It
will not tell anyone to buy anything: a strategy card reports what a rule did historically, with its
sample size and its failures, and is not a recommendation. And it will not report a thesis it cannot
support -- underpowered is a verdict, not a gap to be filled with narrative.

**No model is wired up here, and the guards do not depend on one.** The default author proposes from
the instrument's structure and priors -- its mechanics, its regime history, its drawdown profile --
rather than from a fishing expedition over the sample, which is what property (2) above demands.
Swapping in a language model changes who writes the hypothesis; it changes nothing about the
machinery that refuses it, exactly as :mod:`app.report.narrative` refuses ungrounded prose whether a
model or a template wrote it.
"""
