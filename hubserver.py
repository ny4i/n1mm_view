#!/usr/bin/python3
"""
hubserver.py

Lightweight "information hub" / landing page for the Field Day station.
Runs on port 80 and gives a single view that:

  - Links out to the QSO dashboard (webserver.py, :8080) and the TR4W
    server (tr4wserver.py, :8081).
  - Shows live up/down status for the four station processes
    (collector, headless, webserver, tr4wserver) via `systemctl is-active`
    plus a TCP reachability check for the ones that listen on a port.
  - Shows a few live figures from the QSO database (event name, total
    QSOs, last QSO).

This is deliberately separate from webserver.py: webserver.py serves the
chart IMAGE_DIR; this is just a status/landing page. It binds port 80, so
its systemd unit grants CAP_NET_BIND_SERVICE rather than running as root.

Run standalone for testing on an unprivileged port:
    ./hubserver.py 8088
"""
import logging
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template_string, request

from config import Config, VERSION

logging.basicConfig(level=logging.INFO)
config = Config()
logger = logging.getLogger(__name__)

app = Flask(__name__)

# The four station processes we care about, in display order. `port` is the
# TCP port the service listens on (None = no listener, status from systemd
# only). `link` controls whether the card offers an "Open" button.
SERVICES = [
    {'unit': 'n1mm_view_collector', 'label': 'Collector',
     'desc': 'Receives N1MM+ UDP broadcasts', 'port': None, 'link': False},
    {'unit': 'n1mm_view_headless', 'label': 'Headless Renderer',
     'desc': 'Generates the chart images', 'port': None, 'link': False},
    {'unit': 'n1mm_view_webserver', 'label': 'QSO Dashboard',
     'desc': 'Live charts & radio sidebar', 'port': 8080, 'link': True},
    {'unit': 'tr4wserver', 'label': 'TR4W Server',
     'desc': 'TR4W logging server', 'port': 8081, 'link': True},
    {'unit': 'gateway', 'label': 'ClubLog Gateway',
     'desc': 'Real-time QSO upload to ClubLog', 'port': None, 'link': False},
    {'unit': 'chrony', 'label': 'NTP (chrony)',
     'desc': 'System time synchronization', 'port': None, 'link': False},
]


# Mode marker written by ~/setNetMode.sh (fieldday|normal + epoch).
NETMODE_FILE = getattr(config, 'NETMODE_FILE', '/home/pi/.netmode')
# Log written by ~/checkNet.sh (the priority Wi-Fi selector, Field Day only).
CHECKNET_LOG = getattr(config, 'CHECKNET_LOG', '/var/log/checkNet.log')

# checkNet log lines worth surfacing as "what it last did".
_CHECKNET_KEYS = ('Already connected', 'Successfully connected', 'Switching Wi-Fi',
                  'None of the configured', 'reachable via wlan0',
                  'Leaving current Wi-Fi')


def _run(cmd):
    """Run a command, return stdout stripped ('' on any failure)."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=3).stdout.strip()
    except Exception:
        return ''


def _checknet_info():
    """Last run time + last meaningful result from checkNet.sh's log."""
    import re
    out = {'last_run': None, 'last_msg': None}
    try:
        with open(CHECKNET_LOG, 'rb') as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 8192))
            lines = [l for l in fh.read().decode('utf-8', 'ignore').splitlines() if l.strip()]
    except OSError:
        return out
    ts_re = re.compile(r'\[([\d\-]+ [\d:]+)\]\s*(.*)')
    for line in reversed(lines):
        m = ts_re.match(line)
        if m and not out['last_run']:
            out['last_run'] = m.group(1)
        msg = m.group(2) if m else line
        if not out['last_msg'] and any(k in msg for k in _CHECKNET_KEYS):
            out['last_msg'] = msg
        if out['last_run'] and out['last_msg']:
            break
    return out


