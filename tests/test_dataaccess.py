"""
Tests for dataaccess.py - Database operations and query functions.

Uses in-memory SQLite database for fast, isolated tests.
"""
import pytest
import sqlite3
import sys
import os
import time
import calendar

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dataaccess
import constants


class MockOperators:
    """Mock Operators class for testing without real DB initialization."""

    def __init__(self, db, cursor):
        self.db = db
        self.cursor = cursor
        self.operators = {}
        self.next_id = 1

    def lookup_operator_id(self, operator):
        if operator not in self.operators:
            self.cursor.execute("INSERT INTO operator (name) VALUES (?);", (operator,))
            self.db.commit()
            self.operators[operator] = self.cursor.lastrowid
        return self.operators[operator]


class MockStations:
    """Mock Stations class for testing without real DB initialization."""

    def __init__(self, db, cursor):
        self.db = db
        self.cursor = cursor
        self.stations = {}

    def lookup_station_id(self, station):
        if station not in self.stations:
            self.cursor.execute("INSERT INTO station (name) VALUES (?);", (station,))
            self.db.commit()
            self.stations[station] = self.cursor.lastrowid
        return self.stations[station]


@pytest.fixture
def db():
    """Create an in-memory SQLite database with tables."""
    conn = sqlite3.connect(':memory:')
    cursor = conn.cursor()
    dataaccess.create_tables(conn, cursor)
    yield conn, cursor
    conn.close()


@pytest.fixture
def db_with_helpers(db):
    """Database with mock Operators and Stations helpers."""
    conn, cursor = db
    operators = MockOperators(conn, cursor)
    stations = MockStations(conn, cursor)
    return conn, cursor, operators, stations


class TestCreateTables:
    """Tests for database schema creation."""

    def test_creates_operator_table(self, db):
        """Test operator table is created."""
        conn, cursor = db
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='operator';")
        assert cursor.fetchone() is not None

    def test_creates_station_table(self, db):
        """Test station table is created."""
        conn, cursor = db
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='station';")
        assert cursor.fetchone() is not None

    def test_creates_qso_log_table(self, db):
        """Test qso_log table is created."""
        conn, cursor = db
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='qso_log';")
        assert cursor.fetchone() is not None

    def test_creates_radio_info_table(self, db):
        """Test radio_info table is created."""
        conn, cursor = db
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='radio_info';")
        assert cursor.fetchone() is not None

    def test_qso_log_has_state_column(self, db):
        """Test qso_log has state column."""
        conn, cursor = db
        cursor.execute("PRAGMA table_info(qso_log);")
        columns = [row[1] for row in cursor.fetchall()]
        assert 'state' in columns

    def test_idempotent_creation(self, db):
        """Test tables can be created multiple times without error."""
        conn, cursor = db
        # Should not raise
        dataaccess.create_tables(conn, cursor)
        dataaccess.create_tables(conn, cursor)


