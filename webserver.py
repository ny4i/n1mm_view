#!/usr/bin/python3
"""
n1mm_view_webserver

Lightweight Flask app that serves the IMAGE_DIR produced by headless.py and
exposes a JSON endpoint with the current radio_info table for near-realtime
sidebar updates in the browser. Designed to run on the same Pi as the
collector so the browser sees the same DB the collector is writing to.

Routes:
    GET  /                          -> IMAGE_DIR/index.html
    GET  /<path>                    -> static file from IMAGE_DIR
    GET  /api/radio                 -> JSON list of radio_info rows
    GET  /api/health                -> {"ok": true, ...}
    GET  /admin                     -> status + admin actions page
    POST /admin/action/purge-stale  -> purge radio_info older than RADIO_HIDE_SECONDS
    POST /admin/action/clear-all    -> wipe radio_info table
    POST /admin/action/regenerate-index -> rewrite IMAGE_DIR/index.html

The rsync workflow (POST_FILE_COMMAND in [HEADLESS INFO]) is unaffected.
Remote copies that don't have this server still get the radio_info.png
sidebar; the index.html falls back to the PNG when /api/radio is unreachable.
"""

import base64
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone

from flask import Flask, Response, jsonify, redirect, render_template_string, request, send_from_directory, abort

from config import Config, VERSION
import constants
import dataaccess

__author__ = 'Tom Schaefer NY4I'
__copyright__ = 'Copyright 2026 Thomas M. Schaefer'
__license__ = 'Simplified BSD'

config = Config()
logger = logging.getLogger(__name__)

# Werkzeug logs every HTTP request at INFO -- per-request access-log spam during
# normal operation. Treat it as DEBUG-level detail: show it only when running at
# DEBUG, otherwise keep just 4xx/5xx (warnings/errors).
logging.getLogger('werkzeug').setLevel(
    logging.INFO if logging.getLogger().getEffectiveLevel() <= logging.DEBUG
    else logging.WARNING)

app = Flask(__name__)

SERVICES = [
    'n1mm_view_collector',
    'n1mm_view_headless',
    'n1mm_view_dashboard',
    'n1mm_view_webserver',
]

# A radio whose last_update is older than this is considered stale: the
# dashboard greys it out and it no longer participates in duplicate detection.
# Matches the 60s dim threshold used by headless.py and graphics.draw_radio_info.
STALE_SECONDS = 60

CONFIG_KEYS = [
    'DATABASE_FILENAME', 'IMAGE_DIR', 'EVENT_NAME',
    'EVENT_START_TIME', 'EVENT_END_TIME',
    'MULTS', 'DISPLAY_DWELL_TIME', 'DATA_DWELL_TIME', 'HEADLESS_DWELL_TIME',
    'N1MM_BROADCAST_PORT',
    'WEBSERVER_ENABLED', 'WEBSERVER_BIND', 'WEBSERVER_PORT',
    'RADIO_POLL_SECONDS', 'RADIO_HIDE_SECONDS',
    'SHOW_RADIO_INFO', 'SHOW_RADIO_SIDEBAR',
    'SHOW_MULT_PROGRESS', 'SHOW_MULT_REMAINING', 'SHOW_MULT_ALERT',
    'SHOW_OPERATOR_LEADERBOARD',
    'SHOW_NEW_OPS_RACE', 'SHOW_NEW_OPS_ROSTER', 'SHOW_NEW_OPS_YOY',
    'PRIOR_DB_FILENAME', 'PRIOR_EVENT_LABEL',
    'PRIOR_OPERATORS_DB', 'PRIOR_ADIF_DIR', 'YOY_EVENT_REGEX',
    'POST_FILE_COMMAND',
]


def _query_radio_info():
    db = sqlite3.connect(config.DATABASE_FILENAME)
    try:
        cursor = db.cursor()
        return dataaccess.get_radio_info(cursor)
    finally:
        db.close()


def _annotate_radios(radios):
    """Add band, mode_group, source and a duplicate band/mode flag to each radio.

    Two or more radios sharing the same band + simple mode group (CW/PHONE/DATA)
    are flagged dup=True so the dashboard can alert -- at Field Day that means two
    transmitters in one category (a rule violation), and it also surfaces a
    station-name collision.
    """
    now = int(time.time())
    for r in radios:
        r['band'] = constants.Bands.freq_to_band(r.get('freq'))
        r['mode_group'] = constants.Modes.get_simple_mode_name(r.get('mode') or '')
        r['source'] = r.get('source') or 'radioinfo'
        # Out of band: outside every ham band, or PHONE below the phone sub-band
        # edge. Flag it so it's obvious (it's also excluded from dup matching).
        r['offband'] = constants.Bands.is_out_of_band(r.get('freq'), r['mode_group'])
    # Only live (non-stale) radios participate in collision detection. Stale rows
    # are the greyed-out leftovers of stations that have gone away; counting them
    # would falsely flag a live radio as a DUP of an old, idle one. Use the same
    # 60s staleness window the renderer uses to grey a row out.
    def _live(r):
        return (now - (r.get('last_update') or now)) <= STALE_SECONDS
    counts = {}
    for r in radios:
        if _live(r) and r['band'] and r['mode_group'] not in (None, 'N/A'):
            counts[(r['band'], r['mode_group'])] = counts.get((r['band'], r['mode_group']), 0) + 1
    for r in radios:
        key = (r['band'], r['mode_group'])
        r['dup'] = bool(_live(r) and r['band'] and r['mode_group'] not in (None, 'N/A')
                        and counts.get(key, 0) > 1)
    return radios


@app.route('/api/radio')
def api_radio():
    radios = _query_radio_info()
    now = int(time.time())
    hide = getattr(config, 'RADIO_HIDE_SECONDS', 0)
    if hide and hide > 0:
        radios = [r for r in radios if (now - r['last_update']) <= hide]
    radios = _annotate_radios(radios)
    return jsonify({
        'server_time': now,
        'radios': radios,
    })


