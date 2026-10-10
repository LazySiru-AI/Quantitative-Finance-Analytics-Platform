"""Per-holding reports, and the grounding contract that keeps their prose honest.

Two modules with a hard line between them.

:mod:`~app.report.builder` computes. It assembles a :class:`~app.report.models.FactBundle` -- every
figure a report could want, each carrying a pointer to where it came from -- out of the Phase 4-7
engines. Nothing in this package computes a statistic that those engines do not already own.

:mod:`~app.report.narrative` writes, and is not trusted. A narrative is a *template* whose every
number arrives through a ``{{fact:id}}`` reference resolved against the bundle at render time. A
draft that names a fact the bundle does not hold, or that writes a bare numeral of its own, is
rejected before rendering.

**The enforcement is code, not a prompt.** "Only cite figures from the bundle" is an instruction a
language model follows most of the time, and the failures are precisely the plausible-looking
sentences nobody checks. Making numerals unwriteable is the version of that rule which holds when
the model is careless, when it is jailbroken, and when the model is swapped for a different one.
No model is wired up in this repo, and none is needed for the contract to be real: the default
narrator is deterministic, and it goes through the identical verification.
"""
