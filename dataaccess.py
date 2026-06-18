# n1mm_view database access code

import calendar
from datetime import datetime
import logging
import time
import constants
from config import Config

__author__ = 'Jeffrey B. Otterson, N1KDO'
__copyright__ = 'Copyright 2016, 2019, 2020, Jeffrey B. Otterson'
__license__ = 'Simplified BSD'

config = Config()
logging.basicConfig(format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s', datefmt='%Y-%m-%d %H:%M:%S',
                    level=config.LOG_LEVEL)
logging.Formatter.converter = time.gmtime


def create_tables(db, cursor):
    """
    set up the database tables
    """
    cursor.execute('CREATE TABLE IF NOT EXISTS operator\n'
                   '    (id INTEGER PRIMARY KEY NOT NULL, \n'
                   '    name char(12) NOT NULL);')
    cursor.execute('CREATE INDEX IF NOT EXISTS operator_name ON operator(name);')

    cursor.execute('CREATE TABLE IF NOT EXISTS station\n'
                   '    (id INTEGER PRIMARY KEY NOT NULL, \n'
                   '    name char(12) NOT NULL);')
    cursor.execute('CREATE INDEX IF NOT EXISTS station_name ON station(name);')

    cursor.execute('CREATE TABLE IF NOT EXISTS qso_log\n'
                   # '    (id INTEGER PRIMARY KEY NOT NULL,\n'
                   '     (timestamp INTEGER NOT NULL,\n'
                   '     mycall char(12) NOT NULL,\n'
                   '     band_id INTEGER NOT NULL,\n'
                   '     mode_id INTEGER NOT NULL,\n'
                   '     operator_id INTEGER NOT NULL,\n'
                   '     station_id INTEGER NOT NULL,\n'
                   '     rx_freq INTEGER NOT NULL,\n'
                   '     tx_freq INTEGER NOT NULL,\n'
                   '     callsign char(12) NOT NULL,\n'
                   '     rst_sent char(3),\n'
                   '     rst_recv char(3),\n'
                   '     exchange char(4),\n'
                   '     section char(4),\n'
                   '     state char(4),\n'
                   '     comment TEXT,\n'
                   '     qso_id  char(32) PRIMARY KEY NOT NULL);')  # this is primary key to speed up Update & Delete

    # Migration: add state column to pre-existing databases. Must run before
    # the qso_log_state index is created, otherwise CREATE INDEX fails on
    # databases that predate the MULTS=STATES feature.
    try:
        cursor.execute('ALTER TABLE qso_log ADD COLUMN state char(4);')
        db.commit()
        logging.info('Added state column to qso_log table')
    except Exception:
        pass  # column already exists

    cursor.execute('CREATE INDEX IF NOT EXISTS qso_log_band_id ON qso_log(band_id);')
    cursor.execute('CREATE INDEX IF NOT EXISTS qso_log_mode_id ON qso_log(mode_id);')
    cursor.execute('CREATE INDEX IF NOT EXISTS qso_log_operator_id ON qso_log(operator_id);')
    cursor.execute('CREATE INDEX IF NOT EXISTS qso_log_station_id ON qso_log(station_id);')
    cursor.execute('CREATE INDEX IF NOT EXISTS qso_log_section ON qso_log(section);')
    cursor.execute('CREATE INDEX IF NOT EXISTS qso_log_state ON qso_log(state);')
    cursor.execute('CREATE INDEX IF NOT EXISTS qso_log_qso_id ON qso_log(qso_id);')
    cursor.execute('CREATE INDEX IF NOT EXISTS qso_log_qso_timestamp ON qso_log(timestamp);')

    cursor.execute('CREATE TABLE IF NOT EXISTS radio_info\n'
                   '    (station_name CHAR(32) NOT NULL,\n'
                   '     radio_nr     INTEGER NOT NULL,\n'
                   '     freq         INTEGER NOT NULL DEFAULT 0,\n'
                   '     tx_freq      INTEGER NOT NULL DEFAULT 0,\n'
                   '     mode         CHAR(12),\n'
                   '     op_call      CHAR(12),\n'
                   '     is_running   INTEGER NOT NULL DEFAULT 0,\n'
                   '     is_transmitting INTEGER NOT NULL DEFAULT 0,\n'
                   '     is_connected INTEGER NOT NULL DEFAULT 0,\n'
                   '     is_split     INTEGER NOT NULL DEFAULT 0,\n'
                   '     is_active    INTEGER NOT NULL DEFAULT 0,\n'
                   '     radio_name   CHAR(32),\n'
                   '     antenna      INTEGER,\n'
                   '     last_update  INTEGER NOT NULL,\n'
                   '     PRIMARY KEY (station_name, radio_nr));')

    # Migration: add is_active column to existing databases
    try:
        cursor.execute('ALTER TABLE radio_info ADD COLUMN is_active INTEGER NOT NULL DEFAULT 0;')
        db.commit()
        logging.info('Added is_active column to radio_info table')
    except Exception:
        pass  # column already exists

    db.commit()