@app.route('/api/new_ops')
def api_new_ops():
    """
    Return this event's operators flagged as "new" (name not in
    PRIOR_DB_FILENAME's operator table), plus a summary count and the
    prior event's total operator count. Each new-op entry includes the
    timestamp/band/mode/callsign of their first event QSO.
    """
    import constants
    db = sqlite3.connect(config.DATABASE_FILENAME)
    try:
        cursor = db.cursor()
        cur_first = dataaccess.get_operator_first_qsos(cursor)
    finally:
        db.close()
    prior_names = dataaccess.get_prior_operators_from_consolidated_db(
        getattr(config, 'PRIOR_OPERATORS_DB', ''))
    # "Last event" count for the sidebar is PRIOR_DB_FILENAME only (the chosen
    # reference event), NOT the union across every imported prior year.
    last_event_names, _, _ = dataaccess.get_prior_operator_names(config.PRIOR_DB_FILENAME)
    if not prior_names:
        prior_names = last_event_names
    new_ops = []
    for r in cur_first:
        if r['name'].strip().lower() in prior_names:
            continue
        bid = r.get('band_id') or 0
        mid = r.get('mode_id') or 0
        band = (constants.Bands.BANDS_TITLE[bid]
                if 0 <= bid < constants.Bands.count() else '')
        mode = (constants.Modes.SIMPLE_MODES_LIST[constants.Modes.MODE_TO_SIMPLE_MODE[mid]]
                if 0 <= mid < len(constants.Modes.MODE_TO_SIMPLE_MODE) else '')
        new_ops.append({
            'name': r['name'],
            'first_ts': r['first_ts'],
            'band': band,
            'mode': mode,
            'worked': r.get('worked') or '',
        })
    # prior_new = the prior reference event's *new*-operator count (year-over-year),
    # so "N new this event" compares against new-vs-new (e.g. 2025 FD had 7 new,
    # not its 25 total). Pulled from the same YoY computation the chart uses.
    prior_new = None
    try:
        yoy = dataaccess.get_yoy_new_op_counts(
            getattr(config, 'PRIOR_OPERATORS_DB', ''),
            event_label_regex=getattr(config, 'YOY_EVENT_REGEX', None))
        if yoy:
            prior_new = yoy[-1][3]  # most recent prior event's new_ops
    except Exception:
        prior_new = None
    return jsonify({
        'server_time': int(time.time()),
        'event_name': config.EVENT_NAME,
        'prior_event_label': getattr(config, 'PRIOR_EVENT_LABEL', ''),
        # prior_total = last reference event's TOTAL ops (e.g. 2025 FD = 25);
        # prior_new   = that event's NEW ops year-over-year (e.g. 7);
        # all_prior_total = union across every imported prior event (e.g. 75).
        'prior_total': len(last_event_names) if last_event_names else None,
        'prior_new': prior_new,
        'all_prior_total': len(prior_names) if prior_names else None,
        'total_ops': len(cur_first),
        'total_new': len(new_ops),
        'new_ops': new_ops,
    })


@app.route('/api/last_qso')
def api_last_qso():
    """Return the most recent QSO (callsign, band, mode, operator, etc.) so
    the dashboard header can show it without waiting for headless to re-render."""
    import constants
    db = sqlite3.connect(config.DATABASE_FILENAME)
    try:
        cursor = db.cursor()
        ts, message = dataaccess.get_last_qso(cursor)
        cursor.execute(
            'SELECT timestamp, callsign, exchange, section, operator.name, '
            '       band_id, mode_id, station.name '
            'FROM qso_log JOIN operator ON operator.id = operator_id '
            'JOIN station ON station.id = station_id '
            'ORDER BY timestamp DESC LIMIT 1;')
        row = cursor.fetchone()
    finally:
        db.close()
    if not row:
        return jsonify({'server_time': int(time.time()), 'last_qso': None})
    band = (constants.Bands.BANDS_TITLE[row[5]]
            if 0 <= row[5] < constants.Bands.count() else '')
    mode = (constants.Modes.SIMPLE_MODES_LIST[constants.Modes.MODE_TO_SIMPLE_MODE[row[6]]]
            if 0 <= row[6] < len(constants.Modes.MODE_TO_SIMPLE_MODE) else '')
    return jsonify({
        'server_time': int(time.time()),
        'last_qso': {
            'timestamp': row[0],
            'callsign': row[1],
            'exchange': row[2],
            'section': row[3],
            'operator': row[4],
            'band_id': row[5],
            'band': band,
            'mode_id': row[6],
            'mode': mode,
            'station': row[7],
            'message': message,
        },
    })


@app.route('/api/summary')
def api_summary():
    """Band x mode QSO counts (CW / Phone / Data / Total) plus grand totals --
    the 'QSOs Summary' grid, as JSON for the mobile view."""
    import constants
    db = sqlite3.connect(config.DATABASE_FILENAME)
    try:
        cursor = db.cursor()
        grid = dataaccess.get_qso_band_modes(cursor)  # [band_id][0=n/a,1=cw,2=phone,3=data]
    finally:
        db.close()
    bands = []
    tot = [0, 0, 0]  # cw, phone, data
    for bid, row in enumerate(grid):
        if bid == 0:  # 'No Band' / N/A -- skip
            continue
        cw, phone, data = row[1], row[2], row[3]
        if (cw + phone + data) == 0:
            continue  # omit bands with no QSOs to keep the phone list short
        bands.append({
            'band': constants.Bands.BANDS_TITLE[bid],
            'cw': cw, 'phone': phone, 'data': data,
            'total': cw + phone + data,
        })
        tot[0] += cw; tot[1] += phone; tot[2] += data
    return jsonify({
        'server_time': int(time.time()),
        'bands': bands,
        'totals': {'cw': tot[0], 'phone': tot[1], 'data': tot[2],
                   'total': tot[0] + tot[1] + tot[2]},
    })


