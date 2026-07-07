#!/usr/bin/python3
"""
n1mm_view collector
This program collects N1MM+ "Contact Info" broadcasts and saves data from the broadcasts
in database tables.
"""

import hashlib
import logging
import multiprocessing
import socket
import sqlite3
import time
import xml.parsers.expat

from config import Config
import constants
import dataaccess

__author__ = 'Jeffrey B. Otterson, N1KDO'
__copyright__ = 'Copyright 2016, 2017, 2019, 2024 Jeffrey B. Otterson'
__license__ = 'Simplified BSD'

config = Config()
BROADCAST_BUF_SIZE = 2048

run = True

class Operators:
    operators = {}
    db = None
    cursor = None

    def __init__(self, db, cursor):
        self.db = db
        self.cursor = cursor
        # load operators
        self.cursor.execute('SELECT id, name FROM operator;')
        for row in self.cursor:
            self.operators[row[1]] = row[0]

    def lookup_operator_id(self, operator):
        """
        lookup the operator id for the supplied operator text.
        if the operator is not found, create it.
        """
        oid = self.operators.get(operator)
        if oid is None:
            self.cursor.execute("insert into operator (name) values (?);", (operator,))
            self.db.commit()
            oid = self.cursor.lastrowid
            self.operators[operator] = oid
        return oid


class Stations:
    stations = {}
    db = None
    cursor = None

    def __init__(self, db, cursor):
        self.db = db
        self.cursor = cursor
        self.cursor.execute('SELECT id, name FROM station;')
        for row in self.cursor:
            self.stations[row[1]] = row[0]

    def lookup_station_id(self, station):
        sid = self.stations.get(station)
        if sid is None:
            self.cursor.execute('insert into station (name) values (?);', (station,))
            self.db.commit()
            sid = self.cursor.lastrowid
            self.stations[station] = sid
        return sid


class N1mmMessageParser:
    """
    this is a cheap and dirty class to parse N1MM+ broadcast messages.
    It accepts the message and returns a dict, keyed by the element name.
    This is unsuitable for any other purpose, since it throws away the
    outer _contactinfo_ (or whatever) element -- instead it returns the name of
    the outer element as the value of the __messagetype__ key.
    OTOH, hopefully it is faster than using the DOM-based minidom.parse
    """
    result = {}
    lastElementName = None
    lastElementValue = None

    def __init__(self):
        self.parser = None
        self.result = None
        self.lastElementValue = None
        self.lastElementName = None

    def parse(self, data):
        self.parser = xml.parsers.expat.ParserCreate()
        self.parser.StartElementHandler = self.start_element
        self.parser.EndElementHandler = self.end_element
        self.parser.CharacterDataHandler = self.char_data
        self.lastElementValue = None
        self.lastElementName = None

        self.result = {}
        self.parser.Parse(data)
        return self.result

    def start_element(self, name, attrs):
        if self.lastElementName is not None:
            self.result['__messagetype__'] = self.lastElementName
        self.lastElementName = name
        self.lastElementValue = None

    def end_element(self, name):
        if self.lastElementName is not None and self.lastElementValue is not None:
            self.result[self.lastElementName] = self.lastElementValue
        self.lastElementName = None
        self.lastElementValue = None

    def char_data(self, data):
        self.lastElementValue = data


def compress_message(msg):
    new_msg = bytearray()
    state = 0
    count = 0
    for byte in msg:
        if state == 0 and byte == 10:
            state = 1
            continue
        elif state == 1 and byte == 32:
            continue
        else:
            state = 0
            new_msg.append(byte)
            count += 1
    return new_msg


def checksum(data):
    """
    generate a unique ID for each QSO.
    this is using md5 rather than crc32 because it is hoped that md5 will have less collisions.
    """
    hval = data['timestamp'] + data['StationName'] + data['contestnr'] + data['call']
    return int(hashlib.md5(hval.encode()).hexdigest(), 16)


def convert_timestamp(s):
    """
    convert the N1MM+ timestamp into a python time object.
    """
    return time.strptime(s, '%Y-%m-%d %H:%M:%S')


_dropped_apps_logged = set()