def clear_radio_info(db, cursor):
    """
    Clear all radio info entries. Called on collector startup so only
    active radios from the current session are tracked.
    """
    try:
        cursor.execute('DELETE FROM radio_info;')
        db.commit()
        logging.info('Cleared radio_info table')
    except Exception as err:
        logging.warning('clear_radio_info failed: %s' % str(err))


def purge_stale_radio_info(db, cursor, max_age_seconds):
    """
    Delete radio_info rows whose last_update is older than max_age_seconds.
    Returns the number of rows deleted.
    """
    try:
        cursor.execute(
            'DELETE FROM radio_info WHERE last_update < (strftime(\'%s\',\'now\') - ?);',
            (int(max_age_seconds),))
        deleted = cursor.rowcount
        db.commit()
        logging.info('Purged %d stale radio_info row(s) older than %ds',
                     deleted, max_age_seconds)
        return deleted
    except Exception as err:
        logging.warning('purge_stale_radio_info failed: %s' % str(err))
        return 0


def record_radio_info(db, cursor, station_name, radio_nr, freq, tx_freq, mode, op_call,
                      is_running, is_transmitting, is_connected, is_split, is_active,
                      radio_name, antenna, last_update):
    """
    record or update radio info for a station/radio
    """
    try:
        cursor.execute(
            'INSERT OR REPLACE INTO radio_info\n'
            '    (station_name, radio_nr, freq, tx_freq, mode, op_call,\n'
            '     is_running, is_transmitting, is_connected, is_split, is_active,\n'
            '     radio_name, antenna, last_update)\n'
            '    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);',
            (station_name, radio_nr, freq, tx_freq, mode, op_call,
             is_running, is_transmitting, is_connected, is_split, is_active,
             radio_name, antenna, last_update))
        db.commit()
    except Exception as err:
        logging.warning('record_radio_info failed: %s' % str(err))


def get_radio_info(cursor):
    """
    return list of dicts with radio info, ordered by station_name, radio_nr
    """
    try:
        cursor.execute('SELECT station_name, radio_nr, freq, tx_freq, mode, op_call,\n'
                       '       is_running, is_transmitting, is_connected, is_split,\n'
                       '       is_active, radio_name, antenna, last_update\n'
                       'FROM radio_info ORDER BY station_name, radio_nr;')
        radios = []
        for row in cursor:
            radios.append({
                'station_name': row[0],
                'radio_nr': row[1],
                'freq': row[2],
                'tx_freq': row[3],
                'mode': row[4],
                'op_call': row[5],
                'is_running': row[6],
                'is_transmitting': row[7],
                'is_connected': row[8],
                'is_split': row[9],
                'is_active': row[10],
                'radio_name': row[11],
                'antenna': row[12],
                'last_update': row[13],
            })
        return radios
    except Exception:
        return []


