#!/usr/bin/python3
"""
import_prior_operators.py

Build / refresh the consolidated prior-operators database used by the
"new operator" feature in n1mm_view. Reads operator callsigns from:

  - Every *.adi / *.adif file in [NEW_OPERATORS] PRIOR_ADIF_DIR
  - Every n1mm_view.*.db file in the CWD (except DATABASE_FILENAME, which is
    the live event), unless --no-auto-db is passed
  - Any additional .db / .adi paths passed on the command line
  - [NEW_OPERATORS] PRIOR_DB_FILENAME if it points to a readable file

Schema preserves per-event structure so the YOY (new-ops-per-year) chart in
the sidebar can be computed from this same DB:

    CREATE TABLE event (
        label       TEXT PRIMARY KEY NOT NULL,  -- '2019 ARRL FD' etc.
        event_year  INTEGER,                    -- pulled from filename or QSO data
        source_path TEXT,                       -- absolute path of source file
        op_count    INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE operator (
        name        TEXT NOT NULL,              -- lowercased callsign
        event_label TEXT NOT NULL,
        PRIMARY KEY(name, event_label)
    );

Re-running is idempotent: existing rows are preserved, new (name, event) pairs
get inserted. The script does NOT delete operators that are no longer in any
source — use `--reset` to wipe the DB and re-import from scratch.

Usage:
    python3 import_prior_operators.py                 # use config defaults
    python3 import_prior_operators.py --out my.db     # write elsewhere
    python3 import_prior_operators.py extra.db        # add ad-hoc sources
    python3 import_prior_operators.py --dry-run       # preview, no writes
    python3 import_prior_operators.py --reset         # rebuild from scratch
"""

import argparse
import glob
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

