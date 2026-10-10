"""The evolution loop: competition rounds that design their own successors.

`app.tournament.jobs` runs *one* round of *pre-authored* cards. This package is the layer above it:
a supervisor that proposes a generation of candidates, runs them through the existing round machinery,
reads the leaderboard, and uses what it learned to propose the next generation -- indefinitely, until
a human stops it.

Module map, in the order one iteration touches them:

    models.py       the shared vocabulary (this package's contract; every module below imports it)
    universe.py     the purpose-partitioned ticker pools a candidate may draw from
    genome.py       the heritable description of a candidate, and the mutation/crossover operators
    ruleforms.py    the eight rule shapes a `rules` genome may express, and the discipline read off one
    proposer.py     genome -> a real `StrategyCard` / `AllocationCard` on disk
    news_signal.py  optional: which tickers the news is talking about, as a universe bias
    execute.py      run one generation through the round machinery, respecting its single-slot lock
    feedback.py     leaderboard -> findings -> the next generation's seed population
    ledger.py       every candidate the loop has ever run, for the multiple-comparison denominator
    promotion.py    the gate, and the write into the library + paper-desk roster overlay
    loop.py         the supervisor thread that sequences all of the above
    goal_directives.py  reads `LoopConfig.goal` *for a reader, never for the search*: text shaped like
                    a config directive that the run does not carry, noted in `gen{N}/PLAN.md`

Two rules from `strategy-program/AGENTS-INTEGRATION-PLAN.md` govern the whole package and are not
negotiable by anything in it:

*No model in the scoring path.* Proposal is generative; scoring is not. Every number this package
reports comes from `app.tournament.results`, computed from run files the existing engine wrote. The
proposer chooses *what to test*; it never has an opinion about *how it did*.

*A search that never stops is a multiple-comparison problem that never stops.* An infinite loop over
a parameter space will eventually produce a card that looks excellent and is not, and it will do so
by construction rather than by accident. Three mechanisms in this package exist only to make that
survivable, and removing any of them makes the loop's output worthless rather than merely noisier:
`ledger.py` keeps the correction denominator at *every candidate the loop has ever run* rather than
the current generation; `LoopConfig.holdout_windows` reserves regimes that selection never sees and
promotion must not contradict; and `promotion.py` requires the same genome to clear the gate in two
consecutive generations on differing window sets, which is `strategy-program/PROTOCOL.md` §6's rule
applied to a searcher that can propose far faster than a human analyst can.
"""
