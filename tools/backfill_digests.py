"""Write `gen{N:04d}/DIGEST.md` for every existing generation directory and rebuild `JOURNAL.md`.

    .venv/Scripts/python.exe tools/backfill_digests.py               (dry run, the default)
    .venv/Scripts/python.exe tools/backfill_digests.py --dry-run
    .venv/Scripts/python.exe tools/backfill_digests.py --apply

**Why this exists.** `app.evolution.digest.write_digest` is meant to be called once per generation by
`app.evolution.loop`, right after that generation's `OUTCOME.json` is written -- see this workstream's
own report for the exact call site. But 233 generations already exist on disk with no `DIGEST.md` at
all, written before this feature did, and the owner asked for a per-generation summary of "what a
generation taught and what the next one will try" for the run that already happened, not only for runs
that happen from here on. This script is that one-time catch-up, built to be re-run safely as many
times as needed (a second `--apply` after a `render_digest` bug fix, for instance) rather than only
once.

**Idempotent.** `app.evolution.digest.write_digest` reports `changed=False`, and writes nothing, when
the freshly rendered Markdown already matches what is on disk -- this script trusts that signal
directly rather than re-deriving its own idempotency check; see that function's own docstring for why
the comparison is meaningful (`render_digest` is pure, so identical inputs always render identical
text).

**`--dry-run` is the default, and `--apply` is the only way to write anything.** This mirrors
`tools/migrate_seat_pipeline.py`'s own convention for a one-time, disk-mutating script, except that
tool requires one of the two flags explicitly; this one does not, since a bare invocation with no flag
at all is the safer thing to have happen by accident -- it previews, it never writes.

Full digests for generation 1859 (an ordinary succeeded generation) and generation 1673 (the first
generation directory after the documented gap, and one of the two directories in this tree whose own
`OUTCOME.json` cannot be read at all) are always printed in full, dry run or not, so a reviewer never
has to re-run this script with extra flags to see the two cases the brief asked to be shown.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from app.config import get_settings
from app.evolution import digest
from app.evolution.models import loop_root

__all__ = ["main", "parse_args"]

#: Always printed in full -- see this module's own docstring for why these two.
_ALWAYS_SHOW = (1859, 1673)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true", help="report what would change; write nothing (default)"
    )
    mode.add_argument(
        "--apply", action="store_true", help="write every DIGEST.md and rebuild JOURNAL.md"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    apply = args.apply

    settings = get_settings()
    root = loop_root(settings)
    generations = digest.existing_generation_numbers(root)

    print(f"{'APPLY' if apply else 'DRY RUN'}: {len(generations)} generation directory(ies) under {root}")

    caveat = digest.caveat_stats(settings)
    fraction = caveat.positive_fraction
    pct = "n/a" if fraction is None else f"{fraction * 100:.1f}%"
    print(
        f"Standing caveat (ledger snapshot): {caveat.positive}/{caveat.total} holdout-measured "
        f"candidates positive ({pct}), {caveat.candidates_ever_run} ledger row(s) total"
    )

    written = 0
    unchanged = 0
    for generation in generations:
        markdown, changed = digest.write_digest(
            generation, settings=settings, caveat=caveat, dry_run=not apply
        )
        if changed:
            written += 1
        else:
            unchanged += 1
        if generation in _ALWAYS_SHOW:
            label = "would write" if not apply else "wrote"
            print(f"\n{'=' * 88}")
            print(f"gen{generation:04d}/DIGEST.md ({label}, changed={changed}):")
            print("=" * 88)
            print(markdown)

    verb = "Would write" if not apply else "Wrote"
    print(f"\n{verb} {written} digest(s); {unchanged} already matched what is on disk.")

    if apply:
        journal = digest.rebuild_journal(settings=settings)
        print(f"Rebuilt {journal}")
    else:
        print("Dry run: JOURNAL.md was not rebuilt. Re-run with --apply to write digests and the journal.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