def record_contact_combined(db, cursor, operators, stations,
                            timestamp, mycall, band, mode, operator, station,
                            rx_freq, tx_freq, callsign, rst_sent, rst_recv,
                            exchange, section, comment, qso_id, state=''):
    """
    record the results of a contact_message
    """
    band_id = constants.Bands.get_band_number(band)
    mode_id = constants.Modes.get_mode_number(mode)
    operator_id = operators.lookup_operator_id(operator)
    station_id = stations.lookup_station_id(station)

    logging.info(' QSO: %s %6s %4s %-6s %-12s %-12s %10d %10d %-6s %3s %3s %3s %-3s %-3s %32s' % (
        time.strftime('%Y-%m-%d %H:%M:%S', timestamp),
        mycall, band,
        mode, operator,
        station, rx_freq, tx_freq, callsign, rst_sent,
        rst_recv, exchange, section, comment, qso_id))

    if band_id is None or mode_id is None or operator_id is None or station_id is None:
        reasons = []
        if band_id is None: reasons.append(f'unknown band {band!r}')
        if mode_id is None: reasons.append(f'unknown mode {mode!r}')
        if operator_id is None: reasons.append(f'unknown operator {operator!r}')
        if station_id is None: reasons.append(f'unknown station {station!r}')
        logging.warning('cannot log QSO %s (call=%s): %s', qso_id, callsign, '; '.join(reasons))
        return
    try:
        cursor.execute(
            'insert or replace into qso_log \n'
            '    (timestamp, mycall, band_id, mode_id, operator_id, station_id , rx_freq, tx_freq, \n'
            '     callsign, rst_sent, rst_recv, exchange, section, state, comment, qso_id)\n'
            '    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);',
            (calendar.timegm(timestamp), mycall, band_id, mode_id, operator_id, station_id, rx_freq, tx_freq,
             callsign, rst_sent, rst_recv, exchange, section, state, comment, str(qso_id)))

        db.commit()
    except Exception as err:
        logging.warning('Insert Failed: %s\nError: %s' % (qso_id, str(err)))


def record_contact(db, cursor, operators, stations,
                   timestamp, mycall, band, mode, operator, station,
                   rx_freq, tx_freq, callsign, rst_sent, rst_recv,
                   exchange, section, comment, qso_id, state=''):
    """
    record the results of a contact_message
    """
    band_id = constants.Bands.get_band_number(band)
    mode_id = constants.Modes.get_mode_number(mode)
    operator_id = operators.lookup_operator_id(operator)
    station_id = stations.lookup_station_id(station)

    logging.info('QSO: %s %6s %4s %-6s %-12s %-12s %10d %10d %-6s %3s %3s %3s %-3s %-3s %32s' % (
        time.strftime('%Y-%m-%d %H:%M:%S', timestamp),
        mycall, band,
        mode, operator,
        station, rx_freq, tx_freq, callsign, rst_sent,
        rst_recv, exchange, section, comment, qso_id))

    if band_id is None or mode_id is None or operator_id is None or station_id is None:
        reasons = []
        if band_id is None: reasons.append(f'unknown band {band!r}')
        if mode_id is None: reasons.append(f'unknown mode {mode!r}')
        if operator_id is None: reasons.append(f'unknown operator {operator!r}')
        if station_id is None: reasons.append(f'unknown station {station!r}')
        logging.warning('cannot log QSO %s (call=%s): %s', qso_id, callsign, '; '.join(reasons))
        return
    try:
        cursor.execute(
            'insert into qso_log \n'
            '    (timestamp, mycall, band_id, mode_id, operator_id, station_id , rx_freq, tx_freq, \n'
            '     callsign, rst_sent, rst_recv, exchange, section, state, comment, qso_id)\n'
            '    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);',
            (calendar.timegm(timestamp), mycall, band_id, mode_id, operator_id, station_id, rx_freq, tx_freq,
             callsign, rst_sent, rst_recv, exchange, section, state, comment, qso_id))

        db.commit()
    except Exception as err:
        logging.warning('Insert Failed: %s\nError: %s' % (qso_id, str(err)))


