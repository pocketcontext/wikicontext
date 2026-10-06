"""Consistent database-only snapshots for isolated synthetic search fixtures.

This helper does not recover original files and is not an operational backup tool.
"""
from contextlib import closing
from pathlib import Path
import sqlite3


def snapshot(data, dest):
    data, dest = Path(data), Path(dest)
    dest.mkdir(parents=True, exist_ok=False)
    with closing(sqlite3.connect((data / "data.db").resolve().as_uri() + "?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(dest / "data.db")) as target:
            source.backup(target)
            target.execute("PRAGMA journal_mode=DELETE")
            if target.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise RuntimeError("synthetic database snapshot failed integrity check")
