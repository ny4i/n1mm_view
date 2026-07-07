#!/usr/bin/env python3
"""
backfill_zones.py

Populate the qso_log.ituzone / qso_log.cqzone column for rows logged before the
zone columns existed, by parsing the zone out of the stored exchange.

For zone contests the received exchange is "RST zone" (e.g. "59 8"), so the zone
is the trailing whitespace-separated integer. Only rows whose target column is
currently NULL are touched, and only a value in the valid range is written
(1..90 for ITU, 1..40 for CQ), so the pass is safe to re-run.

The target column defaults to the one matching config.MULTS (ituzone for
ITUZONES, cqzone for CQZONES); override with --column.

Usage:
    python3 backfill_zones.py                     # dry run against config DB
    python3 backfill_zones.py --apply             # write changes (makes a backup)
    python3 backfill_zones.py --column cqzone --db some.db --apply
"""

import argparse
import logging
import os
import shutil
import sqlite3
import time

from config import Config

config = Config()

# column -> inclusive max zone number for validation
ZONE_MAX = {'ituzone': 90, 'cqzone': 40}

# config.MULTS -> default zone column
MULTS_COLUMN = {'ITUZONES': 'ituzone', 'CQZONES': 'cqzone'}


def parse_zone(exchange, zone_max):
    """Return the zone (1..zone_max) from an exchange string, or None.

    The zone is the trailing integer token of "RST zone" (e.g. "59 8" -> 8).
    """
    if not exchange:
        return None
    tokens = exchange.split()
    if not tokens:
        return None
    last = tokens[-1]
    if not last.isdigit():
        return None
    zone = int(last)
    return zone if 1 <= zone <= zone_max else None


def backfill(db_path, column, apply_changes):
    if column not in ZONE_MAX:
        raise SystemExit('unknown zone column: %s (expected one of %s)'
                         % (column, ', '.join(ZONE_MAX)))
    if not os.path.exists(db_path):
        raise SystemExit('database not found: %s' % db_path)

    zone_max = ZONE_MAX[column]
    db = sqlite3.connect(db_path)
    cur = db.cursor()

    cols = [r[1] for r in cur.execute('PRAGMA table_info(qso_log)')]
    if column not in cols:
        raise SystemExit('qso_log has no %s column; run the migration first '
                         '(open the DB with dataaccess.create_tables)' % column)

    rows = cur.execute(
        'SELECT qso_id, callsign, exchange FROM qso_log WHERE %s IS NULL' % column
    ).fetchall()

    planned = []   # (qso_id, callsign, exchange, zone)
    skipped = []   # (callsign, exchange)
    for qso_id, callsign, exchange in rows:
        zone = parse_zone(exchange, zone_max)
        if zone is None:
            skipped.append((callsign, exchange))
        else:
            planned.append((qso_id, callsign, exchange, zone))

    print('%s: %d row(s) with NULL %s; %d parseable, %d unparseable'
          % (column, len(rows), column, len(planned), len(skipped)))
    for _, callsign, exchange, zone in planned:
        print('  %-12s exchange=%-8r -> %s %d' % (callsign, exchange, column, zone))
    for callsign, exchange in skipped:
        print('  SKIP %-12s exchange=%r (no zone found)' % (callsign, exchange))

    if not planned:
        print('nothing to backfill.')
        return

    if not apply_changes:
        print('\ndry run -- re-run with --apply to write these changes.')
        return

    backup = '%s.%s.bak' % (db_path, time.strftime('%Y%m%d-%H%M%S', time.gmtime()))
    shutil.copy2(db_path, backup)
    print('\nbacked up to %s' % backup)

    cur.executemany('UPDATE qso_log SET %s = ? WHERE qso_id = ?' % column,
                    [(zone, qso_id) for qso_id, _, _, zone in planned])
    db.commit()
    print('updated %d row(s).' % len(planned))
    db.close()


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', default=config.DATABASE_FILENAME,
                    help='database file (default: %(default)s)')
    ap.add_argument('--column', default=MULTS_COLUMN.get(config.MULTS),
                    choices=sorted(ZONE_MAX),
                    help='zone column to fill (default: from config.MULTS)')
    ap.add_argument('--apply', action='store_true',
                    help='write changes (otherwise dry run)')
    args = ap.parse_args()
    if not args.column:
        ap.error('config.MULTS=%s is not a zone contest; pass --column ituzone|cqzone'
                 % config.MULTS)
    backfill(args.db, args.column, args.apply)


if __name__ == '__main__':
    main()