def update_contact(db, cursor, operators, stations,
                   timestamp, mycall, band, mode, operator, station,
                   rx_freq, tx_freq, callsign, rst_sent, rst_recv,
                   exchange, section, comment, qso_id, state=''):
    """
    record the results of a contact_message
    """
    band_id = constants.Bands.get_band_number(band)
    mode_id = constants.Modes.get_mode_number(mode)
    operator_id = operators.lookup_operator_id(operator)
    station_id = stations.lookup_station_id(station)

    logging.info('Update QSO: %s %6s %4s %-6s %-12s %-12s %10d %10d %-6s %3s %3s %3s %-3s %-3s %32s' % (
        time.strftime('%Y-%m-%d %H:%M:%S', timestamp),
        mycall, band,
        mode, operator,
        station, rx_freq, tx_freq, callsign, rst_sent,
        rst_recv, exchange, section, comment, qso_id))

    if band_id is None or mode_id is None or operator_id is None or station_id is None:
        reasons = []
        if band_id is None: reasons.append(f'unknown band {band!r}')
        if mode_id is None: reasons.append(f'unknown mode {mode!r}')
        if operator_id is None: reasons.append(f'unknown operator {operator!r}')
        if station_id is None: reasons.append(f'unknown station {station!r}')
        logging.warning('cannot update QSO %s (call=%s): %s', qso_id, callsign, '; '.join(reasons))
        return
    try:
        cursor.execute(
            'update qso_log \n'
            '    set timestamp=?, mycall=?, band_id=?, mode_id=?, operator_id=?, station_id=? , rx_freq=?, tx_freq=?, \n'
            '     callsign=?, rst_sent=?, rst_recv=?, exchange=?, section=?, state=?, comment=? \n'
            ' where qso_id = ?;',
            (calendar.timegm(timestamp), mycall, band_id, mode_id, operator_id, station_id, rx_freq, tx_freq,
             callsign, rst_sent, rst_recv, exchange, section, state, comment, qso_id))

        db.commit()
    except Exception as err:
        logging.warning('Update Failed: %s\nError: %s' % (qso_id, str(err)))


def delete_contact(db, cursor, timestamp, station, callsign):
    """
    Delete the results of a delete in N1MM
    """

    """ station_id = stations.lookup_station_id(station)
"""

    logging.info('DELETEQSO: %s, timestamp = %s' % (callsign, calendar.timegm(timestamp)))
    try:
        cursor.execute(
            "delete from qso_log where callsign = ? and timestamp = ?", (callsign, calendar.timegm(timestamp),))
        db.commit()
    except Exception as e:
        logging.exception('Exception deleting contact from db.')
        return ''


def delete_contact_by_qso_id(db, cursor, qso_id):
    """
    Delete the results of a delete in N1MM
    """

    """ station_id = stations.lookup_station_id(station)
"""

    logging.debug('DELETEQSOByqso_id: %s' % (qso_id))
    try:
        cursor.execute('delete from qso_log where qso_id = ?;', (str(qso_id),))
        db.commit()
    except Exception as e:
        logging.exception('Exception deleting contact (by qso_id) from db.')
        return ''


def get_last_qso(cursor):
    cursor.execute('SELECT timestamp, callsign, exchange, section, operator.name, band_id \n'
                   'FROM qso_log JOIN operator WHERE operator.id = operator_id \n'
                   'ORDER BY timestamp DESC LIMIT 1')
    last_qso_time = int(time.time()) - 60
    message = ''
    for row in cursor:
        last_qso_time = row[0]
        message = 'Last QSO: %s %s %s on %s by %s at %s' % (
            row[1], row[2], row[3], constants.Bands.BANDS_TITLE[row[5]], row[4],
            datetime.utcfromtimestamp(row[0]).strftime('%H:%M:%S'))
        logging.debug('%s' % (message))

    return last_qso_time, message


def get_operators_by_qsos(cursor):
    logging.debug('Load QSOs by Operator')
    qso_operators = []
    cursor.execute('SELECT name, COUNT(operator_id) AS qso_count \n'
                   'FROM qso_log JOIN operator ON operator.id = operator_id \n'
                   'GROUP BY operator_id ORDER BY qso_count DESC;')
    for row in cursor:
        qso_operators.append((row[0], row[1]))
    return qso_operators


def get_station_qsos(cursor):
    logging.debug('Load QSOs by Station')
    qso_stations = []
    cursor.execute('SELECT name, COUNT(station_id) AS qso_count \n'
                   'FROM qso_log JOIN station ON station.id = station_id GROUP BY station_id;')
    for row in cursor:
        qso_stations.append((row[0], row[1]))
    return qso_stations