class TestRadioInfo:
    """Tests for radio info recording and retrieval."""

    def test_record_radio_info(self, db):
        """Test recording radio info."""
        conn, cursor = db
        now = int(time.time())

        dataaccess.record_radio_info(
            conn, cursor,
            station_name='Station1',
            radio_nr=1,
            freq=14250000,
            tx_freq=14250000,
            mode='CW',
            op_call='W1AW',
            is_running=1,
            is_transmitting=0,
            is_connected=1,
            is_split=0,
            is_active=1,
            radio_name='IC-7300',
            antenna=1,
            last_update=now
        )

        radios = dataaccess.get_radio_info(cursor)
        assert len(radios) == 1
        assert radios[0]['station_name'] == 'Station1'
        assert radios[0]['freq'] == 14250000
        assert radios[0]['mode'] == 'CW'
        assert radios[0]['is_active'] == 1

    def test_update_radio_info(self, db):
        """Test updating existing radio info (upsert)."""
        conn, cursor = db
        now = int(time.time())

        # Insert first
        dataaccess.record_radio_info(
            conn, cursor,
            station_name='Station1', radio_nr=1,
            freq=14250000, tx_freq=14250000, mode='CW', op_call='W1AW',
            is_running=1, is_transmitting=0, is_connected=1, is_split=0,
            is_active=1, radio_name='IC-7300', antenna=1, last_update=now
        )

        # Update same station/radio
        dataaccess.record_radio_info(
            conn, cursor,
            station_name='Station1', radio_nr=1,
            freq=7125000, tx_freq=7125000, mode='SSB', op_call='K1ABC',
            is_running=1, is_transmitting=1, is_connected=1, is_split=0,
            is_active=0, radio_name='IC-7300', antenna=1, last_update=now + 10
        )

        radios = dataaccess.get_radio_info(cursor)
        assert len(radios) == 1  # Still just one record
        assert radios[0]['freq'] == 7125000
        assert radios[0]['mode'] == 'SSB'
        assert radios[0]['op_call'] == 'K1ABC'
        assert radios[0]['is_active'] == 0

    def test_multiple_radios(self, db):
        """Test multiple radios are returned in order."""
        conn, cursor = db
        now = int(time.time())

        # Add Station2 first to test ordering
        dataaccess.record_radio_info(
            conn, cursor,
            station_name='Station2', radio_nr=1,
            freq=7000000, tx_freq=7000000, mode='CW', op_call='N1KDO',
            is_running=1, is_transmitting=0, is_connected=1, is_split=0,
            is_active=0, radio_name='FT-991A', antenna=1, last_update=now
        )

        dataaccess.record_radio_info(
            conn, cursor,
            station_name='Station1', radio_nr=1,
            freq=14000000, tx_freq=14000000, mode='SSB', op_call='W1AW',
            is_running=1, is_transmitting=0, is_connected=1, is_split=0,
            is_active=1, radio_name='IC-7300', antenna=1, last_update=now
        )

        radios = dataaccess.get_radio_info(cursor)
        assert len(radios) == 2
        # Should be ordered by station_name
        assert radios[0]['station_name'] == 'Station1'
        assert radios[1]['station_name'] == 'Station2'
        assert radios[0]['is_active'] == 1
        assert radios[1]['is_active'] == 0

    def test_get_radio_info_empty(self, db):
        """Test get_radio_info returns empty list when no radios."""
        conn, cursor = db
        radios = dataaccess.get_radio_info(cursor)
        assert radios == []

    def test_clear_radio_info(self, db):
        """Test clear_radio_info removes all radio entries."""
        conn, cursor = db
        now = int(time.time())

        # Add some radios
        dataaccess.record_radio_info(
            conn, cursor,
            station_name='Station1', radio_nr=1,
            freq=14000000, tx_freq=14000000, mode='CW', op_call='W1AW',
            is_running=1, is_transmitting=0, is_connected=1, is_split=0,
            is_active=1, radio_name='IC-7300', antenna=1, last_update=now
        )
        dataaccess.record_radio_info(
            conn, cursor,
            station_name='Station1', radio_nr=2,
            freq=7000000, tx_freq=7000000, mode='SSB', op_call='W1AW',
            is_running=0, is_transmitting=0, is_connected=1, is_split=0,
            is_active=0, radio_name='IC-7610', antenna=2, last_update=now
        )

        # Verify radios exist
        radios = dataaccess.get_radio_info(cursor)
        assert len(radios) == 2

        # Clear and verify empty
        dataaccess.clear_radio_info(conn, cursor)
        radios = dataaccess.get_radio_info(cursor)
        assert radios == []