@app.route('/api/health')
def api_health():
    return jsonify({
        'ok': True,
        'version': VERSION,
        'image_dir': config.IMAGE_DIR,
        'server_time': int(time.time()),
    })


# A 1x1 transparent GIF used by the kiosk wrapper as a cross-origin reachability
# probe: an <img> load succeeds only when this server is up. Lighter and more
# CORS-proof than fetch(), and works from a file:// kiosk page.
_PING_GIF = base64.b64decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7')


@app.route('/kiosk-ping.gif')
def kiosk_ping():
    return Response(_PING_GIF, mimetype='image/gif',
                    headers={'Cache-Control': 'no-store, no-cache, must-revalidate'})


# ---------------------------------------------------------------------------
# Admin page
# ---------------------------------------------------------------------------

def _service_status(unit):
    """Return ('active'|'inactive'|'failed'|..., css_class)."""
    try:
        r = subprocess.run(
            ['systemctl', 'is-active', unit],
            capture_output=True, text=True, timeout=3)
        status = (r.stdout or r.stderr).strip() or 'unknown'
    except Exception as e:
        status = 'error: %s' % e
    cls = {
        'active': 'svc-active',
        'inactive': 'svc-inactive',
        'failed': 'svc-failed',
        'activating': 'svc-pending',
        'deactivating': 'svc-pending',
    }.get(status, 'svc-unknown')
    return status, cls