def get_qsos_per_hour_per_operator(cursor, last_qso_time):
    logging.debug('Load QSOs per Hour by Operator')
    slice_minutes = 15
    slices_per_hour = 60 / slice_minutes
    start_time = last_qso_time - slice_minutes * 60

    cursor.execute('SELECT operator.name, COUNT(operator_id) qso_count FROM qso_log\n'
                   'JOIN operator ON operator.id = operator_id\n'
                   'WHERE timestamp >= ? AND timestamp <= ?\n'
                   'GROUP BY operator_id ORDER BY qso_count DESC LIMIT 10;', (start_time, last_qso_time))
    operator_qso_rates = [['Operator', 'Rate']]
    total = 0
    for row in cursor:
        rate = row[1] * slices_per_hour
        total += rate
        operator_qso_rates.append([row[0], '%4d' % rate])
    operator_qso_rates.append(['Total', '%4d' % total])
    return operator_qso_rates


def get_qso_band_modes(cursor):
    qso_band_modes = [[0] * 4 for _ in constants.Bands.BANDS_LIST]

    cursor.execute('SELECT COUNT(*), band_id, mode_id FROM qso_log GROUP BY band_id, mode_id;')
    for row in cursor:
        qso_band_modes[row[1]][constants.Modes.MODE_TO_SIMPLE_MODE[row[2]]] += row[0]
    return qso_band_modes


def get_qso_classes(cursor):
    cursor.execute('SELECT COUNT(*), exchange FROM qso_log group by exchange;')
    exchanges = []
    for row in cursor:
        exchanges.append((row[0], row[1]))
    return exchanges


def get_qso_categories(cursor):
    cursor.execute("SELECT exchange FROM qso_log;")
    counts = {}
    for (exchange,) in cursor:
        cls = ''
        if exchange:
            token = exchange.split()[0]  # e.g. "1D" from "1D EPA"
            if token and token[-1].isalpha():
                cls = token[-1].upper()
        # Validate against known Field Day classes; bucket anything else into
        # a visible '?' slice rather than inventing a phantom category.
        key = cls if cls in constants.CATEGORY_NAMES else '?'
        counts[key] = counts.get(key, 0) + 1
    return [(count, key) for key, count in counts.items()]


def get_qsos_per_hour_per_band(cursor):
    qsos_per_hour = []
    qsos_by_band = [0] * constants.Bands.count()
    slice_minutes = 15
    slice_minutes = 12  # TODO FIXME was 15, 12 looks pretty ok
    slices_per_hour = 60 / slice_minutes
    window_seconds = slice_minutes * 60

    logging.debug('Load QSOs per Hour by Band')
    cursor.execute('SELECT timestamp / %d * %d AS ts, band_id, COUNT(*) AS qso_count \n'
                   'FROM qso_log GROUP BY ts, band_id;' % (window_seconds, window_seconds))
    for row in cursor:
        if len(qsos_per_hour) == 0:
            qsos_per_hour.append([0] * constants.Bands.count())
            qsos_per_hour[-1][0] = row[0]
        while qsos_per_hour[-1][0] != row[0]:
            ts = qsos_per_hour[-1][0] + window_seconds
            qsos_per_hour.append([0] * constants.Bands.count())
            qsos_per_hour[-1][0] = ts
        qsos_per_hour[-1][row[1]] = row[2] * slices_per_hour
        qsos_by_band[row[1]] += row[2]

    for rec in qsos_per_hour:
        rec[0] = datetime.utcfromtimestamp(rec[0])
        # t = rec[0].strftime('%H:%M:%S')

    return qsos_per_hour, qsos_by_band


def get_qsos_by_section(cursor):
    logging.debug('Load QSOs by Section')
    qsos_by_section = {}
    cursor.execute('SELECT section, COUNT(section) AS qsos FROM qso_log GROUP BY section;')
    for row in cursor:
        qsos_by_section[row[0]] = row[1]
        logging.debug(f'Section {row[0]} {row[1]}')
    return qsos_by_section