class TestContactOperations:
    """Tests for QSO contact CRUD operations."""

    def _make_timestamp(self, year=2024, month=6, day=22, hour=18, minute=30, second=0):
        """Helper to create a time struct."""
        return time.strptime(f'{year}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}',
                             '%Y-%m-%d %H:%M:%S')

    def test_record_contact(self, db_with_helpers):
        """Test recording a contact."""
        conn, cursor, operators, stations = db_with_helpers
        ts = self._make_timestamp()

        dataaccess.record_contact(
            conn, cursor, operators, stations,
            timestamp=ts,
            mycall='W1AW',
            band='14',
            mode='CW',
            operator='OP1',
            station='Station1',
            rx_freq=14025000,
            tx_freq=14025000,
            callsign='K1ABC',
            rst_sent='599',
            rst_recv='599',
            exchange='2A',
            section='CT',
            comment='',
            qso_id='test-qso-1',
            state='CT'
        )

        cursor.execute('SELECT * FROM qso_log WHERE qso_id = ?', ('test-qso-1',))
        row = cursor.fetchone()
        assert row is not None
        assert row[8] == 'K1ABC'  # callsign

    def test_record_contact_combined_upsert(self, db_with_helpers):
        """Test record_contact_combined does upsert."""
        conn, cursor, operators, stations = db_with_helpers
        ts = self._make_timestamp()

        # Insert
        dataaccess.record_contact_combined(
            conn, cursor, operators, stations,
            timestamp=ts, mycall='W1AW', band='14', mode='CW',
            operator='OP1', station='Station1',
            rx_freq=14025000, tx_freq=14025000, callsign='K1ABC',
            rst_sent='599', rst_recv='599', exchange='2A', section='CT',
            comment='', qso_id='test-qso-1', state='CT'
        )

        # Update same qso_id with different data
        dataaccess.record_contact_combined(
            conn, cursor, operators, stations,
            timestamp=ts, mycall='W1AW', band='14', mode='CW',
            operator='OP1', station='Station1',
            rx_freq=14025000, tx_freq=14025000, callsign='K1ABC',
            rst_sent='599', rst_recv='599', exchange='3A', section='CT',  # Changed exchange
            comment='corrected', qso_id='test-qso-1', state='CT'
        )

        cursor.execute('SELECT COUNT(*) FROM qso_log')
        assert cursor.fetchone()[0] == 1  # Still just one record

        cursor.execute('SELECT exchange, comment FROM qso_log WHERE qso_id = ?', ('test-qso-1',))
        row = cursor.fetchone()
        assert row[0] == '3A'
        assert row[1] == 'corrected'

    def test_update_contact(self, db_with_helpers):
        """Test updating an existing contact."""
        conn, cursor, operators, stations = db_with_helpers
        ts = self._make_timestamp()

        # First insert
        dataaccess.record_contact(
            conn, cursor, operators, stations,
            timestamp=ts, mycall='W1AW', band='14', mode='CW',
            operator='OP1', station='Station1',
            rx_freq=14025000, tx_freq=14025000, callsign='K1ABC',
            rst_sent='599', rst_recv='599', exchange='2A', section='CT',
            comment='', qso_id='test-qso-1', state='CT'
        )

        # Update
        dataaccess.update_contact(
            conn, cursor, operators, stations,
            timestamp=ts, mycall='W1AW', band='14', mode='SSB',  # Changed mode
            operator='OP1', station='Station1',
            rx_freq=14250000, tx_freq=14250000, callsign='K1ABC',
            rst_sent='59', rst_recv='59', exchange='2A', section='CT',
            comment='updated', qso_id='test-qso-1', state='CT'
        )

        cursor.execute('SELECT mode_id, comment FROM qso_log WHERE qso_id = ?', ('test-qso-1',))
        row = cursor.fetchone()
        assert row[0] == constants.Modes.get_mode_number('SSB')
        assert row[1] == 'updated'

    def test_delete_contact_by_qso_id(self, db_with_helpers):
        """Test deleting a contact by qso_id."""
        conn, cursor, operators, stations = db_with_helpers
        ts = self._make_timestamp()

        dataaccess.record_contact(
            conn, cursor, operators, stations,
            timestamp=ts, mycall='W1AW', band='14', mode='CW',
            operator='OP1', station='Station1',
            rx_freq=14025000, tx_freq=14025000, callsign='K1ABC',
            rst_sent='599', rst_recv='599', exchange='2A', section='CT',
            comment='', qso_id='test-qso-1', state='CT'
        )

        cursor.execute('SELECT COUNT(*) FROM qso_log')
        assert cursor.fetchone()[0] == 1

        dataaccess.delete_contact_by_qso_id(conn, cursor, 'test-qso-1')

        cursor.execute('SELECT COUNT(*) FROM qso_log')
        assert cursor.fetchone()[0] == 0

    def test_record_contact_invalid_band_ignored(self, db_with_helpers):
        """Test that contacts with invalid band are not recorded."""
        conn, cursor, operators, stations = db_with_helpers
        ts = self._make_timestamp()

        dataaccess.record_contact(
            conn, cursor, operators, stations,
            timestamp=ts, mycall='W1AW', band='INVALID', mode='CW',
            operator='OP1', station='Station1',
            rx_freq=14025000, tx_freq=14025000, callsign='K1ABC',
            rst_sent='599', rst_recv='599', exchange='2A', section='CT',
            comment='', qso_id='test-qso-invalid', state='CT'
        )

        cursor.execute('SELECT COUNT(*) FROM qso_log')
        assert cursor.fetchone()[0] == 0