def process_message(parser, db, cursor, operators, stations, message, seen, src_addr=None):
    """
    Process a N1MM+ contactinfo message.

    Validates input data and logs warnings for malformed messages rather than
    raising exceptions, to ensure the collector continues running even when
    receiving bad data.
    """
    message = compress_message(message)

    # Parse XML with error handling
    try:
        data = parser.parse(message)
    except xml.parsers.expat.ExpatError as e:
        logging.warning(f'Malformed XML in UDP message: {e}')
        logging.debug(f'Raw message: {message}')
        return

    # App allow-list: drop messages whose <app> field is not in the
    # configured set. Messages without an app field pass through.
    allowed = getattr(config, 'ALLOWED_APPS', None)
    if allowed:
        sender = data.get('app')
        if sender is not None and sender.strip().lower() not in allowed:
            # Log the first drop per (app, message type) at WARNING so a
            # silently-dropped RadioInfo/contactinfo is visible; throttle the
            # repeats to DEBUG to avoid flooding the log.
            msg_type = data.get('__messagetype__', '?')
            key = (sender.strip().lower(), msg_type)
            if key not in _dropped_apps_logged:
                _dropped_apps_logged.add(key)
                logging.warning('Dropping %s message(s) from app=%r (not in ALLOWED_APPS=%s)',
                                msg_type, sender, sorted(allowed))
            else:
                logging.debug('Dropped %s message from app=%r', msg_type, sender)
            return

    logging.debug(f'{data}')
    message_type = data.get('__messagetype__', '')
    logging.debug(f'Received UDP message {message_type}')

    # Match the message type case-insensitively so a TR4W/N1MM variant that
    # spells the root element differently (e.g. <Radioinfo>) is still handled.
    mt = message_type.lower()
    if mt in ('contactinfo', 'contactreplace'):
        _process_contact(data, db, cursor, operators, stations)
    elif mt == 'radioinfo':
        _process_radio_info(data, db, cursor, src_addr)
    elif mt == 'contactdelete':
        _process_contact_delete(data, db, cursor)
    elif mt == 'dynamicresults':
        logging.debug('Received Score message')
    else:
        logging.warning(f'unknown message type "{message_type}" received, ignoring.')
        logging.debug(message)


def _process_contact(data, db, cursor, operators, stations):
    """Process a contactinfo or contactreplace message with validation."""
    qso_id = data.get('ID', '')

    # If no ID tag from N1MM, generate a hash for uniqueness
    if len(qso_id) == 0:
        # Validate required fields for checksum
        required_fields = ['timestamp', 'StationName', 'contestnr', 'call']
        missing = [f for f in required_fields if f not in data]
        if missing:
            logging.warning(f'Contact message missing required fields for checksum: {missing}')
            logging.debug(f'Message data: {data}')
            return
        qso_id = checksum(data)
    else:
        qso_id = qso_id.replace('-', '')

    # Validate timestamp
    qso_timestamp = data.get('timestamp')
    if not qso_timestamp:
        logging.warning('Contact message missing timestamp field')
        logging.debug(f'Message data: {data}')
        return

    try:
        timestamp = convert_timestamp(qso_timestamp)
    except ValueError as e:
        logging.warning(f'Contact message has invalid timestamp format "{qso_timestamp}": {e}')
        logging.debug(f'Message data: {data}')
        return

    # Validate frequencies
    rx_freq_str = data.get('rxfreq')
    tx_freq_str = data.get('txfreq')

    if rx_freq_str is None:
        logging.warning('Contact message missing rxfreq field')
        logging.debug(f'Message data: {data}')
        return
    if tx_freq_str is None:
        logging.warning('Contact message missing txfreq field')
        logging.debug(f'Message data: {data}')
        return

    try:
        rx_freq = int(rx_freq_str) * 10  # convert to Hz
    except ValueError:
        logging.warning(f'Contact message has invalid rxfreq "{rx_freq_str}"')
        logging.debug(f'Message data: {data}')
        return

    try:
        tx_freq = int(tx_freq_str) * 10
    except ValueError:
        logging.warning(f'Contact message has invalid txfreq "{tx_freq_str}"')
        logging.debug(f'Message data: {data}')
        return

    # Validate frequencies are non-negative
    if rx_freq < 0:
        logging.warning(f'Contact message has negative rxfreq: {rx_freq}')
        logging.debug(f'Message data: {data}')
        return
    if tx_freq < 0:
        logging.warning(f'Contact message has negative txfreq: {tx_freq}')
        logging.debug(f'Message data: {data}')
        return

    # Extract remaining fields with defaults
    mycall = data.get('mycall', '').upper()
    band = data.get('band')
    mode = data.get('mode', '').upper()
    operator = data.get('operator', '').upper()
    # QSO/station identity: friendly StationName (with NetBiosName as a last resort).
    # This is what the by-station QSO counts display, so keep it human-readable and
    # stable across the contest.
    station = (data.get('StationName', '') or data.get('NetBiosName', '')).upper()
    # Radio-panel identity: the machine name, which is the ONLY identifier both
    # packet types agree on. ContactInfo carries <StationName> (friendly, "STATION1")
    # AND <NetBiosName> (machine, "STATION-1"); RadioInfo carries only <StationName>,
    # and there it holds the machine name. Keying the radio fallback row on the
    # machine name (NetBiosName, else StationName) makes it match the RadioInfo row
    # for the same PC, so one station no longer shows twice ("STATION1" vs
    # "STATION-1") on the radio panel.
    radio_station = (data.get('NetBiosName', '') or data.get('StationName', '')).upper()
    callsign = data.get('call', '').upper()
    rst_sent = data.get('snt')
    rst_recv = data.get('rcv')
    exchange = data.get('exchange1', '').upper()
    section = data.get('section', '').upper()
    comment = data.get('comment', '')

    # Prefix multiplier (e.g. CQ WPX): TR4W/N1MM send the scored WPX prefix.
    prefix = data.get('wpxprefix', '').upper()

    # Zone multiplier: TR4W/N1MM carry a single <zone> field whose meaning is
    # contest-dependent -- the ITU zone for IARU HF, the CQ zone for CQ contests.
    # Route it to the matching column based on the configured multiplier type so
    # the map query can read the right one. (exchange1 also holds it, e.g.
    # "59 8", but <zone> is already parsed to just the number.)
    zone = data.get('zone', '').strip()
    ituzone = zone if config.MULTS == 'ITUZONES' else ''
    cqzone = zone if config.MULTS == 'CQZONES' else ''

    # Maidenhead grid multiplier (VHF/UHF contests): the worked station's grid
    # square. Only stored in GRID mode; the map computes each cell from this.
    grid = data.get('gridsquare', '').upper() if config.MULTS == 'GRID' else ''

    # Extract state from section when in STATES multiplier mode
    if config.MULTS == 'STATES':
        state = section
    else:
        state = ''

    dataaccess.record_contact_combined(db, cursor, operators, stations,
                                       timestamp, mycall, band, mode, operator, station,
                                       rx_freq, tx_freq, callsign, rst_sent, rst_recv,
                                       exchange, section, comment, qso_id, state=state,
                                       ituzone=ituzone, cqzone=cqzone, prefix=prefix, grid=grid)

    # Fallback radio display: keep the station visible on the radio panel from
    # its QSO traffic even if its RadioInfo broadcasts aren't being received.
    # Only fills in when no real RadioInfo row exists for the station. Keyed by the
    # machine name so it shares an identity with the RadioInfo rows (see above).
    dataaccess.record_radio_info_from_contact(db, cursor, radio_station, rx_freq, mode,
                                              operator, int(time.time()))