def get_qsos_by_state(cursor):
    logging.debug('Load QSOs by State')
    qsos_by_state = {}
    cursor.execute('SELECT state, COUNT(state) AS qsos FROM qso_log WHERE state != \'\' GROUP BY state;')
    for row in cursor:
        qsos_by_state[row[0]] = row[1]
        logging.debug(f'State {row[0]} {row[1]}')
    return qsos_by_state


def get_operator_first_qsos(cursor):
    """
    For each operator that has logged at least one QSO in THIS event's DB,
    return their earliest QSO: (op_name, first_ts, callsign_worked, band_id,
    mode_id). Used by the new-operator race-curve and roster.
    """
    cursor.execute(
        'SELECT operator.name, MIN(timestamp) AS first_ts, band_id, mode_id, callsign\n'
        'FROM qso_log JOIN operator ON operator.id = operator_id\n'
        'GROUP BY operator_id;')
    rows = []
    # MIN(timestamp) gives the timestamp but band_id/mode_id/callsign on the
    # same row are NOT guaranteed to be from the min row in standard SQL.
    # SQLite happens to return values from the min row when using MIN() this
    # way (the "bare columns" optimization), but rely on a fresh lookup for
    # correctness.
    for row in cursor.fetchall():
        rows.append({'name': row[0], 'first_ts': row[1]})
    # Second pass: pull band/mode/callsign for the actual min-ts QSO per op.
    for r in rows:
        cursor.execute(
            'SELECT band_id, mode_id, callsign FROM qso_log\n'
            'JOIN operator ON operator.id = operator_id\n'
            'WHERE operator.name = ? AND timestamp = ?\n'
            'LIMIT 1;', (r['name'], r['first_ts']))
        row = cursor.fetchone()
        if row:
            r['band_id'] = row[0]
            r['mode_id'] = row[1]
            r['worked'] = row[2]
        else:
            r['band_id'] = 0
            r['mode_id'] = 0
            r['worked'] = ''
    rows.sort(key=lambda r: r['first_ts'])
    return rows


_ADIF_OP_RE = None
_ADIF_CACHE = {}  # path -> (mtime, set_of_names)


def _adif_operators(adif_path):
    """Parse ADIF, return lowercased set of <OPERATOR> field values. Cached
    by mtime so successive renders skip re-parsing unchanged files."""
    import os as _os
    import re as _re
    global _ADIF_OP_RE
    if _ADIF_OP_RE is None:
        # ADIF fields are <NAME:LEN[:TYPE]>VALUE with VALUE exactly LEN bytes.
        # Match OPERATOR case-insensitively.
        _ADIF_OP_RE = _re.compile(rb'<\s*OPERATOR\s*:\s*(\d+)(?:\s*:\s*[A-Za-z])?\s*>',
                                  _re.IGNORECASE)
    try:
        mtime = _os.path.getmtime(adif_path)
    except OSError:
        return set()
    cached = _ADIF_CACHE.get(adif_path)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with open(adif_path, 'rb') as fh:
            data = fh.read()
    except OSError as err:
        logging.warning('cannot read ADIF %s: %s', adif_path, err)
        return set()
    import re as _re2
    # Strip any leading/trailing characters that aren't valid in a callsign,
    # which handles malformed ADIFs that embed stray punctuation (e.g. TR4W's
    # `<OPERATOR:6>]N4FOY` should match a clean `N4FOY` from another year).
    _callsign_trim = _re2.compile(r'^[^A-Za-z0-9]+|[^A-Za-z0-9/]+$')
    names = set()
    for m in _ADIF_OP_RE.finditer(data):
        length = int(m.group(1))
        start = m.end()
        value = data[start:start + length].decode('ascii', errors='ignore').strip()
        value = _callsign_trim.sub('', value).lower()
        if value:
            names.add(value)
    _ADIF_CACHE[adif_path] = (mtime, names)
    logging.info('ADIF %s: %d distinct operator(s)', adif_path, len(names))
    return names