def _net_info():
    """Current network state for the hub: mode marker, uplink adapter, the
    Wi-Fi AP we're on (if any), and per-interface IPv4 addresses."""
    info = {'mode': None, 'mode_since': None, 'uplink': None,
            'ssid': None, 'bssid': None, 'signal': None, 'addresses': []}
    # Mode marker from setNetMode.sh
    try:
        with open(NETMODE_FILE) as fh:
            for line in fh:
                if line.startswith('mode='):
                    info['mode'] = line.split('=', 1)[1].strip()
                elif line.startswith('since='):
                    try:
                        info['mode_since'] = int(line.split('=', 1)[1].strip())
                    except ValueError:
                        pass
    except OSError:
        pass
    # Which adapter currently carries the default route (the live uplink)
    route = _run(['ip', 'route', 'show', 'default'])
    parts = route.split()
    if 'dev' in parts:
        info['uplink'] = parts[parts.index('dev') + 1]
    # Per-interface IPv4 addresses (skip loopback)
    for line in _run(['ip', '-o', '-4', 'addr', 'show']).splitlines():
        cols = line.split()
        if len(cols) >= 4 and cols[1] != 'lo':
            info['addresses'].append({'iface': cols[1], 'ip': cols[3]})
    # Wi-Fi AP: SSID + signal, plus BSSID (the specific access point)
    for line in _run(['nmcli', '-t', '-f', 'active,ssid,signal',
                      'dev', 'wifi']).splitlines():
        if line.startswith('yes:'):
            f = line.split(':')
            info['ssid'] = f[1] or None
            info['signal'] = f[-1] or None
            break
    for line in _run(['nmcli', '-t', '-f', 'active,bssid',
                      'dev', 'wifi']).splitlines():
        # nmcli -t escapes the colons inside a BSSID as '\:'; protect them
        # before splitting on the field separator, then restore.
        guard = line.replace('\\:', '\0')
        if guard.startswith('yes:'):
            info['bssid'] = guard.split(':', 1)[1].replace('\0', ':') or None
            break
    # checkNet activity is only relevant in Field Day mode (WiFi uplink).
    if info['mode'] == 'fieldday':
        info['checknet'] = _checknet_info()
    return info


def _service_status(unit):
    """Return systemd state string: 'active' | 'inactive' | 'failed' | ..."""
    try:
        r = subprocess.run(['systemctl', 'is-active', unit],
                           capture_output=True, text=True, timeout=3)
        return (r.stdout or r.stderr).strip() or 'unknown'
    except Exception as e:
        return 'error: %s' % e


def _port_open(port, host='127.0.0.1', timeout=0.5):
    """True if something is accepting TCP connections on host:port."""
    if not port:
        return None
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _db_stats():
    out = {'event': getattr(config, 'EVENT_NAME', '') or '', 'qso_count': 0,
           'last_qso': '—', 'error': None}
    try:
        db = sqlite3.connect(config.DATABASE_FILENAME)
        try:
            cursor = db.cursor()
            cursor.execute('SELECT COUNT(*) FROM qso_log;')
            out['qso_count'] = cursor.fetchone()[0]
            cursor.execute('SELECT timestamp, callsign FROM qso_log '
                           'ORDER BY timestamp DESC LIMIT 1;')
            row = cursor.fetchone()
            if row:
                ts = datetime.fromtimestamp(row[0], tz=timezone.utc).strftime(
                    '%Y-%m-%d %H:%M:%S UTC')
                out['last_qso'] = '%s (%s)' % (row[1], ts)
        finally:
            db.close()
    except Exception as e:
        out['error'] = str(e)
    return out


def _collect_status():
    """Assemble the full status payload used by both the page and /api/status."""
    services = []
    up = 0
    for s in SERVICES:
        state = _service_status(s['unit'])
        listening = _port_open(s['port'])
        # "ok" means systemd says active AND (if it has a port) the port answers.
        ok = (state == 'active') and (listening is not False)
        if ok:
            up += 1
        services.append({
            'unit': s['unit'], 'label': s['label'], 'desc': s['desc'],
            'port': s['port'], 'link': s['link'],
            'state': state, 'listening': listening, 'ok': ok,
        })
    return {
        'server_time': int(time.time()),
        'services': services,
        'up': up,
        'total': len(SERVICES),
        'db': _db_stats(),
        'net': _net_info(),
    }


