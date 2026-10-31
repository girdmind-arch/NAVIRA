"""Import a locally reviewed JSON dataset. This command performs no downloads."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.core import connect, init_db
from backend.app.services.route_safety_import import import_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="Reviewed JSON dataset containing source metadata and records")
    parser.add_argument("--dry-run", action="store_true", help="Validate the input without writing records")
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    init_db()
    with connect() as db:
        print(json.dumps(import_dataset(db, dataset, dry_run=args.dry_run), indent=2))


if __name__ == "__main__":
    main()