def get_prior_operators_from_consolidated_db(prior_ops_db_path):
    """Return the set of lowercased operator names from the consolidated
    prior_operators.db (schema: operator(name TEXT, event_label TEXT)).
    Empty set on any error (missing file, wrong schema)."""
    import os as _os
    import sqlite3 as _sqlite3
    if not prior_ops_db_path or not _os.path.isfile(prior_ops_db_path):
        return set()
    try:
        pdb = _sqlite3.connect(prior_ops_db_path)
        try:
            pcur = pdb.cursor()
            pcur.execute('SELECT DISTINCT name FROM operator;')
            return {(row[0] or '').strip().lower() for row in pcur.fetchall() if row[0]}
        finally:
            pdb.close()
    except _sqlite3.Error as err:
        logging.warning('get_prior_operators_from_consolidated_db failed for %s: %s',
                        prior_ops_db_path, err)
        return set()


def get_yoy_new_op_counts(prior_ops_db_path, event_label_regex=None):
    """
    Return [(event_label, event_year, total_ops, new_ops), ...] sorted by
    event_year ASC. "new_ops" for event E = operators in E who never appeared
    in any event with an earlier event_year. event_label_regex is an optional
    re.compile()-style pattern (case-insensitive) to filter event labels.
    Empty list on any error.
    """
    import os as _os
    import re as _re
    import sqlite3 as _sqlite3
    if not prior_ops_db_path or not _os.path.isfile(prior_ops_db_path):
        return []
    try:
        pdb = _sqlite3.connect(prior_ops_db_path)
        try:
            pcur = pdb.cursor()
            pcur.execute(
                'SELECT label, event_year, op_count FROM event '
                'WHERE event_year IS NOT NULL ORDER BY event_year ASC, label ASC;')
            events = list(pcur.fetchall())
            if event_label_regex:
                pat = _re.compile(event_label_regex, _re.IGNORECASE)
                events = [e for e in events if pat.search(e[0] or '')]
            out = []
            seen = set()  # names seen in any strictly-earlier-year event we kept
            current_year = None
            year_buffer = []  # rows being processed at current_year
            for label, year, op_count in events:
                if year != current_year:
                    # flush year_buffer first
                    if year_buffer:
                        names_added_this_year = set()
                        for blabel, byear, bcount in year_buffer:
                            pcur.execute(
                                'SELECT name FROM operator WHERE event_label = ?;',
                                (blabel,))
                            ev_names = {row[0].strip().lower() for row in pcur.fetchall()}
                            new = sorted(ev_names - seen)
                            out.append((blabel, byear, len(ev_names), len(new)))
                            names_added_this_year |= ev_names
                        seen |= names_added_this_year
                        year_buffer = []
                    current_year = year
                year_buffer.append((label, year, op_count))
            # flush trailing year
            if year_buffer:
                names_added_this_year = set()
                for blabel, byear, bcount in year_buffer:
                    pcur.execute(
                        'SELECT name FROM operator WHERE event_label = ?;',
                        (blabel,))
                    ev_names = {row[0].strip().lower() for row in pcur.fetchall()}
                    new = sorted(ev_names - seen)
                    out.append((blabel, byear, len(ev_names), len(new)))
                    names_added_this_year |= ev_names
                seen |= names_added_this_year
            return out
        finally:
            pdb.close()
    except _sqlite3.Error as err:
        logging.warning('get_yoy_new_op_counts failed for %s: %s',
                        prior_ops_db_path, err)
        return []


def get_prior_operators_from_adif_dir(adif_dir):
    """Union the OPERATOR fields from every *.adi / *.adif file in adif_dir.
    Returns an empty set on any error (missing dir, unreadable files)."""
    import os as _os
    if not adif_dir or not _os.path.isdir(adif_dir):
        return set()
    names = set()
    try:
        for entry in sorted(_os.listdir(adif_dir)):
            ext = entry.rsplit('.', 1)[-1].lower() if '.' in entry else ''
            if ext not in ('adi', 'adif'):
                continue
            names |= _adif_operators(_os.path.join(adif_dir, entry))
    except OSError as err:
        logging.warning('cannot scan ADIF dir %s: %s', adif_dir, err)
    return names