class TestQueryFunctions:
    """Tests for aggregate query functions."""

    @pytest.fixture
    def populated_db(self, db_with_helpers):
        """Database with sample QSO data."""
        conn, cursor, operators, stations = db_with_helpers

        # Insert multiple QSOs
        test_qsos = [
            ('2024-06-22 18:00:00', 'W1AW', '14', 'CW', 'OP1', 'Station1', 14025000, 'K1ABC', '2A', 'CT', 'CT'),
            ('2024-06-22 18:05:00', 'W1AW', '14', 'CW', 'OP1', 'Station1', 14025000, 'W2DEF', '3A', 'NNJ', 'NJ'),
            ('2024-06-22 18:10:00', 'W1AW', '7', 'SSB', 'OP2', 'Station2', 7250000, 'N3GHI', '2A', 'EPA', 'PA'),
            ('2024-06-22 18:15:00', 'W1AW', '14', 'FT8', 'OP1', 'Station1', 14074000, 'K4JKL', '1D', 'VA', 'VA'),
            ('2024-06-22 18:20:00', 'W1AW', '7', 'CW', 'OP2', 'Station2', 7025000, 'W5MNO', '4A', 'STX', 'TX'),
        ]

        for i, qso in enumerate(test_qsos):
            ts = time.strptime(qso[0], '%Y-%m-%d %H:%M:%S')
            dataaccess.record_contact(
                conn, cursor, operators, stations,
                timestamp=ts, mycall=qso[1], band=qso[2], mode=qso[3],
                operator=qso[4], station=qso[5],
                rx_freq=qso[6], tx_freq=qso[6], callsign=qso[7],
                rst_sent='599', rst_recv='599', exchange=qso[8], section=qso[9],
                comment='', qso_id=f'qso-{i}', state=qso[10]
            )

        return conn, cursor, operators, stations

    def test_get_operators_by_qsos(self, populated_db):
        """Test getting QSO counts by operator."""
        conn, cursor, operators, stations = populated_db
        result = dataaccess.get_operators_by_qsos(cursor)

        assert len(result) == 2
        # Results are ordered by count DESC
        assert result[0][0] == 'OP1'
        assert result[0][1] == 3  # OP1 has 3 QSOs
        assert result[1][0] == 'OP2'
        assert result[1][1] == 2  # OP2 has 2 QSOs

    def test_get_station_qsos(self, populated_db):
        """Test getting QSO counts by station."""
        conn, cursor, operators, stations = populated_db
        result = dataaccess.get_station_qsos(cursor)

        assert len(result) == 2
        # Find Station1 and Station2 counts
        station_counts = {r[0]: r[1] for r in result}
        assert station_counts['Station1'] == 3
        assert station_counts['Station2'] == 2

    def test_get_qso_band_modes(self, populated_db):
        """Test getting band/mode matrix."""
        conn, cursor, operators, stations = populated_db
        result = dataaccess.get_qso_band_modes(cursor)

        # result is a 2D array: [band_index][simple_mode_index]
        # Band 14 (20m) = index 4, Band 7 (40m) = index 3
        # Simple modes: 0=N/A, 1=CW, 2=PHONE, 3=DATA

        # 20m: 2 CW, 1 FT8 (DATA)
        assert result[4][1] == 2  # 20m CW
        assert result[4][3] == 1  # 20m DATA (FT8)

        # 40m: 1 SSB, 1 CW
        assert result[3][1] == 1  # 40m CW
        assert result[3][2] == 1  # 40m PHONE (SSB)

    def test_get_qso_classes(self, populated_db):
        """Test getting QSO counts by exchange/class."""
        conn, cursor, operators, stations = populated_db
        result = dataaccess.get_qso_classes(cursor)

        # Should have counts for 2A, 3A, 1D, 4A
        exchanges = {r[1]: r[0] for r in result}
        assert exchanges['2A'] == 2  # Two 2A contacts
        assert exchanges['3A'] == 1
        assert exchanges['1D'] == 1
        assert exchanges['4A'] == 1

    def test_get_qso_categories(self, populated_db):
        """Test getting QSO counts by category letter."""
        conn, cursor, operators, stations = populated_db
        result = dataaccess.get_qso_categories(cursor)

        # Categories are last char of exchange: A, D
        categories = {r[1]: r[0] for r in result}
        assert categories['A'] == 4  # 2A, 3A, 2A, 4A
        assert categories['D'] == 1  # 1D

    def test_get_qsos_by_section(self, populated_db):
        """Test getting QSO counts by section."""
        conn, cursor, operators, stations = populated_db
        result = dataaccess.get_qsos_by_section(cursor)

        assert result['CT'] == 1
        assert result['NNJ'] == 1
        assert result['EPA'] == 1
        assert result['VA'] == 1
        assert result['STX'] == 1

    def test_get_qsos_by_state(self, populated_db):
        """Test getting QSO counts by state."""
        conn, cursor, operators, stations = populated_db
        result = dataaccess.get_qsos_by_state(cursor)

        assert result['CT'] == 1
        assert result['NJ'] == 1
        assert result['PA'] == 1
        assert result['VA'] == 1
        assert result['TX'] == 1

    def test_get_last_qso(self, populated_db):
        """Test getting the last QSO."""
        conn, cursor, operators, stations = populated_db
        last_time, message = dataaccess.get_last_qso(cursor)

        # Last QSO was at 18:20:00 on 2024-06-22
        expected_time = calendar.timegm(time.strptime('2024-06-22 18:20:00', '%Y-%m-%d %H:%M:%S'))
        assert last_time == expected_time
        assert 'W5MNO' in message
        assert 'STX' in message

    def test_get_last_N_qsos(self, populated_db):
        """Test getting the last N QSOs."""
        conn, cursor, operators, stations = populated_db
        result = dataaccess.get_last_N_qsos(cursor, 3)

        assert len(result) == 3
        # Should be in reverse chronological order
        assert result[0][1] == 'W5MNO'  # Most recent
        assert result[1][1] == 'K4JKL'
        assert result[2][1] == 'N3GHI'

    def test_get_last_N_qsos_more_than_available(self, populated_db):
        """Test requesting more QSOs than exist."""
        conn, cursor, operators, stations = populated_db
        result = dataaccess.get_last_N_qsos(cursor, 100)

        assert len(result) == 5  # Only 5 exist