@app.route('/api/status')
def api_status():
    return jsonify(_collect_status())


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ event or 'Field Day' }} - Station Hub</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         background: #0d1117; color: #e6edf3; }
  header { padding: 1.2rem 1.5rem; border-bottom: 1px solid #30363d;
           display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.75rem; }
  header h1 { margin: 0; font-size: 1.5rem; }
  header .clock { margin-left: auto; font-variant-numeric: tabular-nums; color: #8b949e; }
  .wrap { padding: 1.5rem; max-width: 1100px; margin: 0 auto; }
  .stats { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.5rem; }
  .stat { background: #161b22; border: 1px solid #30363d; border-radius: 10px;
          padding: 0.9rem 1.2rem; flex: 1 1 180px; }
  .stat .k { font-size: 0.8rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.04em; }
  .stat .v { font-size: 1.3rem; font-weight: 600; margin-top: 0.25rem; }
  .grid { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 12px;
          padding: 1.1rem 1.2rem; display: flex; flex-direction: column; gap: 0.6rem; }
  .card h2 { margin: 0; font-size: 1.1rem; display: flex; align-items: center; gap: 0.55rem; }
  .dot { width: 11px; height: 11px; border-radius: 50%; flex: none; box-shadow: 0 0 8px currentColor; }
  .ok { color: #3fb950; } .bad { color: #f85149; } .warn { color: #d29922; }
  .card .desc { color: #8b949e; font-size: 0.9rem; flex: 1; }
  .card .state { font-size: 0.82rem; color: #8b949e; font-variant-numeric: tabular-nums; }
  .card a.open { align-self: flex-start; text-decoration: none; background: #1f6feb;
                 color: #fff; padding: 0.45rem 0.9rem; border-radius: 8px; font-weight: 600;
                 font-size: 0.9rem; }
  .card a.open:hover { background: #388bfd; }
  footer { padding: 1rem 1.5rem; color: #6e7681; font-size: 0.8rem; border-top: 1px solid #30363d; }
  .net { background: #161b22; border: 1px solid #30363d; border-radius: 12px;
         padding: 1.1rem 1.2rem; margin-bottom: 1.5rem; }
  .net h2 { margin: 0 0 0.8rem; font-size: 1.05rem; display: flex; align-items: center; gap: 0.6rem; }
  .net .badge { font-size: 0.8rem; font-weight: 700; padding: 0.2rem 0.6rem; border-radius: 6px; }
  .badge.fieldday { background: #1f6feb; color: #fff; }
  .badge.normal { background: #2d333b; color: #adbac7; }
  .badge.unknown { background: #6e4a00; color: #f0c674; }
  .net .rows { display: grid; gap: 0.4rem 1.5rem; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
  .net .row { display: flex; justify-content: space-between; gap: 1rem;
              padding: 0.35rem 0; border-bottom: 1px solid #21262d; font-size: 0.92rem; }
  .net .row .k { color: #8b949e; } .net .row .v { font-variant-numeric: tabular-nums; text-align: right; }
</style>
</head>
<body>
<header>
  <h1>{{ event or 'Field Day' }} &mdash; Station Hub</h1>
  <span class="clock" id="clock"></span>
</header>
<div class="wrap">
  <div class="stats">
    <div class="stat"><div class="k">Services Up</div><div class="v" id="upcount">{{ up }}/{{ total }}</div></div>
    <div class="stat"><div class="k">Total QSOs</div><div class="v" id="qsos">{{ db.qso_count }}</div></div>
    <div class="stat"><div class="k">Last QSO</div><div class="v" id="lastqso" style="font-size:1rem">{{ db.last_qso }}</div></div>
  </div>
  <div class="net" id="net"></div>
  <div class="grid" id="grid"></div>
</div>
<footer>n1mm_view station hub v{{ version }} &middot; auto-refreshing every 5s</footer>
<script>
  // Build service links from the hostname the browser used, so they work
  // from any device on the LAN regardless of how this page was reached.
  var HOST = window.location.hostname;
  function dotClass(s) { return s.ok ? 'ok' : (s.state === 'active' ? 'warn' : 'bad'); }
  function stateText(s) {
    var t = s.state;
    if (s.port) t += s.listening === true ? ', port ' + s.port + ' open'
                    : (s.listening === false ? ', port ' + s.port + ' DOWN' : '');
    return t;
  }
  function renderNet(n) {
    var mode = (n.mode || 'unknown');
    var rows = [];
    if (n.uplink) rows.push(['Uplink adapter', n.uplink]);
    if (n.ssid) {
      var ap = n.ssid + (n.signal ? ' (' + n.signal + '%)' : '');
      rows.push(['Connected AP', ap]);
      if (n.bssid) rows.push(['AP BSSID', n.bssid]);
    }
    (n.addresses || []).forEach(function (a) { rows.push([a.iface + ' IP', a.ip]); });
    if (n.checknet && n.checknet.last_run) {
      rows.push(['Wi-Fi mgr (checkNet)', n.checknet.last_run]);
      if (n.checknet.last_msg) rows.push(['checkNet result', n.checknet.last_msg]);
    }
    var rowHtml = rows.map(function (r) {
      return '<div class="row"><span class="k">' + r[0] + '</span><span class="v">' + r[1] + '</span></div>';
    }).join('');
    document.getElementById('net').innerHTML =
      '<h2>Network <span class="badge ' + mode + '">' +
        (mode === 'fieldday' ? 'FIELD DAY MODE' : mode === 'normal' ? 'NORMAL MODE' : 'MODE UNKNOWN') +
      '</span></h2><div class="rows">' + rowHtml + '</div>';
  }
  function render(data) {
    renderNet(data.net || {});
    document.getElementById('upcount').textContent = data.up + '/' + data.total;
    document.getElementById('qsos').textContent = data.db.qso_count;
    document.getElementById('lastqso').textContent = data.db.last_qso;
    var grid = document.getElementById('grid');
    grid.innerHTML = '';
    data.services.forEach(function (s) {
      var card = document.createElement('div');
      card.className = 'card';
      var link = (s.link && s.port)
        ? '<a class="open" href="http://' + HOST + ':' + s.port + '/" target="_blank" rel="noopener">Open &rarr;</a>'
        : '';
      card.innerHTML =
        '<h2><span class="dot ' + dotClass(s) + '"></span>' + s.label + '</h2>' +
        '<div class="desc">' + s.desc + '</div>' +
        '<div class="state">' + stateText(s) + '</div>' + link;
      grid.appendChild(card);
    });
  }
  function tick() {
    var now = new Date();
    document.getElementById('clock').textContent = now.toUTCString().replace('GMT', 'UTC');
  }
  function poll() {
    fetch('/api/status').then(function (r) { return r.json(); })
      .then(render).catch(function () {});
  }
  tick(); setInterval(tick, 1000);
  poll(); setInterval(poll, 5000);
</script>
</body>
</html>
"""


@app.route('/')
def index():
    data = _collect_status()
    return render_template_string(PAGE, version=VERSION, event=data['db']['event'],
                                  up=data['up'], total=data['total'], db=data['db'])


def main():
    # Optional argv port override for testing on an unprivileged port.
    port = int(sys.argv[1]) if len(sys.argv) > 1 else getattr(config, 'HUB_PORT', 80)
    bind = getattr(config, 'HUB_BIND', '0.0.0.0')
    logger.info('Starting n1mm_view station hub v%s on %s:%d', VERSION, bind, port)
    app.run(host=bind, port=port, threaded=True, use_reloader=False)


if __name__ == '__main__':
    main()