def _process_radio_info(data, db, cursor, src_addr=None):
    """Process a RadioInfo message with validation."""
    logging.debug('Received RadioInfo message')
    # Same identity rule as _process_contact: NetBiosName (machine name) if present,
    # else StationName. RadioInfo carries only <StationName>, which holds the machine
    # name, so this resolves to the same key ContactInfo uses for the same PC.
    station_name = (data.get('NetBiosName', '') or data.get('StationName', '')).upper()

    # Validate numeric fields with defaults
    try:
        radio_nr = int(data.get('RadioNr', '1'))
    except ValueError:
        logging.warning(f'RadioInfo has invalid RadioNr "{data.get("RadioNr")}", using default 1')
        radio_nr = 1

    try:
        freq = int(data.get('Freq', '0')) * 10  # convert from 10Hz units to Hz
    except ValueError:
        logging.warning(f'RadioInfo has invalid Freq "{data.get("Freq")}", using default 0')
        freq = 0

    try:
        tx_freq = int(data.get('TXFreq', '0')) * 10
    except ValueError:
        logging.warning(f'RadioInfo has invalid TXFreq "{data.get("TXFreq")}", using default 0')
        tx_freq = 0

    try:
        antenna = int(data.get('Antenna', '0'))
    except ValueError:
        logging.warning(f'RadioInfo has invalid Antenna "{data.get("Antenna")}", using default 0')
        antenna = 0

    mode = data.get('Mode', '').upper()
    op_call = data.get('OpCall', '').upper()
    is_running = 1 if data.get('IsRunning', 'False') == 'True' else 0
    is_transmitting = 1 if data.get('IsTransmitting', 'False') == 'True' else 0
    is_connected = 1 if data.get('IsConnected', 'False') == 'True' else 0
    is_split = 1 if data.get('IsSplit', 'False') == 'True' else 0
    radio_name = data.get('RadioName', '')
    last_update = int(time.time())

    # Check if this radio is the active one
    try:
        active_radio_nr = int(data.get('ActiveRadioNr', '0'))
    except ValueError:
        active_radio_nr = 0
    is_active = 1 if radio_nr == active_radio_nr else 0

    dataaccess.record_radio_info(db, cursor, station_name, radio_nr, freq, tx_freq,
                                 mode, op_call, is_running, is_transmitting,
                                 is_connected, is_split, is_active, radio_name, antenna,
                                 last_update)

    # Log every recorded RadioInfo so we can confirm which stations are actually
    # broadcasting radio data and under what (station_name, radio_nr) key. Note a
    # blank station_name here means the sender omitted both NetBiosName and
    # StationName, which would collide with any other blank-named station on the
    # same radio_nr.
    src_ip = src_addr[0] if src_addr else '?'
    logging.info('RadioInfo recorded: src_ip=%s station_name=%r radio_nr=%d freq=%d mode=%r op_call=%r',
                 src_ip, station_name, radio_nr, freq, mode, op_call)


