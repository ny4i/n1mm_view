#!/usr/bin/python3
"""
find_dupes.py  --  Field Day duplicate finder/flagger for qso_log.

A Field Day duplicate is the same worked callsign, same band, same *simple mode
group* (CW / PHONE / DATA) -- NOT the same exact submode. FT8 and FT4 on one
band, for example, are the same DATA contact and the second one is a dupe.

The "keeper" in each dupe group is the earliest QSO by timestamp; every later
QSO is a duplicate that should not be counted.

By default the script is READ-ONLY and only reports. With --apply it sets the
qso_log.duplicate flag (0 = counts, 1 = dupe), creating a timestamped backup of
the database first. The apply pass is idempotent: it clears all flags and
recomputes from scratch every run, so re-running is always safe.

Usage:
    python3 find_dupes.py                 # report only, DATABASE_FILENAME from INI
    python3 find_dupes.py some_event.db   # report only, specific database
    python3 find_dupes.py --verbose       # list every QSO in each dupe group
    python3 find_dupes.py --apply         # flag dupes (backs up the DB first)
    python3 find_dupes.py --apply --no-backup   # flag without making a backup
"""

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone

# Running from the utils/ subdirectory: put the project root on sys.path so the
# shared top-level modules (config, constants, dataaccess, graphics) import.
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import constants
from config import Config


def simple_mode_name(mode_id):
    """Map a stored mode_id to its FD scoring group: CW / PHONE / DATA."""
    table = constants.Modes.MODE_TO_SIMPLE_MODE
    idx = table[mode_id] if 0 <= mode_id < len(table) else 0
    return constants.Modes.SIMPLE_MODES_LIST[idx]


def band_name(band_id):
    titles = constants.Bands.BANDS_TITLE
    return titles[band_id] if 0 <= band_id < len(titles) else '?%d' % band_id


def ensure_duplicate_column(db, cursor):
    """Add the qso_log.duplicate flag if this DB predates it. Idempotent.

    Mirrors the canonical migration in dataaccess.create_tables() so --apply
    works standalone against an old backup that the app has never opened.
    """
    try:
        cursor.execute('ALTER TABLE qso_log ADD COLUMN duplicate INTEGER NOT NULL DEFAULT 0;')
        cursor.execute('CREATE INDEX IF NOT EXISTS qso_log_duplicate ON qso_log(duplicate);')
        db.commit()
        print('Added duplicate column to qso_log.')
    except sqlite3.OperationalError:
        pass  # column already exists


def backup_database(db_path):
    """Copy db_path to db_path.<YYYYMMDD-HHMMSS>.bak and return the backup path."""
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_path = '%s.%s.bak' % (db_path, stamp)
    shutil.copy2(db_path, backup_path)
    return backup_path


def apply_flags(db_path, dupe_groups, make_backup):
    """Set qso_log.duplicate = 1 for every non-keeper QSO; 0 for everything else.

    Recomputes from a clean slate each run (clears all flags first), so the
    result depends only on the current contents of the log, not prior runs.
    """
    if make_backup:
        backup_path = backup_database(db_path)
        print('Backup   : %s' % backup_path)
    else:
        print('Backup   : SKIPPED (--no-backup)')

    dupe_ids = [row['qso_id'] for rows in dupe_groups.values() for row in rows[1:]]

    db = sqlite3.connect(db_path)
    try:
        cursor = db.cursor()
        ensure_duplicate_column(db, cursor)
        cursor.execute('UPDATE qso_log SET duplicate = 0;')
        cursor.executemany('UPDATE qso_log SET duplicate = 1 WHERE qso_id = ?;',
                           [(qid,) for qid in dupe_ids])
        db.commit()
        flagged = cursor.execute('SELECT COUNT(*) FROM qso_log WHERE duplicate = 1;').fetchone()[0]
    finally:
        db.close()
    print('Applied  : %d QSO(s) now flagged duplicate = 1.' % flagged)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('database', nargs='?', default=None,
                        help='SQLite DB to inspect (default: DATABASE_FILENAME from INI)')
    parser.add_argument('--verbose', action='store_true',
                        help='List every QSO in each duplicate group, not just a summary')
    parser.add_argument('--apply', action='store_true',
                        help='Write the duplicate flag to the database (backs up first)')
    parser.add_argument('--no-backup', action='store_true',
                        help='With --apply, skip making a timestamped backup')
    args = parser.parse_args()

    db_path = args.database or Config().DATABASE_FILENAME
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    cursor = db.cursor()

    cursor.execute('SELECT timestamp, callsign, band_id, mode_id, qso_id FROM qso_log '
                   'ORDER BY timestamp, qso_id;')

    # group key -> list of rows (already time-ordered, so first is the keeper)
    groups = {}
    for row in cursor.fetchall():
        key = (row['callsign'].strip().upper(), row['band_id'], simple_mode_name(row['mode_id']))
        groups.setdefault(key, []).append(row)
    db.close()

    dupe_groups = {k: v for k, v in groups.items() if len(v) > 1}
    dupe_rows = sum(len(v) - 1 for v in dupe_groups.values())

    print('Database : %s' % db_path)
    print('QSOs     : %d' % sum(len(v) for v in groups.values()))
    print('Dupe sets: %d   (callsign + band + CW/PHONE/DATA group)' % len(dupe_groups))
    print('Dupe QSOs: %d   (extra contacts beyond the first in each set)' % dupe_rows)
    print('-' * 64)

    if not dupe_groups:
        print('No duplicates found.')
        return 0

    def when(ts):
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime('%m-%d %H:%M')

    for (call, band_id, smode), rows in sorted(dupe_groups.items(),
                                               key=lambda kv: (-len(kv[1]), kv[0][0])):
        keeper, dupes = rows[0], rows[1:]
        print('%-10s %-4s %-5s  x%d  keep %s  dupe(s): %s'
              % (call, band_name(band_id), smode, len(rows),
                 when(keeper['timestamp']),
                 ', '.join(when(d['timestamp']) for d in dupes)))
        if args.verbose:
            for r in rows:
                tag = 'KEEP ' if r is keeper else 'DUPE '
                print('    %s %s  qso_id=%s' % (tag, when(r['timestamp']), r['qso_id']))

    print('-' * 64)
    if args.apply:
        apply_flags(db_path, dupe_groups, make_backup=not args.no_backup)
    else:
        print('Read-only: nothing was modified. %d QSO(s) would be flagged as dupes.'
              % dupe_rows)
        print('Re-run with --apply to write the duplicate flag (backs up first).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
