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

import logging
import os
import sqlite3
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone

from flask import Flask, jsonify, redirect, render_template_string, request, send_from_directory, abort

from config import Config, VERSION
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


@app.route('/api/radio')
def api_radio():
    radios = _query_radio_info()
    now = int(time.time())
    hide = getattr(config, 'RADIO_HIDE_SECONDS', 0)
    if hide and hide > 0:
        radios = [r for r in radios if (now - r['last_update']) <= hide]
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
    return jsonify({
        'server_time': int(time.time()),
        'event_name': config.EVENT_NAME,
        'prior_event_label': getattr(config, 'PRIOR_EVENT_LABEL', ''),
        # prior_total = last reference event only (e.g. 2025 FD = 25);
        # all_prior_total = union across every imported prior event
        # (e.g. 75 across 2019-2025).
        'prior_total': len(last_event_names) if last_event_names else None,
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


@app.route('/api/health')
def api_health():
    return jsonify({
        'ok': True,
        'version': VERSION,
        'image_dir': config.IMAGE_DIR,
        'server_time': int(time.time()),
    })


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

@app.route('/')
def index():
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