def _db_stats():
    out = {'qso_count': 0, 'last_qso': '—', 'radio_count': 0, 'error': None}
    try:
        db = sqlite3.connect(config.DATABASE_FILENAME)
        try:
            cursor = db.cursor()
            cursor.execute('SELECT COUNT(*) FROM qso_log;')
            out['qso_count'] = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM radio_info;')
            out['radio_count'] = cursor.fetchone()[0]
            cursor.execute('SELECT timestamp, callsign FROM qso_log ORDER BY timestamp DESC LIMIT 1;')
            row = cursor.fetchone()
            if row:
                ts = datetime.fromtimestamp(row[0], tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
                out['last_qso'] = '%s (%s)' % (row[1], ts)
        finally:
            db.close()
    except Exception as e:
        out['error'] = str(e)
    return out


def _format_freq(hz):
    if not hz:
        return '-.---.--'
    khz = hz / 1000.0
    mhz = int(khz / 1000)
    rem = khz - mhz * 1000
    khz_part = int(rem)
    dec = int(round((rem - khz_part) * 100))
    if dec == 100:
        dec = 0
        khz_part += 1
    return '%d.%03d.%02d' % (mhz, khz_part, dec)


def _radio_rows_for_admin():
    """Return *all* radio_info rows (no hide filter) annotated for the table."""
    radios = _query_radio_info()
    now = int(time.time())
    hide = getattr(config, 'RADIO_HIDE_SECONDS', 0)
    out = []
    for r in radios:
        age = now - int(r.get('last_update') or 0)
        hidden = bool(hide and hide > 0 and age > hide)
        out.append({
            'station_name': r.get('station_name') or '',
            'radio_nr': r.get('radio_nr'),
            'radio_name': r.get('radio_name') or '',
            'op_call': r.get('op_call') or '',
            'mode': r.get('mode') or '',
            'freq': _format_freq(r.get('freq')),
            'tx_freq': _format_freq(r.get('tx_freq')) if r.get('is_split') else '',
            'is_active': bool(r.get('is_active')),
            'is_connected': bool(r.get('is_connected')),
            'is_transmitting': bool(r.get('is_transmitting')),
            'last_update_utc': datetime.fromtimestamp(int(r.get('last_update') or 0),
                                                     tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            'age': age,
            'hidden': hidden,
        })
    return out


def _config_snapshot():
    out = []
    for key in CONFIG_KEYS:
        if hasattr(config, key):
            val = getattr(config, key)
            if isinstance(val, datetime):
                val = val.strftime('%Y-%m-%d %H:%M:%S')
            out.append((key, '' if val is None else str(val)))
    return out


ADMIN_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>n1mm_view admin</title>
<style>
  *,*::before,*::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         background: #1a1a2e; color: #e0e0e0; padding: 1rem; }
  header { display: flex; justify-content: space-between; align-items: baseline;
           border-bottom: 2px solid #0f3460; padding-bottom: 0.5rem; margin-bottom: 1rem; }
  header h1 { color: #e94560; font-size: 1.3rem; }
  header .links a { color: #6fd0ff; text-decoration: none; margin-left: 1rem; font-size: 0.9rem; }
  .flash { background: #16213e; border-left: 4px solid #5fff9c; padding: 0.6rem 0.8rem;
           margin-bottom: 1rem; font-size: 0.9rem; }
  .flash.error { border-left-color: #e94560; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem; }
  section { background: #16213e; border: 1px solid #0f3460; border-radius: 4px;
            padding: 0.8rem 1rem; }
  section h2 { color: #ffd24a; font-size: 0.95rem; text-transform: uppercase;
               letter-spacing: 0.05em; margin-bottom: 0.6rem; }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem;
          font-variant-numeric: tabular-nums; }
  th, td { text-align: left; padding: 0.25rem 0.5rem; border-bottom: 1px solid #0f3460; }
  th { color: #a0a0b8; font-weight: 500; }
  .svc-active { color: #5fff9c; font-weight: 600; }
  .svc-inactive { color: #888; }
  .svc-failed { color: #ff6666; font-weight: 600; }
  .svc-pending { color: #ffd24a; }
  .svc-unknown { color: #888; }
  form.action { margin-bottom: 0.5rem; }
  button { background: #0f3460; color: #e0e0e0; border: 1px solid #1a4a8a;
           padding: 0.45rem 0.75rem; font-size: 0.85rem; border-radius: 3px;
           cursor: pointer; width: 100%; text-align: left; }
  button:hover { background: #1a4a8a; }
  button.danger { background: #5a1320; border-color: #8a1f30; }
  button.danger:hover { background: #8a1f30; }
  .wide { grid-column: 1 / -1; overflow-x: auto; }
  tr.stale td { color: #888; }
  tr.hidden td { opacity: 0.5; font-style: italic; }
  .pill { display: inline-block; font-size: 0.7rem; padding: 0.05rem 0.4rem;
          border-radius: 8px; background: #0f3460; color: #a0a0b8;
          margin-right: 0.2rem; }
  .pill.tx { background: #5a1320; color: #ff9aa8; }
  .pill.active { background: #4a3a00; color: #ffd24a; }
  .pill.conn { background: #1a4a3a; color: #5fff9c; }
  .pill.disc { background: #2a2a2a; color: #888; }
  .pill.hidden { background: #2a2a2a; color: #888; }
  footer { text-align: center; color: #606080; font-size: 0.75rem; margin-top: 1rem; }
  code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.8rem; }
</style>
</head>
<body>

<header>
  <h1>n1mm_view admin &mdash; v{{ version }}</h1>
  <div class="links">
    <a href="/">dashboard</a>
    <a href="/api/radio">/api/radio</a>
    <a href="/api/health">/api/health</a>
    <a href="/admin">refresh</a>
  </div>
</header>

{% if flash %}
<div class="flash {% if flash_error %}error{% endif %}">{{ flash }}</div>
{% endif %}

<div class="grid">
  <section>
    <h2>Services</h2>
    <table>
      <tbody>
      {% for s in services %}
        <tr><td><code>{{ s.unit }}</code></td><td class="{{ s.cls }}">{{ s.status }}</td></tr>
      {% endfor %}
      </tbody>
    </table>
    <h2 style="margin-top:0.8rem;">Database</h2>
    <table>
      <tbody>
        <tr><td>DB file</td><td><code>{{ db_file }}</code></td></tr>
        <tr><td>QSO count</td><td>{{ db.qso_count }}</td></tr>
        <tr><td>Last QSO</td><td>{{ db.last_qso }}</td></tr>
        <tr><td>radio_info rows</td><td>{{ db.radio_count }}</td></tr>
        {% if db.error %}<tr><td>error</td><td class="svc-failed">{{ db.error }}</td></tr>{% endif %}
      </tbody>
    </table>
  </section>

  <section>
    <h2>Actions</h2>
    <form class="action" method="post" action="/admin/action/purge-stale">
      <button type="submit">Purge stale radio rows (older than {{ hide_secs }}s)</button>
    </form>
    <form class="action" method="post" action="/admin/action/clear-all"
          onsubmit="return confirm('Delete ALL rows from radio_info?');">
      <button type="submit" class="danger">Clear ALL radio rows</button>
    </form>
    <form class="action" method="post" action="/admin/action/regenerate-index">
      <button type="submit">Regenerate index.html (first run may take a few seconds)</button>
    </form>
    <p style="margin-top:0.6rem; font-size:0.75rem; color:#888;">
      Service restarts are not exposed here; use <code>sudo systemctl restart n1mm_view_*</code> from SSH.
    </p>
  </section>
</div>

<section class="wide">
  <h2>radio_info (all rows, including those filtered from the live display)</h2>
  {% if radios %}
  <table>
    <thead><tr>
      <th>Station</th><th>Nr</th><th>Name</th><th>Op</th><th>Mode</th>
      <th>Freq</th><th>TX</th><th>Flags</th><th>Last update (UTC)</th><th>Age</th>
    </tr></thead>
    <tbody>
    {% for r in radios %}
      <tr class="{% if r.hidden %}hidden{% elif r.age > 60 %}stale{% endif %}">
        <td>{{ r.station_name or '(empty)' }}</td>
        <td>{{ r.radio_nr }}</td>
        <td>{{ r.radio_name }}</td>
        <td>{{ r.op_call }}</td>
        <td>{{ r.mode }}</td>
        <td>{{ r.freq }}</td>
        <td>{{ r.tx_freq }}</td>
        <td>
          {% if r.is_active %}<span class="pill active">ACTIVE</span>{% endif %}
          {% if r.is_transmitting %}<span class="pill tx">TX</span>{% endif %}
          {% if r.is_connected %}<span class="pill conn">CONN</span>{% else %}<span class="pill disc">DISC</span>{% endif %}
          {% if r.hidden %}<span class="pill hidden">HIDDEN</span>{% endif %}
        </td>
        <td>{{ r.last_update_utc }}</td>
        <td>{{ r.age }}s</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p style="color:#888; font-size:0.85rem;">radio_info is empty.</p>
  {% endif %}
</section>

<section class="wide" style="margin-top:1rem;">
  <h2>Effective config</h2>
  <table>
    <tbody>
    {% for k, v in config_snapshot %}
      <tr><td style="width:30%;"><code>{{ k }}</code></td><td><code>{{ v }}</code></td></tr>
    {% endfor %}
    </tbody>
  </table>
</section>

<footer>n1mm_view v{{ version }} &mdash; admin (no auth)</footer>

</body>
</html>'''


def _render_admin(flash=None, flash_error=False):
    services = []
    for unit in SERVICES:
        status, cls = _service_status(unit)
        services.append({'unit': unit, 'status': status, 'cls': cls})
    return render_template_string(
        ADMIN_TEMPLATE,
        version=VERSION,
        services=services,
        db=_db_stats(),
        db_file=config.DATABASE_FILENAME,
        radios=_radio_rows_for_admin(),
        config_snapshot=_config_snapshot(),
        hide_secs=getattr(config, 'RADIO_HIDE_SECONDS', 0),
        flash=flash,
        flash_error=flash_error,
    )


@app.route('/admin')
def admin_page():
    msg = request.args.get('msg')
    err = request.args.get('err') == '1'
    return _render_admin(flash=msg, flash_error=err)


def _admin_redirect(msg, err=False):
    q = urllib.parse.urlencode({'msg': msg, 'err': '1' if err else '0'})
    return redirect('/admin?' + q, code=303)


@app.route('/admin/action/purge-stale', methods=['POST'])
def admin_purge_stale():
    hide = getattr(config, 'RADIO_HIDE_SECONDS', 0)
    if not hide or hide <= 0:
        return _admin_redirect('RADIO_HIDE_SECONDS is 0; nothing to purge.', err=True)
    try:
        db = sqlite3.connect(config.DATABASE_FILENAME)
        try:
            cursor = db.cursor()
            deleted = dataaccess.purge_stale_radio_info(db, cursor, hide)
        finally:
            db.close()
        return _admin_redirect('Purged %d row(s) older than %ds.' % (deleted, hide))
    except Exception as e:
        logger.exception('purge-stale failed')
        return _admin_redirect('purge failed: %s' % e, err=True)


@app.route('/admin/action/clear-all', methods=['POST'])
def admin_clear_all():
    try:
        db = sqlite3.connect(config.DATABASE_FILENAME)
        try:
            cursor = db.cursor()
            dataaccess.clear_radio_info(db, cursor)
        finally:
            db.close()
        return _admin_redirect('Cleared all radio_info rows.')
    except Exception as e:
        logger.exception('clear-all failed')
        return _admin_redirect('clear failed: %s' % e, err=True)


@app.route('/admin/action/regenerate-index', methods=['POST'])
def admin_regenerate_index():
    image_dir = config.IMAGE_DIR
    if not image_dir or image_dir == 'None':
        return _admin_redirect('IMAGE_DIR is not configured.', err=True)
    try:
        # Lazy import: headless.py pulls in matplotlib/cartopy/pygame which we
        # don't want to load until/unless this action fires.
        from headless import write_index_html
        write_index_html(image_dir)
        return _admin_redirect('Rewrote %s/index.html.' % image_dir)
    except Exception as e:
        logger.exception('regenerate-index failed')
        return _admin_redirect('regenerate failed: %s' % e, err=True)


# ---------------------------------------------------------------------------
# Static IMAGE_DIR serving (must be registered AFTER /admin routes so the
# catch-all /<path:filename> doesn't swallow /admin/...).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Mobile view -- a lightweight, responsive page that pulls the live JSON API
# instead of the fixed-width matplotlib slideshow. Phones land here automatically
# from '/'; '/m' always serves it; append '?big=1' to '/' to force the slideshow.
# ---------------------------------------------------------------------------

MOBILE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="dark">
<title>n1mm_view</title>
<style>
  :root {
    --bg: #0a1626; --card: #13233b; --line: #243a5a;
    --text: #d7e0ec; --muted: #8493ab; --pink: #e94560;
    --yellow: #ffd24a; --green: #43e08a; --cyan: #6fd0ff;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    -webkit-text-size-adjust: 100%; padding: env(safe-area-inset-top) 0 0 0;
  }
  .wrap { max-width: 640px; margin: 0 auto; padding: 0.75rem 0.75rem 2rem; }
  header { text-align: center; padding: 0.5rem 0 0.75rem; }
  header h1 { color: var(--pink); font-size: 1.15rem; margin: 0 0 0.4rem; line-height: 1.25; }
  .status { font-size: 1rem; font-weight: 600; margin: 0.2rem 0; }
  .status.pre { color: var(--yellow); }
  .status.live { color: var(--green); }
  .status.post { color: var(--muted); }
  .clocks { color: var(--muted); font-size: 0.85rem; margin-top: 0.3rem;
            font-variant-numeric: tabular-nums; }
  .clocks span { margin: 0 0.5rem; }
  section { background: var(--card); border: 1px solid var(--line);
            border-radius: 10px; padding: 0.75rem 0.85rem; margin-top: 0.75rem; }
  section h2 { color: var(--yellow); font-size: 0.72rem; letter-spacing: 0.08em;
               text-transform: uppercase; margin: 0 0 0.55rem; font-weight: 700; }
  .call { font-size: 1.5rem; font-weight: 700; color: var(--text); }
  .lq-sub { color: var(--muted); font-size: 0.9rem; margin-top: 0.15rem; }
  .lq-sub b { color: var(--cyan); font-weight: 600; }
  .radio { padding: 0.5rem 0; border-top: 1px solid var(--line); }
  .radio:first-of-type { border-top: 0; padding-top: 0; }
  .radio .top { display: flex; justify-content: space-between; align-items: baseline; }
  .radio .name { color: var(--text); font-size: 0.95rem; font-weight: 600; }
  .radio .op { color: var(--cyan); font-size: 0.85rem; }
  .radio .sub { color: var(--muted); font-size: 0.72rem; margin-top: 0.1rem; }
  .radio .mode { color: var(--yellow); font-size: 0.9rem; font-weight: 600;
                 vertical-align: 0.15rem; margin-left: 0.35rem; }
  .radio .freq { font-size: 1.6rem; font-weight: 700; color: var(--green);
                 font-variant-numeric: tabular-nums; line-height: 1.1; }
  .badges { margin-top: 0.3rem; display: flex; flex-wrap: wrap; gap: 0.35rem; }
  .pill { font-size: 0.7rem; padding: 0.1rem 0.45rem; border-radius: 999px;
          border: 1px solid var(--line); color: var(--muted); }
  .pill.on { color: var(--green); border-color: var(--green); }
  .pill.tx { color: var(--pink); border-color: var(--pink); }
  .pill.src { color: #ffcf6a; border-color: #ffcf6a; }
  .pill.dup { color: #ff6b6b; border-color: #ff6b6b; font-weight: 700; }
  .pill.offband { color: #ff9f43; border-color: #ff9f43; font-weight: 700; }
  .radio.offband { background: rgba(255,159,67,0.09); border-radius: 6px;
                   box-shadow: inset 0 0 0 1px #ff9f43; }
  .radio.dup { background: rgba(255,80,80,0.10); border-radius: 6px;
               box-shadow: inset 0 0 0 1px #ff6b6b; }
  .radio.fromqso { background: rgba(255,207,106,0.07); border-radius: 6px; }
  table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
  th, td { padding: 0.4rem 0.3rem; text-align: right; font-size: 0.95rem; }
  th:first-child, td:first-child { text-align: left; }
  thead th { color: var(--muted); font-size: 0.72rem; text-transform: uppercase;
             border-bottom: 1px solid var(--line); font-weight: 600; }
  tbody td { border-bottom: 1px solid rgba(36,58,90,0.5); }
  tfoot td { font-weight: 700; border-top: 2px solid var(--line); color: var(--yellow); }
  td.tot, th.tot { color: var(--text); font-weight: 700; }
  .muted { color: var(--muted); }
  .newops-list { margin-top: 0.5rem; }
  .newops-list div { font-size: 0.9rem; padding: 0.2rem 0;
                     display: flex; justify-content: space-between; }
  .newops-list .who { color: var(--green); font-weight: 600; }
  .big-link { display: block; text-align: center; color: var(--cyan);
              text-decoration: none; font-size: 0.85rem; margin-top: 1rem; }
  footer { text-align: center; color: var(--muted); font-size: 0.72rem;
           margin-top: 1rem; }
  footer .dot { color: var(--green); }
  footer .dot.stale { color: var(--pink); }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1 id="event">&nbsp;</h1>
    <div id="status" class="status">&nbsp;</div>
    <div class="clocks"><span id="utc"></span><span id="local"></span></div>
  </header>

  <section>
    <h2>Last QSO</h2>
    <div id="lastqso"><span class="muted">Loading…</span></div>
  </section>

  <section>
    <h2>Radios</h2>
    <div id="radios"><span class="muted">Loading…</span></div>
  </section>

  <section>
    <h2>QSOs by Band &amp; Mode</h2>
    <div id="summary"><span class="muted">Loading…</span></div>
  </section>

  <section>
    <h2>New Operators</h2>
    <div id="newops"><span class="muted">Loading…</span></div>
  </section>

  <a class="big-link" href="/?big=1">Switch to full dashboard view ›</a>
  <footer><span id="dot" class="dot">●</span> updated <span id="updated">—</span>
          · v<span id="ver">—</span></footer>
</div>

<script>
const EVENT = __EVENT_JSON__;
let skew = 0;            // serverTime - clientTime, in seconds
let lastQso = null;      // remembered for per-second "ago" updates
let lastOk = 0;          // client time of last successful load

function nowSec() { return Date.now() / 1000 + skew; }
function pad(n) { return String(n).padStart(2, '0'); }
function esc(s) { return String(s == null ? '' : s).replace(/[&<>]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }

function fmtFreq(hz) {
  if (!hz) return '-.---.--';
  const khz = hz / 1000.0;
  let mhz = Math.floor(khz / 1000);
  let rem = khz - mhz * 1000;
  let k = Math.floor(rem);
  let dec = Math.round((rem - k) * 100);
  if (dec === 100) { dec = 0; k += 1; }
  return mhz + '.' + String(k).padStart(3, '0') + '.' + pad(dec);
}

function ago(ts) {
  let s = Math.max(0, nowSec() - ts);
  if (s < 60) return Math.floor(s) + 's ago';
  if (s < 3600) return Math.floor(s / 60) + 'm ago';
  if (s < 86400) return Math.floor(s / 3600) + 'h ago';
  return Math.floor(s / 86400) + 'd ago';
}

function dur(sec) {
  sec = Math.max(0, Math.floor(sec));
  const d = Math.floor(sec / 86400); sec -= d * 86400;
  const h = Math.floor(sec / 3600); sec -= h * 3600;
  const m = Math.floor(sec / 60); const s = sec - m * 60;
  const hms = pad(h) + ':' + pad(m) + ':' + pad(s);
  return (d > 0 ? d + 'd ' : '') + hms;
}

function tick() {
  const d = new Date(nowSec() * 1000);
  document.getElementById('utc').textContent =
    'UTC ' + pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) + ':' + pad(d.getUTCSeconds());
  document.getElementById('local').textContent =
    'LOCAL ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());

  const st = document.getElementById('status');
  const now = nowSec();
  if (EVENT.start && now < EVENT.start) {
    st.textContent = 'Starts in ' + dur(EVENT.start - now); st.className = 'status pre';
  } else if (EVENT.end && now <= EVENT.end) {
    st.textContent = 'Running — ends in ' + dur(EVENT.end - now); st.className = 'status live';
  } else if (EVENT.end && now > EVENT.end) {
    st.textContent = 'Contest ended'; st.className = 'status post';
  } else { st.textContent = ' '; st.className = 'status'; }

  if (lastQso) {
    const a = document.getElementById('lq-ago');
    if (a) a.textContent = ago(lastQso.timestamp);
  }
}

function renderLastQso(d) {
  lastQso = d && d.last_qso ? d.last_qso : null;
  const el = document.getElementById('lastqso');
  if (!lastQso) { el.innerHTML = '<span class="muted">No QSOs yet.</span>'; return; }
  const q = lastQso;
  el.innerHTML =
    '<div class="call">' + esc(q.callsign) + '</div>' +
    '<div class="lq-sub">' + esc(q.band) + ' / ' + esc(q.mode) +
    ' by <b>' + esc(q.operator) + '</b> · <span id="lq-ago">' + ago(q.timestamp) + '</span>' +
    (q.section ? ' · ' + esc(q.section) : '') + '</div>';
}

function renderRadios(d) {
  const el = document.getElementById('radios');
  const rs = ((d && d.radios) || []).slice().sort((a, b) => {
    const an = (a.station_name || '').toUpperCase(), bn = (b.station_name || '').toUpperCase();
    return an < bn ? -1 : an > bn ? 1 : (a.radio_nr || 0) - (b.radio_nr || 0);
  });
  if (!rs.length) { el.innerHTML = '<span class="muted">No active radio.</span>'; return; }
  el.innerHTML = rs.map(r => {
    const badges = [];
    badges.push('<span class="pill' + (r.is_active ? ' on' : '') + '">' +
                (r.is_active ? 'ACTIVE' : 'idle') + '</span>');
    if (r.is_running !== undefined && r.is_running !== null)
      badges.push('<span class="pill">' + (r.is_running ? 'RUN' : 'S&amp;P') + '</span>');
    badges.push('<span class="pill' + (r.is_connected ? ' on' : '') + '">' +
                (r.is_connected ? 'CONN' : 'no conn') + '</span>');
    if (r.is_transmitting) badges.push('<span class="pill tx">TX</span>');
    // Source indicator: this row was synthesized from QSO traffic, not a real
    // RadioInfo broadcast -- go check that station's RadioInfo.
    if (r.source === 'contactinfo')
      badges.push('<span class="pill src" title="No RadioInfo received - derived from logged QSOs">via QSO</span>');
    // Duplicate band/mode alert (two radios in the same band + CW/PH/DATA group).
    if (r.dup)
      badges.push('<span class="pill dup">⚠ DUP ' +
                  esc((r.band || '?') + ' ' + (r.mode_group || '?')) + '</span>');
    // Out of band: outside any ham band, or phone below the phone sub-band edge.
    if (r.offband)
      badges.push('<span class="pill offband" title="Out of band: not in a ham band, or phone below the phone sub-band edge">OUT-OF-BAND</span>');
    // Lead with the station (computer) name, like the desktop panels; show the
    // radio number + radio name as a secondary line so that detail is kept too.
    const station = r.station_name || ('Radio ' + (r.radio_nr || ''));
    const radioBits = 'R' + (r.radio_nr || '') + (r.radio_name ? ' · ' + r.radio_name : '');
    return '<div class="radio' + (r.offband ? ' offband' : '') + (r.dup ? ' dup' : '') +
      (r.source === 'contactinfo' ? ' fromqso' : '') + '"><div class="top">' +
      '<span class="name">' + esc(station) + '</span>' +
      '<span class="op">' + esc(r.op_call || '') + '</span></div>' +
      '<div class="sub">' + esc(radioBits) + '</div>' +
      '<div class="freq">' + fmtFreq(r.freq) +
        (r.mode ? ' <span class="mode">' + esc(r.mode) + '</span>' : '') + '</div>' +
      '<div class="badges">' + badges.join('') + '</div></div>';
  }).join('');
}

function renderSummary(d) {
  const el = document.getElementById('summary');
  const bands = (d && d.bands) || [];
  if (!bands.length) { el.innerHTML = '<span class="muted">No QSOs yet.</span>'; return; }
  const t = d.totals;
  el.innerHTML =
    '<table><thead><tr><th>Band</th><th>CW</th><th>Ph</th><th>Data</th>' +
    '<th class="tot">Tot</th></tr></thead><tbody>' +
    bands.map(b => '<tr><td>' + esc(b.band) + '</td><td>' + b.cw + '</td><td>' +
      b.phone + '</td><td>' + b.data + '</td><td class="tot">' + b.total +
      '</td></tr>').join('') +
    '</tbody><tfoot><tr><td>Total</td><td>' + t.cw + '</td><td>' + t.phone +
    '</td><td>' + t.data + '</td><td>' + t.total + '</td></tr></tfoot></table>';
}

function renderNewOps(d) {
  const el = document.getElementById('newops');
  if (!d) { el.innerHTML = '<span class="muted">—</span>'; return; }
  const prior = (d.prior_new != null)
    ? (' (' + d.prior_new + ' new' + (d.prior_event_label ? ' in ' + esc(d.prior_event_label) : ' prior') + ')')
    : '';
  let html = '<div><b style="color:var(--yellow)">' + (d.total_new || 0) +
    '</b> new this event' + prior + '</div>';
  const ops = (d.new_ops || []).slice(0, 12);
  if (ops.length) {
    html += '<div class="newops-list">' + ops.map(o =>
      '<div><span class="who">' + esc(o.name) + '</span>' +
      '<span class="muted">' + esc([o.band, o.mode].filter(Boolean).join(' ')) +
      (o.worked ? ' · ' + esc(o.worked) : '') + '</span></div>').join('') + '</div>';
  }
  el.innerHTML = html;
}

async function getJSON(url) {
  const r = await fetch(url, { cache: 'no-store' });
  if (!r.ok) throw new Error(url + ' ' + r.status);
  return r.json();
}

async function load() {
  try {
    const [lq, radio, summary, newops] = await Promise.all([
      getJSON('/api/last_qso'), getJSON('/api/radio'),
      getJSON('/api/summary'), getJSON('/api/new_ops'),
    ]);
    if (lq && lq.server_time) skew = lq.server_time - Date.now() / 1000;
    renderLastQso(lq); renderRadios(radio);
    renderSummary(summary); renderNewOps(newops);
    lastOk = Date.now() / 1000;
    const dt = new Date(nowSec() * 1000);
    document.getElementById('updated').textContent =
      pad(dt.getHours()) + ':' + pad(dt.getMinutes()) + ':' + pad(dt.getSeconds());
    document.getElementById('dot').className = 'dot';
  } catch (e) {
    document.getElementById('dot').className = 'dot stale';
  }
}

document.getElementById('event').textContent = EVENT.name || 'n1mm_view';
document.getElementById('ver').textContent = EVENT.version || '';
tick();
load();
setInterval(tick, 1000);
setInterval(load, 10000);
// Refresh promptly when the phone wakes / tab refocuses.
document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
</script>
</body>
</html>
"""

_MOBILE_UA = re.compile(r'Mobi|Android|iPhone|iPod|iPad|Windows Phone|BlackBerry', re.I)


# ---------------------------------------------------------------------------
# Kiosk wrapper -- a resilient shell for an always-on display. It never
# navigates away: it loads the dashboard in an iframe and probes the pi with a
# tiny <img> ping. When the pi is unreachable it shows a "Waiting…" overlay and
# keeps retrying; when the pi returns it reloads the iframe automatically. Loaded
# from a local file on the kiosk it even survives the pi being down at boot --
# the wrapper still loads and waits, where a bare browser would be stuck on its
# own "can't reach the site" error page with no JS to retry.
# ---------------------------------------------------------------------------

KIOSK_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>pi400 kiosk</title>
<style>
  html, body { margin: 0; height: 100%; background: #000; overflow: hidden;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  #dash { position: fixed; inset: 0; width: 100%; height: 100%; border: 0; background: #000; }
  #overlay { position: fixed; inset: 0; z-index: 10; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 1.1rem;
    background: #0a1626; color: #d7e0ec; transition: opacity .5s ease; }
  #overlay.hidden { opacity: 0; pointer-events: none; }
  .spinner { width: 64px; height: 64px; border: 6px solid #243a5a;
    border-top-color: #e94560; border-radius: 50%; animation: spin 1s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  h1 { color: #e94560; font-size: 2rem; margin: 0; }
  p { margin: 0; color: #8493ab; font-size: 1.1rem; }
  #clk { font-variant-numeric: tabular-nums; }
</style>
</head>
<body>
  <iframe id="dash" referrerpolicy="no-referrer"></iframe>
  <div id="overlay">
    <div class="spinner"></div>
    <h1>Waiting for pi400…</h1>
    <p id="msg">Trying to reach the dashboard</p>
    <p id="clk"></p>
  </div>
<script>
  // Base URL of the pi running webserver.py. '' = same origin (this page served
  // by the pi at /kiosk). When loading this file locally on the kiosk, set it to
  // the pi, e.g. 'http://pi400.local'.
  var PI = '__PI_BASE__';
  var DASH = PI + '/?big=1';
  var PING = PI + '/kiosk-ping.gif';
  var POLL_MS = 4000;     // how often to probe the pi
  var TIMEOUT_MS = 3500;  // a probe is considered failed after this

  var iframe = document.getElementById('dash');
  var overlay = document.getElementById('overlay');
  var msg = document.getElementById('msg');
  var up = null;          // null = unknown, true / false

  function loadDash() { iframe.src = DASH + '&t=' + Date.now(); }

  // Reveal the dashboard only once the (re)loaded iframe has actually painted,
  // so recovery doesn't flash an empty/half-loaded frame. If the pi drops again
  // before it loads, 'up' is already false and the overlay simply stays up.
  iframe.addEventListener('load', function() { if (up) overlay.classList.add('hidden'); });

  function ping() {
    return new Promise(function(resolve) {
      var img = new Image();
      var done = false;
      var to = setTimeout(function() {
        if (!done) { done = true; img.src = ''; resolve(false); }
      }, TIMEOUT_MS);
      img.onload = function() { if (!done) { done = true; clearTimeout(to); resolve(true); } };
      img.onerror = function() { if (!done) { done = true; clearTimeout(to); resolve(false); } };
      img.src = PING + '?t=' + Date.now();
    });
  }

  function tick() {
    ping().then(function(ok) {
      if (ok) {
        // Reload the dashboard only on the down->up (or first) transition; while
        // the pi stays up the dashboard refreshes its own images/data.
        if (up !== true) { loadDash(); }  // overlay hides on the iframe 'load' event
        up = true;
      } else {
        if (up !== false) {
          overlay.classList.remove('hidden');
          msg.textContent = 'pi400 is unreachable — retrying every ' + (POLL_MS / 1000) + 's';
        }
        up = false;
      }
    });
  }

  setInterval(function() {
    document.getElementById('clk').textContent = new Date().toLocaleTimeString();
  }, 1000);
  tick();
  setInterval(tick, POLL_MS);
</script>
</body>
</html>
"""


def _event_meta():
    def epoch(dt):
        if not dt:
            return None
        try:
            return int(dt.replace(tzinfo=timezone.utc).timestamp())
        except Exception:
            return None
    return {
        'name': config.EVENT_NAME,
        'start': epoch(getattr(config, 'EVENT_START_TIME', None)),
        'end': epoch(getattr(config, 'EVENT_END_TIME', None)),
        'version': VERSION,
    }


def _render_mobile():
    return MOBILE_HTML.replace('__EVENT_JSON__', json.dumps(_event_meta()))


@app.route('/m')
def mobile_page():
    return _render_mobile()


@app.route('/kiosk')
def kiosk_page():
    # Served by the pi itself -> same-origin base ('') for the iframe and ping.
    return KIOSK_HTML.replace('__PI_BASE__', '')


@app.route('/')
def index():
    ua = request.headers.get('User-Agent', '')
    if _MOBILE_UA.search(ua) and not request.args.get('big'):
        return _render_mobile()
    return _serve('index.html')


@app.route('/<path:filename>')
def static_file(filename):
    return _serve(filename)


def _serve(filename):
    image_dir = config.IMAGE_DIR
    if not image_dir or image_dir == 'None':
        abort(500, description='IMAGE_DIR is not configured')
    full = os.path.join(image_dir, filename)
    if not os.path.exists(full):
        abort(404)
    return send_from_directory(image_dir, filename)


@app.after_request
def _no_cache_api(response):
    if response.mimetype == 'application/json' or response.mimetype == 'text/html':
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


def main():
    if not config.WEBSERVER_ENABLED:
        logger.info('Web server disabled in config; exiting.')
        sys.exit(0)
    image_dir = config.IMAGE_DIR
    if not image_dir or image_dir == 'None':
        logger.error('IMAGE_DIR is not set; the web server has nothing to serve.')
        sys.exit(1)
    if not os.path.isdir(image_dir):
        logger.warning('IMAGE_DIR %s does not exist yet; headless.py will create it.', image_dir)

    bind = config.WEBSERVER_BIND
    port = config.WEBSERVER_PORT
    logger.info('Starting n1mm_view web server v%s on %s:%d serving %s',
                VERSION, bind, port, image_dir)
    app.run(host=bind, port=port, threaded=True, use_reloader=False)


if __name__ == '__main__':
    main()
