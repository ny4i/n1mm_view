#!/usr/bin/python3
"""
n1mm_view event hooks

Fire user-supplied external scripts when notable contest events occur:

    new_multiplier   -- a multiplier value was worked for the first time
    operator_change  -- the operator at a station changed
    band_change      -- a station moved to a different band

Design / safety notes
---------------------
  * Scripts are invoked with subprocess WITHOUT a shell (an argv list, so
    shell=False). Event data therefore can never be interpreted as shell
    syntax -- a callsign or exchange like "rm -rf ~" arrives as one inert
    argv/env string and is never executed. This is the primary injection
    defense: values are *parameters to a program*, not shell input.
  * Every event field is exported as an N1MMV_* environment variable
    (CGI / $_SERVER style), so a hook reads e.g. $N1MMV_NEW_MULTIPLIER,
    $N1MMV_CURRENT_OPERATOR, $N1MMV_NEW_CALL. The event name is also passed
    as argv[1] for easy `case "$1" in ...` dispatch in a shell script.
  * Hooks run in daemon threads with a timeout, so a slow or hung script can
    never stall the collector's real-time UDP ingest. Concurrency is bounded
    so an event storm (e.g. a multiplier pileup) cannot fork-bomb the box.
  * Field values are sanitized (control characters stripped, length capped)
    and every failure is caught and logged. A misbehaving hook can never
    break contact collection.

The collector calls EventHooks.on_contact() once per successfully recorded
QSO with a dict of fields; this module owns the change-detection state and
decides which (if any) scripts to fire.
"""

import logging
import os
import re
import subprocess
import threading

# Strip ASCII control characters (incl. NUL, CR, LF, ESC) from field values so
# nothing weird lands in a child process's environment or a downstream device.
_CONTROL_CHARS = re.compile(r'[\x00-\x1f\x7f]')
_MAX_VALUE_LEN = 256

# The events we support and the Config attribute holding each script path.
_EVENT_SCRIPTS = (
    ('new_multiplier', 'HOOK_NEW_MULTIPLIER_SCRIPT'),
    ('operator_change', 'HOOK_OPERATOR_CHANGE_SCRIPT'),
    ('band_change', 'HOOK_BAND_CHANGE_SCRIPT'),
)


def _sanitize(value):
    """Coerce any field value to a safe, bounded, control-char-free string."""
    s = '' if value is None else str(value)
    s = _CONTROL_CHARS.sub(' ', s)
    return s[:_MAX_VALUE_LEN]


class EventHooks:
    """
    Dispatch external scripts for contest events, and track the per-station
    operator/band state used to detect operator_change / band_change.

    One instance lives for the life of the collector's message_processor.
    """

    def __init__(self, config):
        self.timeout = max(1, getattr(config, 'HOOK_TIMEOUT', 10))
        max_conc = max(1, getattr(config, 'HOOK_MAX_CONCURRENT', 4))
        self._sema = threading.BoundedSemaphore(max_conc)
        self.mult_per_band = bool(getattr(config, 'HOOK_MULT_PER_BAND', False))

        # Resolve and validate each configured script path once, up front.
        self._scripts = {}
        for event, attr in _EVENT_SCRIPTS:
            path = self._resolve(getattr(config, attr, '') or '')
            if path:
                self._scripts[event] = path
                logging.info('Event hook enabled: %s -> %s', event, path)

        # station name -> {'operator': str, 'band': str} of the last QSO seen.
        self._last = {}
        self.enabled = bool(self._scripts)
        if self.enabled:
            logging.info('Event hooks active (timeout=%ss, max_concurrent=%d, mult_per_band=%s)',
                         self.timeout, max_conc, self.mult_per_band)

    @staticmethod
    def _resolve(raw):
        """Expand, validate, and return an absolute script path, or None."""
        raw = (raw or '').strip()
        if not raw:
            return None
        path = os.path.realpath(os.path.expanduser(raw))
        if not os.path.isfile(path):
            logging.warning('Event hook script not found, disabling: %s', raw)
            return None
        if not os.access(path, os.X_OK):
            logging.warning('Event hook script not executable (chmod +x it), disabling: %s', path)
            return None
        return path

    def on_contact(self, fields):
        """
        Evaluate one recorded QSO for events and fire any matching hooks.

        `fields` is a dict built by the collector; keys used here:
          station, operator, band, callsign, mult_is_new, mult_value, ...
        Never raises -- collection must continue regardless.
        """
        try:
            station = fields.get('station') or ''
            prev = self._last.get(station)
            if prev is not None:
                op = fields.get('operator')
                if op and op != prev.get('operator'):
                    self.fire('operator_change',
                              dict(fields, previous_operator=prev.get('operator')))
                band = fields.get('band')
                if band and band != prev.get('band'):
                    self.fire('band_change',
                              dict(fields, previous_band=prev.get('band')))
            self._last[station] = {'operator': fields.get('operator'),
                                   'band': fields.get('band')}

            if fields.get('mult_is_new') and fields.get('mult_value'):
                self.fire('new_multiplier', fields)
        except Exception:
            logging.exception('event hook on_contact failed')

    def fire(self, event, fields):
        """Spawn the script for `event` (if configured) without blocking."""
        path = self._scripts.get(event)
        if not path:
            return
        env = self._build_env(event, fields)
        # Non-blocking acquire: if we're already at the concurrency cap a hung
        # script is holding threads, so drop this event rather than pile up.
        if not self._sema.acquire(blocking=False):
            logging.warning('event hook concurrency limit reached; dropping %s event', event)
            return
        threading.Thread(target=self._run, args=(event, path, env), daemon=True).start()

    def _build_env(self, event, f):
        env = dict(os.environ)

        def put(key, value):
            env['N1MMV_' + key] = _sanitize(value)

        put('EVENT', event)
        put('TIMESTAMP', f.get('timestamp', ''))
        put('STATION', f.get('station', ''))
        put('CURRENT_OPERATOR', f.get('operator', ''))
        put('PREVIOUS_OPERATOR', f.get('previous_operator', ''))
        put('NEW_CALL', f.get('callsign', ''))
        put('MYCALL', f.get('mycall', ''))
        put('BAND', f.get('band', ''))
        put('PREVIOUS_BAND', f.get('previous_band', ''))
        put('MODE', f.get('mode', ''))
        put('FREQ', f.get('freq', ''))
        put('SECTION', f.get('section', ''))
        put('EXCHANGE', f.get('exchange', ''))
        put('MULT_TYPE', f.get('mult_type', ''))
        put('MULT_NAME', f.get('mult_name', ''))
        put('NEW_MULTIPLIER', f.get('mult_value', ''))
        put('MULT_COUNT', f.get('mult_count', ''))
        put('QSO_COUNT', f.get('qso_count', ''))
        return env

    def _run(self, event, path, env):
        try:
            proc = subprocess.run(
                [path, event], env=env, shell=False,
                cwd=os.path.dirname(path) or None,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=self.timeout)
            if proc.returncode != 0:
                err = (proc.stderr or b'').decode('utf-8', 'replace').strip()
                logging.warning('event hook %s exited %d: %s', event, proc.returncode, err[:500])
            else:
                logging.info('event hook %s fired ok (%s)', event, os.path.basename(path))
        except subprocess.TimeoutExpired:
            logging.warning('event hook %s timed out after %ss, killed: %s', event, self.timeout, path)
        except Exception:
            logging.exception('event hook %s failed to run: %s', event, path)
        finally:
            self._sema.release()