def get_prior_operator_names(prior_db_path):
    """
    Return a set of lowercased operator names from PRIOR_DB_FILENAME's
    operator table, plus the prior event's (min_ts, max_ts) from its
    qso_log. On any error (missing file, bad schema) returns (set(), None, None)
    so the caller can carry on with no comparison.
    """
    import os as _os
    import sqlite3 as _sqlite3
    if not prior_db_path or not _os.path.isfile(prior_db_path):
        return set(), None, None
    try:
        pdb = _sqlite3.connect(prior_db_path)
        try:
            pcur = pdb.cursor()
            pcur.execute('SELECT name FROM operator;')
            names = {(row[0] or '').strip().lower() for row in pcur.fetchall() if row[0]}
            pcur.execute('SELECT MIN(timestamp), MAX(timestamp) FROM qso_log;')
            row = pcur.fetchone()
            min_ts, max_ts = (row[0], row[1]) if row else (None, None)
            return names, min_ts, max_ts
        finally:
            pdb.close()
    except Exception as err:
        logging.warning('get_prior_operator_names failed for %s: %s', prior_db_path, err)
        return set(), None, None


def get_prior_first_qso_curve(prior_db_path):
    """
    For the prior event, return a sorted list of (offset_seconds_from_event_start,
    cumulative_distinct_operators). offset_seconds_from_event_start is computed
    relative to the prior event's MIN(timestamp), so it can be overlaid on the
    current event's elapsed timeline. Returns [] on any error.
    """
    import os as _os
    import sqlite3 as _sqlite3
    if not prior_db_path or not _os.path.isfile(prior_db_path):
        return []
    try:
        pdb = _sqlite3.connect(prior_db_path)
        try:
            pcur = pdb.cursor()
            pcur.execute(
                'SELECT operator.name, MIN(timestamp) AS first_ts\n'
                'FROM qso_log JOIN operator ON operator.id = operator_id\n'
                'GROUP BY operator_id ORDER BY first_ts ASC;')
            first_ts_list = [row[1] for row in pcur.fetchall() if row[1] is not None]
            if not first_ts_list:
                return []
            event_start = first_ts_list[0]
            return [(ts - event_start, idx + 1) for idx, ts in enumerate(first_ts_list)]
        finally:
            pdb.close()
    except Exception as err:
        logging.warning('get_prior_first_qso_curve failed for %s: %s', prior_db_path, err)
        return []


def get_last_N_qsos(cursor, nQSOCount):
    logging.info('get_last_N_qsos for last %d QSOs' % (nQSOCount))
    qsos = []
    cursor.execute(
        'SELECT qso_id, timestamp, callsign, band_id, mode_id, operator.name, rx_freq, tx_freq, exchange, section, station.name \n'
        'FROM qso_log '
        'JOIN operator ON operator.id = operator_id\n'
        'JOIN station ON station.id = station_id\n'
        'ORDER BY timestamp DESC LIMIT %d;' % (nQSOCount))
    for row in cursor:
        qsos.append((row[1]  # raw timestamp 0
                         , row[2]  # call 1
                         , constants.Bands.BANDS_TITLE[row[3]]  # band 2
                         , constants.Modes.SIMPLE_MODES_LIST[constants.Modes.MODE_TO_SIMPLE_MODE[row[4]]]  # mode 3
                         , row[5]  # operator callsign 4
                         , row[8]  # exchange 5
                         , row[9]  # section 6
                         , row[10]  # station name 7
                     ))
        message = 'QSO: time=%sZ call=%s exchange=%s %s mode=%s band=%s operator=%s station=%s' % (
            datetime.utcfromtimestamp(row[1]).strftime('%Y %b %d %H:%M:%S')
            , row[2]  # callsign
            , row[8]  # exchange
            , row[9]  # section
            , constants.Modes.SIMPLE_MODES_LIST[constants.Modes.MODE_TO_SIMPLE_MODE[row[4]]]
            , constants.Bands.BANDS_TITLE[row[3]]
            , row[5]  # operator
            , row[10]  # station
        )
        logging.info('%s' % (message))
    return qsos
