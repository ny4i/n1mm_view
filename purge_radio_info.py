#!/usr/bin/python3
"""
purge_radio_info.py

Delete leftover rows from the radio_info table.

Usage:
    ./purge_radio_info.py                # delete rows older than RADIO_HIDE_SECONDS
    ./purge_radio_info.py --older-than 0 # alias for --all (delete everything)
    ./purge_radio_info.py --older-than 300
    ./purge_radio_info.py --all
    ./purge_radio_info.py --list         # show current rows with age, don't delete

The collector clears the table on startup via dataaccess.clear_radio_info(),
so this tool is for the in-between case: pruning stale rows without bouncing
the collector mid-event.
"""

import argparse
import logging
import sqlite3
import sys
import time

from config import Config
import dataaccess

__author__ = 'Tom Schaefer NY4I'
__license__ = 'Simplified BSD'

config = Config()
logger = logging.getLogger(__name__)


def list_rows(cursor):
    cursor.execute(
        'SELECT station_name, radio_nr, radio_name, op_call, is_active,\n'
        '       is_connected, is_transmitting, last_update,\n'
        '       (strftime(\'%s\',\'now\') - last_update) AS age\n'
        '  FROM radio_info ORDER BY station_name, radio_nr;')
    rows = cursor.fetchall()
    if not rows:
        print('radio_info: (empty)')
        return
    print('%-12s %3s %-12s %-8s %3s %3s %3s %19s %10s' % (
        'station', 'nr', 'radio_name', 'op', 'act', 'con', 'tx', 'last_update_utc', 'age_sec'))
    for r in rows:
        last_str = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(r[7]))
        print('%-12s %3d %-12s %-8s %3d %3d %3d %19s %10d' % (
            r[0] or '', r[1], (r[2] or ''), (r[3] or ''),
            r[4], r[5], r[6], last_str, r[8]))


def main():
    parser = argparse.ArgumentParser(description='Purge rows from radio_info.')
    parser.add_argument('--older-than', type=int, default=None,
                        help='delete rows older than N seconds (default: RADIO_HIDE_SECONDS)')
    parser.add_argument('--all', action='store_true',
                        help='delete every row in radio_info')
    parser.add_argument('--list', action='store_true',
                        help='list current rows and exit (no delete)')
    args = parser.parse_args()

    db = sqlite3.connect(config.DATABASE_FILENAME)
    try:
        cursor = db.cursor()
        if args.list:
            list_rows(cursor)
            return 0
        if args.all or args.older_than == 0:
            dataaccess.clear_radio_info(db, cursor)
            print('cleared all radio_info rows')
            return 0
        max_age = args.older_than if args.older_than is not None else config.RADIO_HIDE_SECONDS
        if max_age <= 0:
            print('RADIO_HIDE_SECONDS is 0/disabled and --older-than not set; '
                  'nothing to do. Use --all to wipe everything.', file=sys.stderr)
            return 1
        deleted = dataaccess.purge_stale_radio_info(db, cursor, max_age)
        print('purged %d row(s) older than %ds' % (deleted, max_age))
        return 0
    finally:
        db.close()


if __name__ == '__main__':
    sys.exit(main())
