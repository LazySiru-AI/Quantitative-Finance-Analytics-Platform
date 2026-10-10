"""Command-line entry point for ingestion::

    python -m app.ingest --init       # write a manifest template for the files found
    python -m app.ingest --dry-run    # show the file -> account attribution, write nothing
    python -m app.ingest              # import everything declared in the manifest
    python -m app.ingest FILE...      # import specific files (still manifest-declared)

Run from ``backend/``, or anywhere with the ``app`` package importable.

**Why a command and not only an HTTP route.** The API needs a server running, and the first thing a
new checkout needs to do is populate an empty ledger -- before there is anything for a server to
serve. This is also the form that fits the way the data actually arrives: the user exports eight
CSVs into a directory and wants them in, which is one command, not eight clicks.

Exit codes: ``0`` when every file landed cleanly, ``1`` when any file failed, was undeclared, or
produced a conflict. Conflicts are failures here for the same reason they are in
:attr:`~app.ingest.service.ImportRun.ok` -- a restated figure that silently did not overwrite a
stored one is not a successful import.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from app.config import get_settings
from app.core.models import Broker
from app.datasource import read_document, write_document
from app.ingest import registry, service
from app.ingest.manifest import ManifestError, render_template
from app.ingest.provenance import read_rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.ingest",
        description="Import broker exports into the ledger.",
    )
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="Specific exports to import. Defaults to every CSV under the data directory.",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="Write an account-manifest template covering the exports found, then exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which account each file resolves to, without writing anything.",
    )
    parser.add_argument(
        "--force-init",
        action="store_true",
        help="With --init, overwrite an existing manifest.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    targets = tuple(args.files) if args.files else None

    if args.init:
        return _init(force=args.force_init)

    if args.dry_run:
        return _dry_run(targets)

    try:
        run = service.import_paths(targets, settings=settings)
    except ManifestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(service.summarise(run.files))
    print()
    print(f"ledger: {run.txn_count} transactions, fingerprint {run.ledger_fingerprint[:12]}")
    if run.conflicted:
        print()
        print("conflicts -- nothing was overwritten; each stored row was left as it was:")
        for item in run.conflicted:
            for conflict in item.conflicts:
                print(f"  {item.path.name}: {conflict}")
    if run.failures:
        print()
        print(f"{len(run.failures)} file(s) did not import.", file=sys.stderr)
    return 0 if run.ok else 1


def _init(*, force: bool) -> int:
    settings = get_settings()
    path = service.manifest_path(settings)
    if read_document("accounts-manifest", settings) is not None and not force:
        print(
            f"{path} already exists. Edit it by hand, or pass --force-init to replace it "
            "(which discards the tax treatments already recorded there).",
            file=sys.stderr,
        )
        return 1

    registry.load_builtin_adapters()
    detected: list[tuple[Path, str, Broker]] = []
    unmatched: list[Path] = []
    for export in service.discover_exports(settings):
        try:
            raw = read_rows(export, settings=settings)
            adapter = registry.resolve(raw)
        except Exception:
            # Deliberately broad, and only here: --init's job is to describe what is present, so a
            # file it cannot read is reported in the output rather than allowed to abort the
            # template for every other file. The import path itself narrows by exception type.
            unmatched.append(export)
            continue
        detected.append((export, adapter.name, adapter.broker))

    text = render_template(detected, data_dir=settings.data_dir)
    write_document("accounts-manifest", text, settings)

    print(f"wrote {path} covering {len(detected)} export(s).")
    for export in unmatched:
        print(f"  skipped {export.name}: no adapter recognised its header")
    print()
    print("Fill in tax_treatment for every entry, then run: python -m app.ingest")
    return 0


def _dry_run(targets: tuple[Path, ...] | None) -> int:
    planned = service.plan_import(targets)
    if not planned:
        print("no broker exports found.")
        return 0
    for item in planned:
        head = f"{item.path.name:<40} {item.status.value:<11}"
        if item.status is service.FileStatus.IMPORTED:
            state = "already imported" if item.already_imported else "would import"
            print(
                f"{head} {state:<17} {item.row_count:>5} rows -> {item.account_id} "
                f"({item.tax_treatment}) via {item.adapter}"
            )
        else:
            print(f"{head} {item.detail or ''}")
    return 0 if all(p.status is service.FileStatus.IMPORTED for p in planned) else 1


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
