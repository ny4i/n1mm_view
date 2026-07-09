#!/usr/bin/python3
"""
check_operator_worked.py  --  READ-ONLY rule check for qso_log.

Field Day rule: a person who operated from our site may not also be *worked* by
our site as a separate station -- you cannot work your own effort. This script
cross-references the `operator` table (the people who logged QSOs here, by their
own callsign) against the worked callsigns in `qso_log.callsign` and reports any
overlap, with the full detail of each offending contact so it can be reviewed
and removed in TR4W (the logger / Cabrillo source).

Matching is case-insensitive on the bare callsign.

By default the script is READ-ONLY and only reports. With --apply it sets the
qso_log.own_effort flag (1) on the offending QSOs so they are excluded from
counts/charts/score, creating a timestamped backup of the database first. The
apply pass is idempotent: it clears own_effort and recomputes from scratch every
run. own_effort is a separate column from the dupe flag, so this never disturbs
find_dupes.py's results (and vice versa).

Usage:
    python3 check_operator_worked.py                 # report only, INI database
    python3 check_operator_worked.py some_event.db   # report only, specific DB
    python3 check_operator_worked.py --apply         # flag own-effort QSOs
    python3 check_operator_worked.py --apply --no-backup
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


def band_name(band_id):
    titles = constants.Bands.BANDS_TITLE
    return titles[band_id] if 0 <= band_id < len(titles) else '?%d' % band_id


def mode_name(mode_id):
    modes = constants.Modes.MODES_LIST
    return modes[mode_id] if 0 <= mode_id < len(modes) else '?%d' % mode_id


def ensure_own_effort_column(db, cursor):
    """Add the qso_log.own_effort flag if this DB predates it. Idempotent.

    Mirrors the canonical migration in dataaccess.create_tables() so --apply
    works standalone against an old backup the app has never opened.
    """
    try:
        cursor.execute('ALTER TABLE qso_log ADD COLUMN own_effort INTEGER NOT NULL DEFAULT 0;')
        cursor.execute('CREATE INDEX IF NOT EXISTS qso_log_own_effort ON qso_log(own_effort);')
        db.commit()
        print('Added own_effort column to qso_log.')
    except sqlite3.OperationalError:
        pass  # column already exists


def backup_database(db_path):
    """Copy db_path to db_path.<YYYYMMDD-HHMMSS>.bak and return the backup path."""
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_path = '%s.%s.bak' % (db_path, stamp)
    shutil.copy2(db_path, backup_path)
    return backup_path


def apply_flags(db_path, offender_qso_ids, make_backup):
    """Set own_effort = 1 on the offending QSOs; 0 on everything else.

    Recomputes from a clean slate each run (clears own_effort first), so the
    result depends only on the current contents of the log, not prior runs.
    Touches only own_effort -- the dupe flag is left exactly as it was.
    """
    if make_backup:
        print('Backup   : %s' % backup_database(db_path))
    else:
        print('Backup   : SKIPPED (--no-backup)')

    db = sqlite3.connect(db_path)
    try:
        cursor = db.cursor()
        ensure_own_effort_column(db, cursor)
        cursor.execute('UPDATE qso_log SET own_effort = 0;')
        cursor.executemany('UPDATE qso_log SET own_effort = 1 WHERE qso_id = ?;',
                           [(qid,) for qid in offender_qso_ids])
        db.commit()
        flagged = cursor.execute('SELECT COUNT(*) FROM qso_log WHERE own_effort = 1;').fetchone()[0]
    finally:
        db.close()
    print('Applied  : %d QSO(s) now flagged own_effort = 1.' % flagged)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('database', nargs='?', default=None,
                        help='SQLite DB to inspect (default: DATABASE_FILENAME from INI)')
    parser.add_argument('--apply', action='store_true',
                        help='Flag offending QSOs own_effort = 1 (backs up first)')
    parser.add_argument('--no-backup', action='store_true',
                        help='With --apply, skip making a timestamped backup')
    args = parser.parse_args()

    db_path = args.database or Config().DATABASE_FILENAME
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    cursor = db.cursor()

    # Each QSO where the worked callsign matches one of our operators' calls.
    # log_op is the operator who logged the contact (joined via operator_id).
    cursor.execute(
        'SELECT q.timestamp, q.callsign AS worked, q.band_id, q.mode_id, '
        '       q.exchange, q.section, log_op.name AS logged_by, q.qso_id '
        'FROM qso_log q '
        'JOIN operator site_op ON UPPER(site_op.name) = UPPER(q.callsign) '
        'LEFT JOIN operator log_op ON log_op.id = q.operator_id '
        'ORDER BY UPPER(q.callsign), q.timestamp;')
    rows = cursor.fetchall()
    db.close()

    print('Database : %s' % db_path)
    print('Rule     : a site operator may not be worked as a station (own effort)')
    print('-' * 70)

    if not rows:
        print('OK -- no site operator appears as a worked callsign.')
        if args.apply:
            apply_flags(db_path, [], make_backup=not args.no_backup)
        return 0

    # Group offending QSOs by the operator callsign that was worked.
    by_call = {}
    for r in rows:
        by_call.setdefault(r['worked'].upper(), []).append(r)

    def when(ts):
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    for call in sorted(by_call):
        hits = by_call[call]
        print('\n!! %s -- site operator worked as a station %d time(s):' % (call, len(hits)))
        for r in hits:
            print('     %s  %-4s %-5s  ex=%-6s sec=%-4s  logged by %s'
                  % (when(r['timestamp']), band_name(r['band_id']),
                     mode_name(r['mode_id']), (r['exchange'] or '').strip(),
                     (r['section'] or '').strip(), r['logged_by'] or '?'))
            print('       qso_id=%s' % r['qso_id'])

    print('-' * 70)
    print('Found %d offending QSO(s) across %d operator call(s).'
          % (len(rows), len(by_call)))
    if args.apply:
        apply_flags(db_path, [r['qso_id'] for r in rows],
                    make_backup=not args.no_backup)
        print('Also delete these in TR4W (the Cabrillo source); the flag only '
              'fixes the dashboard DB.')
    else:
        print('Review and delete these in TR4W (then re-sync); they should not count.')
        print('Or run with --apply to flag them own_effort = 1 in this DB (backs up first).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