def _process_contact_delete(data, db, cursor):
    """Process a contactdelete message with validation."""
    qso_id = data.get('ID') or ''

    # If no ID tag from N1MM, generate a hash for uniqueness
    if len(qso_id) == 0:
        # Validate required fields for checksum
        required_fields = ['timestamp', 'StationName', 'contestnr', 'call']
        missing = [f for f in required_fields if f not in data]
        if missing:
            logging.warning(f'contactdelete message missing required fields: {missing}')
            logging.debug(f'Message data: {data}')
            return
        qso_id = checksum(data)
    else:
        qso_id = qso_id.replace('-', '')

    logging.info(f'Delete QSO Request with ID {qso_id}')
    dataaccess.delete_contact_by_qso_id(db, cursor, qso_id)


def message_processor(q, event):
    global run
    logging.info('collector message_processor starting.')
    message_count = 0
    seen = set()
    db = sqlite3.connect(config.DATABASE_FILENAME)
    try:
        cursor = db.cursor()
        dataaccess.create_tables(db, cursor)
        dataaccess.clear_radio_info(db, cursor)

        operators = Operators(db, cursor)
        stations = Stations(db, cursor)
        parser = N1mmMessageParser()

        thread_run = True
        while not event.is_set() and thread_run:
            try:
                udp_data, src_addr = q.get()
                message_count += 1
                process_message(parser, db, cursor, operators, stations, udp_data, seen, src_addr)
            except KeyboardInterrupt:
                logging.debug('message processor stopping due to keyboard interrupt')
                thread_run = False
    finally:
        db.close()
        logging.info('db closed')
        run = False
        logging.info(f'collector message_processor exited, {message_count} messages collected.')


def main():
    try:
        logging.info('Collector started...')
        receive_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        process_event = None
        proc = None
        forward_socket = None
        try:
            receive_socket.bind(('', config.N1MM_BROADCAST_PORT))

            # Optional fan-out: if UDP_FORWARD_PORT is set, re-send each received
            # datagram verbatim to that port on localhost so a co-located
            # consumer (e.g. the Club Log gateway on its own N1MM port) gets it.
            forward_dest = (('127.0.0.1', config.UDP_FORWARD_PORT)
                            if config.UDP_FORWARD_PORT else None)
            if forward_dest:
                forward_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

            q = multiprocessing.Queue()
            process_event = multiprocessing.Event()

            proc = multiprocessing.Process(name='message_processor', target=message_processor, args=(q, process_event))
            proc.start()

            receive_socket.settimeout(5)
            global run
            while run:
                try:
                    udp_data, src_addr = receive_socket.recvfrom(BROADCAST_BUF_SIZE)
                    q.put((udp_data, src_addr))
                    # Fan-out a verbatim copy to the forward target, if set.
                    # Never let a forwarding error interfere with collection.
                    if forward_dest:
                        try:
                            forward_socket.sendto(udp_data, forward_dest)
                        except OSError as fe:
                            logging.warning('UDP forward to %s:%d failed: %s',
                                            forward_dest[0], forward_dest[1], fe)
                except socket.timeout:
                    pass
        finally:
            if receive_socket is not None:
                receive_socket.close()
            if forward_socket is not None:
                forward_socket.close()
            if process_event is not None:
                process_event.set()
            if proc is not None:
                proc.join(60)
                if proc.is_alive():
                    logging.warning('message processor did not exit upon request, killing.')
                    proc.terminate()
    except KeyboardInterrupt:
        pass

    logging.info('Collector done...')


if __name__ == '__main__':
    main()
