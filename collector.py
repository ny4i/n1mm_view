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


def process_message(parser, db, cursor, operators, stations, message, seen):
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

    logging.debug(f'{data}')
    message_type = data.get('__messagetype__', '')
    logging.debug(f'Received UDP message {message_type}')

    if message_type in ['contactinfo', 'contactreplace']:
        _process_contact(data, db, cursor, operators, stations)
    elif message_type == 'RadioInfo':
        _process_radio_info(data, db, cursor)
    elif message_type == 'contactdelete':
        _process_contact_delete(data, db, cursor)
    elif message_type == 'dynamicresults':
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
    station_name = data.get('StationName', '').upper()
    if station_name is None or station_name == '':
        station_name = data.get('NetBiosName', '')
    station = station_name.upper()
    callsign = data.get('call', '').upper()
    rst_sent = data.get('snt')
    rst_recv = data.get('rcv')
    exchange = data.get('exchange1', '').upper()
    section = data.get('section', '').upper()
    comment = data.get('comment', '')

    # Extract state from section when in STATES multiplier mode
    if config.MULTS == 'STATES':
        state = section
    else:
        state = ''

    dataaccess.record_contact_combined(db, cursor, operators, stations,
                                       timestamp, mycall, band, mode, operator, station,
                                       rx_freq, tx_freq, callsign, rst_sent, rst_recv,
                                       exchange, section, comment, qso_id, state=state)


def _process_radio_info(data, db, cursor):
    """Process a RadioInfo message with validation."""
    logging.debug('Received RadioInfo message')
    station_name = data.get('StationName', '').upper()
    if station_name == '':
        station_name = data.get('NetBiosName', '').upper()

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
                udp_data = q.get()
                message_count += 1
                process_message(parser, db, cursor, operators, stations, udp_data, seen)
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
        try:
            receive_socket.bind(('', config.N1MM_BROADCAST_PORT))

            q = multiprocessing.Queue()
            process_event = multiprocessing.Event()

            proc = multiprocessing.Process(name='message_processor', target=message_processor, args=(q, process_event))
            proc.start()

            receive_socket.settimeout(5)
            global run
            while run:
                try:
                    udp_data = receive_socket.recv(BROADCAST_BUF_SIZE)
                    q.put(udp_data)
                except socket.timeout:
                    pass
        finally:
            if receive_socket is not None:
                receive_socket.close()
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