class TestEmptyDatabase:
    """Tests for query functions on empty database."""

    def test_get_operators_by_qsos_empty(self, db):
        """Test empty result for operators query."""
        conn, cursor = db
        result = dataaccess.get_operators_by_qsos(cursor)
        assert result == []

    def test_get_station_qsos_empty(self, db):
        """Test empty result for station query."""
        conn, cursor = db
        result = dataaccess.get_station_qsos(cursor)
        assert result == []

    def test_get_qso_band_modes_empty(self, db):
        """Test band/mode matrix is all zeros when empty."""
        conn, cursor = db
        result = dataaccess.get_qso_band_modes(cursor)

        # Should be a matrix of zeros
        for band in result:
            for mode_count in band:
                assert mode_count == 0

    def test_get_qsos_by_section_empty(self, db):
        """Test empty dict for section query."""
        conn, cursor = db
        result = dataaccess.get_qsos_by_section(cursor)
        assert result == {}

    def test_get_qsos_by_state_empty(self, db):
        """Test empty dict for state query."""
        conn, cursor = db
        result = dataaccess.get_qsos_by_state(cursor)
        assert result == {}

    def test_get_last_N_qsos_empty(self, db):
        """Test empty result for last N QSOs."""
        conn, cursor = db
        result = dataaccess.get_last_N_qsos(cursor, 10)
        assert result == []