import dataaccess
from config import Config

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)-7s %(message)s')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS event (
    label       TEXT PRIMARY KEY NOT NULL,
    event_year  INTEGER,
    source_path TEXT,
    op_count    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS operator (
    name        TEXT NOT NULL,
    event_label TEXT NOT NULL,
    PRIMARY KEY(name, event_label)
);
CREATE INDEX IF NOT EXISTS idx_operator_name ON operator(name);
CREATE INDEX IF NOT EXISTS idx_event_year ON event(event_year);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
'''

# Match a 4-digit year anywhere in the filename. Filenames like
# "2019 ARRL-FD 2.ADI" -> 2019; "n1mm_view.2025WFD.db" -> 2025.
_YEAR_RE = re.compile(r'(19|20)(\d{2})')


def _label_for_path(path):
    """Turn a file path into a human-readable source label."""
    base = os.path.basename(path)
    for prefix in ('n1mm_view.',):
        if base.startswith(prefix):
            base = base[len(prefix):]
    for suffix in ('.db', '.s3db', '.adi', '.adif', '.ADI', '.ADIF'):
        if base.endswith(suffix):
            base = base[:-len(suffix)]
    return (base or os.path.basename(path)).strip()


def _year_from_filename(path):
    m = _YEAR_RE.search(os.path.basename(path))
    if m:
        return int(m.group(0))
    return None


def _year_from_adif(path):
    """Scan an ADIF for the earliest QSO_DATE field. Returns int year or None."""
    try:
        with open(path, 'rb') as fh:
            data = fh.read(200_000)  # first 200KB is plenty for header + first records
    except OSError:
        return None
    m = re.search(rb'<\s*QSO_DATE\s*:\s*(\d+)(?:\s*:\s*[A-Za-z])?\s*>', data,
                  re.IGNORECASE)
    if not m:
        return None
    length = int(m.group(1))
    raw = data[m.end():m.end() + length].decode('ascii', errors='ignore')
    if len(raw) >= 4 and raw[:4].isdigit():
        return int(raw[:4])
    return None


def _year_from_n1mm_db(path):
    try:
        db = sqlite3.connect(path)
        try:
            cursor = db.cursor()
            cursor.execute('SELECT MIN(timestamp) FROM qso_log;')
            row = cursor.fetchone()
        finally:
            db.close()
        if row and row[0]:
            return datetime.fromtimestamp(int(row[0]), tz=timezone.utc).year
    except sqlite3.Error:
        pass
    return None


def _collect_from_adif(path):
    names = dataaccess._adif_operators(path)
    year = _year_from_filename(path) or _year_from_adif(path)
    return names, year


def _collect_from_n1mm_db(path):
    out = set()
    try:
        db = sqlite3.connect(path)
        try:
            cursor = db.cursor()
            cursor.execute('SELECT name FROM operator;')
            for row in cursor.fetchall():
                name = (row[0] or '').strip().lower()
                if name:
                    out.add(name)
        finally:
            db.close()
    except sqlite3.Error as err:
        logging.warning('skipping %s: %s', path, err)
    year = _year_from_n1mm_db(path) or _year_from_filename(path)
    return out, year


def _auto_discover_dbs(skip):
    skip_abs = {os.path.abspath(p) for p in skip if p}
    out = []
    for path in sorted(glob.glob('n1mm_view.*.db')):
        ap = os.path.abspath(path)
        if ap in skip_abs:
            continue
        if path == 'n1mm_view.db':
            continue
        if os.path.getsize(path) == 0:
            continue
        out.append(path)
    return out


def main():
    config = Config()

    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('extra', nargs='*', help='Additional .db or .adi/.adif paths')
    parser.add_argument('--out', default=None,
                        help='Output SQLite path (default: PRIOR_OPERATORS_DB '
                             'from INI, or prior_operators.db)')
    parser.add_argument('--adif-dir', default=None,
                        help='Directory of ADIFs (default: PRIOR_ADIF_DIR from INI)')
    parser.add_argument('--no-auto-db', action='store_true',
                        help='Skip auto-discovery of n1mm_view.*.db files in CWD')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be imported, do not write the DB')
    parser.add_argument('--reset', action='store_true',
                        help='Drop and rebuild the prior_operators schema before import')
    args = parser.parse_args()

    out_path = (args.out
                or getattr(config, 'PRIOR_OPERATORS_DB', '')
                or 'prior_operators.db')
    adif_dir = (args.adif_dir
                if args.adif_dir is not None
                else getattr(config, 'PRIOR_ADIF_DIR', ''))

    sources = []
    if adif_dir and os.path.isdir(adif_dir):
        for entry in sorted(os.listdir(adif_dir)):
            ext = entry.rsplit('.', 1)[-1].lower() if '.' in entry else ''
            if ext in ('adi', 'adif'):
                sources.append(('adif', os.path.join(adif_dir, entry)))

    if not args.no_auto_db:
        for path in _auto_discover_dbs(skip=[config.DATABASE_FILENAME, out_path]):
            sources.append(('db', path))

    prior_db = getattr(config, 'PRIOR_DB_FILENAME', '')
    if prior_db and os.path.isfile(prior_db):
        prior_abs = os.path.abspath(prior_db)
        already = {os.path.abspath(p) for _, p in sources}
        if prior_abs not in already:
            sources.append(('db', prior_db))

    for extra in args.extra:
        if not os.path.exists(extra):
            logging.warning('skipping arg %s (does not exist)', extra)
            continue
        ext = extra.rsplit('.', 1)[-1].lower() if '.' in extra else ''
        if ext in ('adi', 'adif'):
            sources.append(('adif', extra))
        else:
            sources.append(('db', extra))

    if not sources:
        logging.error('no sources to import (PRIOR_ADIF_DIR empty, no '
                      'n1mm_view.*.db files found, and no extras given)')
        return 1

    # Collect per-source data.
    events = []  # list of dicts: {label, year, source_path, names}
    for kind, path in sources:
        if kind == 'adif':
            names, year = _collect_from_adif(path)
        else:
            names, year = _collect_from_n1mm_db(path)
        label = _label_for_path(path)
        events.append({
            'label': label,
            'year': year,
            'source_path': os.path.abspath(path),
            'kind': kind,
            'names': names,
        })
        logging.info('%s [%s, year=%s]: %d operator(s)',
                     label, kind, year, len(names))

    if args.dry_run:
        print('=' * 60)
        print('DRY RUN — would write %d events to %s' % (len(events), out_path))
        print('=' * 60)
        events_sorted = sorted(events, key=lambda e: (e['year'] or 0, e['label']))
        seen_so_far = set()
        for ev in events_sorted:
            new_in_year = sorted(ev['names'] - seen_so_far)
            seen_so_far |= ev['names']
            print('\n[%s] year=%s  ops=%d  new=%d' %
                  (ev['label'], ev['year'], len(ev['names']), len(new_in_year)))
            if new_in_year:
                print('  new: ' + ', '.join(new_in_year))
        return 0

    db = sqlite3.connect(out_path)
    try:
        cursor = db.cursor()
        if args.reset:
            cursor.executescript(
                'DROP TABLE IF EXISTS operator;'
                'DROP TABLE IF EXISTS event;'
                'DROP TABLE IF EXISTS meta;'
            )
        cursor.executescript(SCHEMA)

        for ev in events:
            cursor.execute(
                'INSERT INTO event(label, event_year, source_path, op_count) '
                'VALUES (?, ?, ?, ?) '
                'ON CONFLICT(label) DO UPDATE SET '
                '  event_year = COALESCE(excluded.event_year, event.event_year), '
                '  source_path = excluded.source_path, '
                '  op_count = excluded.op_count;',
                (ev['label'], ev['year'], ev['source_path'], len(ev['names'])))
            for name in ev['names']:
                cursor.execute(
                    'INSERT OR IGNORE INTO operator(name, event_label) VALUES (?, ?);',
                    (name, ev['label']))

        now_iso = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        cursor.execute(
            'INSERT INTO meta(key, value) VALUES (?, ?) '
            'ON CONFLICT(key) DO UPDATE SET value = excluded.value;',
            ('last_import', now_iso))
        db.commit()

        total_ops = cursor.execute(
            'SELECT COUNT(DISTINCT name) FROM operator;').fetchone()[0]
        total_events = cursor.execute(
            'SELECT COUNT(*) FROM event;').fetchone()[0]
        logging.info('Wrote %s: %d distinct operators across %d events',
                     out_path, total_ops, total_events)
    finally:
        db.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
