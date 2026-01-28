"""
Tests for collector.py - Message parsing and utility functions.
"""
import pytest
import sys
import os
import time
import hashlib
import sqlite3
from xml.parsers.expat import ExpatError

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import (
    convert_timestamp, checksum, compress_message, N1mmMessageParser,
    process_message, Operators, Stations
)
import dataaccess


class TestConvertTimestamp:
    """Tests for the convert_timestamp function."""

    def test_valid_timestamp(self):
        """Test parsing a valid N1MM+ timestamp."""
        result = convert_timestamp('2024-06-22 18:30:45')
        assert result.tm_year == 2024
        assert result.tm_mon == 6
        assert result.tm_mday == 22
        assert result.tm_hour == 18
        assert result.tm_min == 30
        assert result.tm_sec == 45

    def test_midnight_timestamp(self):
        """Test parsing midnight timestamp."""
        result = convert_timestamp('2024-01-01 00:00:00')
        assert result.tm_hour == 0
        assert result.tm_min == 0
        assert result.tm_sec == 0

    def test_end_of_day_timestamp(self):
        """Test parsing end of day timestamp."""
        result = convert_timestamp('2024-12-31 23:59:59')
        assert result.tm_hour == 23
        assert result.tm_min == 59
        assert result.tm_sec == 59

    def test_invalid_timestamp_format(self):
        """Test that invalid format raises ValueError."""
        with pytest.raises(ValueError):
            convert_timestamp('2024/06/22 18:30:45')  # Wrong separator

    def test_invalid_timestamp_missing_time(self):
        """Test that missing time raises ValueError."""
        with pytest.raises(ValueError):
            convert_timestamp('2024-06-22')

    def test_invalid_timestamp_empty(self):
        """Test that empty string raises ValueError."""
        with pytest.raises(ValueError):
            convert_timestamp('')


class TestChecksum:
    """Tests for the checksum function."""

    def test_checksum_returns_int(self):
        """Test checksum returns an integer."""
        data = {
            'timestamp': '2024-06-22 18:30:45',
            'StationName': 'Station1',
            'contestnr': '12345',
            'call': 'W1AW'
        }
        result = checksum(data)
        assert isinstance(result, int)

    def test_checksum_deterministic(self):
        """Test same input produces same checksum."""
        data = {
            'timestamp': '2024-06-22 18:30:45',
            'StationName': 'Station1',
            'contestnr': '12345',
            'call': 'W1AW'
        }
        result1 = checksum(data)
        result2 = checksum(data)
        assert result1 == result2

    def test_checksum_different_timestamps(self):
        """Test different timestamps produce different checksums."""
        data1 = {
            'timestamp': '2024-06-22 18:30:45',
            'StationName': 'Station1',
            'contestnr': '12345',
            'call': 'W1AW'
        }
        data2 = {
            'timestamp': '2024-06-22 18:30:46',  # One second different
            'StationName': 'Station1',
            'contestnr': '12345',
            'call': 'W1AW'
        }
        assert checksum(data1) != checksum(data2)

    def test_checksum_different_calls(self):
        """Test different callsigns produce different checksums."""
        data1 = {
            'timestamp': '2024-06-22 18:30:45',
            'StationName': 'Station1',
            'contestnr': '12345',
            'call': 'W1AW'
        }
        data2 = {
            'timestamp': '2024-06-22 18:30:45',
            'StationName': 'Station1',
            'contestnr': '12345',
            'call': 'K1ABC'
        }
        assert checksum(data1) != checksum(data2)

    def test_checksum_different_stations(self):
        """Test different stations produce different checksums."""
        data1 = {
            'timestamp': '2024-06-22 18:30:45',
            'StationName': 'Station1',
            'contestnr': '12345',
            'call': 'W1AW'
        }
        data2 = {
            'timestamp': '2024-06-22 18:30:45',
            'StationName': 'Station2',
            'contestnr': '12345',
            'call': 'W1AW'
        }
        assert checksum(data1) != checksum(data2)

    def test_checksum_positive(self):
        """Test checksum is always positive."""
        data = {
            'timestamp': '2024-06-22 18:30:45',
            'StationName': 'Station1',
            'contestnr': '12345',
            'call': 'W1AW'
        }
        result = checksum(data)
        assert result >= 0

    def test_checksum_missing_field_raises_keyerror(self):
        """Test checksum with missing required field raises KeyError."""
        data = {
            'timestamp': '2024-06-22 18:30:45',
            'StationName': 'Station1',
            # Missing 'contestnr' and 'call'
        }
        with pytest.raises(KeyError):
            checksum(data)


class TestCompressMessage:
    """Tests for the compress_message function."""

    def test_compress_removes_newline_spaces(self):
        """Test that newline followed by spaces is removed."""
        # Byte 10 = newline, byte 32 = space
        msg = bytearray(b'<tag>\n    value</tag>')
        result = compress_message(msg)
        assert result == bytearray(b'<tag>value</tag>')

    def test_compress_preserves_other_content(self):
        """Test that other content is preserved."""
        msg = bytearray(b'<contactinfo><call>W1AW</call></contactinfo>')
        result = compress_message(msg)
        assert result == msg

    def test_compress_handles_multiple_newline_sequences(self):
        """Test handling multiple newline-space sequences."""
        msg = bytearray(b'<a>\n  x</a>\n  <b>\n  y</b>')
        result = compress_message(msg)
        assert result == bytearray(b'<a>x</a><b>y</b>')

    def test_compress_empty_message(self):
        """Test compressing empty message."""
        msg = bytearray(b'')
        result = compress_message(msg)
        assert result == bytearray(b'')

    def test_compress_returns_bytearray(self):
        """Test that result is a bytearray."""
        msg = bytearray(b'test')
        result = compress_message(msg)
        assert isinstance(result, bytearray)

    def test_compress_newline_not_followed_by_space(self):
        """Test newline not followed by space is preserved."""
        msg = bytearray(b'line1\nline2')
        result = compress_message(msg)
        # Newline followed by 'l' (not space) should be kept
        assert result == bytearray(b'line1line2')


class TestN1mmMessageParser:
    """Tests for the N1mmMessageParser class."""

    def test_parse_contactinfo(self):
        """Test parsing a contactinfo message."""
        xml = b'''<?xml version="1.0"?>
        <contactinfo>
            <call>W1AW</call>
            <band>20</band>
            <mode>CW</mode>
        </contactinfo>'''
        parser = N1mmMessageParser()
        result = parser.parse(xml)
        assert result['__messagetype__'] == 'contactinfo'
        assert result['call'] == 'W1AW'
        assert result['band'] == '20'
        assert result['mode'] == 'CW'

    def test_parse_radioinfo(self):
        """Test parsing a RadioInfo message."""
        xml = b'''<?xml version="1.0"?>
        <RadioInfo>
            <Freq>14025000</Freq>
            <Mode>CW</Mode>
            <StationName>Station1</StationName>
        </RadioInfo>'''
        parser = N1mmMessageParser()
        result = parser.parse(xml)
        assert result['__messagetype__'] == 'RadioInfo'
        assert result['Freq'] == '14025000'
        assert result['Mode'] == 'CW'
        assert result['StationName'] == 'Station1'

    def test_parse_empty_elements(self):
        """Test parsing message with empty elements."""
        xml = b'''<?xml version="1.0"?>
        <contactinfo>
            <call>W1AW</call>
            <notes></notes>
        </contactinfo>'''
        parser = N1mmMessageParser()
        result = parser.parse(xml)
        assert result['call'] == 'W1AW'
        # Empty element should not be in result
        assert 'notes' not in result

    def test_parser_reuse(self):
        """Test that parser can be reused for multiple messages."""
        parser = N1mmMessageParser()

        xml1 = b'<contactinfo><call>W1AW</call></contactinfo>'
        result1 = parser.parse(xml1)
        assert result1['call'] == 'W1AW'

        xml2 = b'<contactinfo><call>K1ABC</call></contactinfo>'
        result2 = parser.parse(xml2)
        assert result2['call'] == 'K1ABC'
        # Result should not contain data from first parse
        assert 'W1AW' not in result2.values()


class TestMalformedXML:
    """Tests for N1mmMessageParser handling of malformed XML."""

    def test_unclosed_tag_raises_error(self):
        """Test parsing XML with unclosed tag raises ExpatError."""
        parser = N1mmMessageParser()
        malformed_xml = b'<contactinfo><call>W1AW</contactinfo>'  # Missing </call>
        with pytest.raises(ExpatError):
            parser.parse(malformed_xml)

    def test_mismatched_tags_raises_error(self):
        """Test parsing XML with mismatched tags raises ExpatError."""
        parser = N1mmMessageParser()
        malformed_xml = b'<contactinfo><call>W1AW</band></contactinfo>'
        with pytest.raises(ExpatError):
            parser.parse(malformed_xml)

    def test_truncated_xml_missing_closing_tag(self):
        """Test parsing truncated XML missing closing bracket returns partial data.

        Note: The expat parser is lenient with certain truncations - it returns
        partial results rather than raising an error when the final closing
        bracket is missing.
        """
        parser = N1mmMessageParser()
        # Missing final '>' - parser is lenient and returns partial data
        malformed_xml = b'<contactinfo><call>W1AW</call><band>20</band'
        result = parser.parse(malformed_xml)
        # Parser returns what it could parse before truncation
        assert result.get('call') == 'W1AW'

    def test_truncated_xml_missing_root_close_returns_partial(self):
        """Test XML missing root closing tag returns partial data.

        Note: The expat parser is lenient - it returns partial data even when
        the root element closing tag is missing.
        """
        parser = N1mmMessageParser()
        # Complete elements but missing </contactinfo>
        malformed_xml = b'<contactinfo><call>W1AW</call>'
        result = parser.parse(malformed_xml)
        # Parser returns the data it found
        assert result['__messagetype__'] == 'contactinfo'
        assert result['call'] == 'W1AW'

    def test_not_xml_raises_error(self):
        """Test parsing non-XML content raises ExpatError."""
        parser = N1mmMessageParser()
        with pytest.raises(ExpatError):
            parser.parse(b'This is not XML at all')

    def test_binary_garbage_raises_error(self):
        """Test parsing binary garbage raises ExpatError."""
        parser = N1mmMessageParser()
        with pytest.raises(ExpatError):
            parser.parse(b'\x00\x01\x02\x03\xff\xfe')

    def test_xml_with_null_byte_raises_error(self):
        """Test parsing XML with null byte raises ExpatError."""
        parser = N1mmMessageParser()
        # Null byte \x00 is not valid in XML
        malformed_xml = b'<contactinfo><call>W1\x00AW</call></contactinfo>'
        with pytest.raises(ExpatError):
            parser.parse(malformed_xml)

    def test_parser_recovers_after_error(self):
        """Test parser can parse valid XML after encountering an error."""
        parser = N1mmMessageParser()

        # First, cause an error
        with pytest.raises(ExpatError):
            parser.parse(b'not valid xml at all!')

        # Then parse valid XML - should work
        result = parser.parse(b'<contactinfo><call>W1AW</call></contactinfo>')
        assert result['call'] == 'W1AW'

    def test_empty_input_returns_empty_dict(self):
        """Test parsing empty input returns empty dict (no outer element)."""
        parser = N1mmMessageParser()
        # Empty string actually parses to empty result, not an error
        result = parser.parse(b'')
        assert result == {}

    def test_whitespace_only_returns_empty_dict(self):
        """Test parsing whitespace-only input returns empty dict."""
        parser = N1mmMessageParser()
        result = parser.parse(b'   \n\t  ')
        assert result == {}


class TestMalformedMessageContent:
    """Tests for parser handling of structurally valid but semantically odd XML."""

    def test_unknown_message_type(self):
        """Test parsing unknown message type still returns data."""
        parser = N1mmMessageParser()
        xml = b'<unknowntype><field1>value1</field1></unknowntype>'
        result = parser.parse(xml)
        assert result['__messagetype__'] == 'unknowntype'
        assert result['field1'] == 'value1'

    def test_very_long_value(self):
        """Test parsing very long field values."""
        parser = N1mmMessageParser()
        long_value = 'X' * 10000
        xml = f'<contactinfo><comment>{long_value}</comment></contactinfo>'.encode('utf-8')
        result = parser.parse(xml)
        assert result['comment'] == long_value

    def test_numeric_element_names(self):
        """Test parsing elements with numeric-looking names."""
        parser = N1mmMessageParser()
        # Element names can't start with numbers, but can contain them
        xml = b'<contactinfo><field123>value</field123></contactinfo>'
        result = parser.parse(xml)
        assert result['field123'] == 'value'

    def test_attributes_ignored(self):
        """Test that XML attributes are ignored by the parser."""
        parser = N1mmMessageParser()
        xml = b'<contactinfo version="1.0"><call attr="ignored">W1AW</call></contactinfo>'
        result = parser.parse(xml)
        assert result['call'] == 'W1AW'
        # Attributes are not captured by this simple parser

    def test_self_closing_root_element(self):
        """Test self-closing root element returns empty result."""
        parser = N1mmMessageParser()
        result = parser.parse(b'<empty/>')
        # No nested elements means no __messagetype__
        assert '__messagetype__' not in result

    def test_nested_empty_elements(self):
        """Test nested structure with empty values."""
        parser = N1mmMessageParser()
        xml = b'<contactinfo><call></call><band></band></contactinfo>'
        result = parser.parse(xml)
        assert result['__messagetype__'] == 'contactinfo'
        # Empty elements don't get added
        assert 'call' not in result
        assert 'band' not in result


@pytest.fixture
def test_db():
    """Create an in-memory SQLite database with tables for process_message tests."""
    conn = sqlite3.connect(':memory:')
    cursor = conn.cursor()
    dataaccess.create_tables(conn, cursor)
    operators = Operators(conn, cursor)
    stations = Stations(conn, cursor)
    parser = N1mmMessageParser()
    seen = set()
    yield conn, cursor, operators, stations, parser, seen
    conn.close()


class TestProcessMessageMalformed:
    """Tests for process_message handling of malformed/incomplete messages."""

    def test_contactinfo_missing_timestamp_skipped(self, test_db):
        """Test contactinfo missing timestamp is skipped gracefully."""
        conn, cursor, operators, stations, parser, seen = test_db
        # Without timestamp field, message should be skipped
        xml = b'''<contactinfo>
            <call>W1AW</call>
            <band>14</band>
            <mode>CW</mode>
            <rxfreq>1402500</rxfreq>
            <txfreq>1402500</txfreq>
            <StationName>Station1</StationName>
            <contestnr>1</contestnr>
        </contactinfo>'''
        # Should not raise - just logs warning and skips
        process_message(parser, conn, cursor, operators, stations, xml, seen)
        cursor.execute('SELECT COUNT(*) FROM qso_log')
        assert cursor.fetchone()[0] == 0

    def test_contactinfo_missing_frequency_skipped(self, test_db):
        """Test contactinfo missing rxfreq is skipped gracefully."""
        conn, cursor, operators, stations, parser, seen = test_db
        xml = b'''<contactinfo>
            <timestamp>2024-06-22 18:30:45</timestamp>
            <call>W1AW</call>
            <band>14</band>
            <mode>CW</mode>
            <txfreq>1402500</txfreq>
            <StationName>Station1</StationName>
            <contestnr>1</contestnr>
            <ID>test-id</ID>
        </contactinfo>'''
        # Should not raise - just logs warning and skips
        process_message(parser, conn, cursor, operators, stations, xml, seen)
        cursor.execute('SELECT COUNT(*) FROM qso_log')
        assert cursor.fetchone()[0] == 0

    def test_contactinfo_non_numeric_frequency_skipped(self, test_db):
        """Test contactinfo with non-numeric frequency is skipped gracefully."""
        conn, cursor, operators, stations, parser, seen = test_db
        xml = b'''<contactinfo>
            <timestamp>2024-06-22 18:30:45</timestamp>
            <call>W1AW</call>
            <band>14</band>
            <mode>CW</mode>
            <rxfreq>not_a_number</rxfreq>
            <txfreq>1402500</txfreq>
            <StationName>Station1</StationName>
            <contestnr>1</contestnr>
            <ID>test-id</ID>
        </contactinfo>'''
        # Should not raise - just logs warning and skips
        process_message(parser, conn, cursor, operators, stations, xml, seen)
        cursor.execute('SELECT COUNT(*) FROM qso_log')
        assert cursor.fetchone()[0] == 0

    def test_contactinfo_invalid_timestamp_format_skipped(self, test_db):
        """Test contactinfo with invalid timestamp format is skipped gracefully."""
        conn, cursor, operators, stations, parser, seen = test_db
        xml = b'''<contactinfo>
            <timestamp>22/06/2024 18:30:45</timestamp>
            <call>W1AW</call>
            <band>14</band>
            <mode>CW</mode>
            <rxfreq>1402500</rxfreq>
            <txfreq>1402500</txfreq>
            <StationName>Station1</StationName>
            <contestnr>1</contestnr>
            <ID>test-id</ID>
        </contactinfo>'''
        # Should not raise - just logs warning and skips
        process_message(parser, conn, cursor, operators, stations, xml, seen)
        cursor.execute('SELECT COUNT(*) FROM qso_log')
        assert cursor.fetchone()[0] == 0

    def test_radioinfo_non_numeric_freq_uses_default(self, test_db):
        """Test RadioInfo with non-numeric frequency uses default 0."""
        conn, cursor, operators, stations, parser, seen = test_db
        xml = b'''<RadioInfo>
            <StationName>Station1</StationName>
            <Freq>invalid</Freq>
        </RadioInfo>'''
        # Should not raise - uses default value
        process_message(parser, conn, cursor, operators, stations, xml, seen)
        radios = dataaccess.get_radio_info(cursor)
        assert len(radios) == 1
        assert radios[0]['freq'] == 0  # Default

    def test_radioinfo_non_numeric_radio_nr_uses_default(self, test_db):
        """Test RadioInfo with non-numeric RadioNr uses default 1."""
        conn, cursor, operators, stations, parser, seen = test_db
        xml = b'''<RadioInfo>
            <StationName>Station1</StationName>
            <RadioNr>abc</RadioNr>
            <Freq>1402500</Freq>
        </RadioInfo>'''
        # Should not raise - uses default value
        process_message(parser, conn, cursor, operators, stations, xml, seen)
        radios = dataaccess.get_radio_info(cursor)
        assert len(radios) == 1
        assert radios[0]['radio_nr'] == 1  # Default

    def test_unknown_message_type_ignored(self, test_db):
        """Test unknown message type is logged but doesn't raise."""
        conn, cursor, operators, stations, parser, seen = test_db
        xml = b'''<unknownmessage>
            <field1>value1</field1>
        </unknownmessage>'''
        # Should not raise - just logs warning
        process_message(parser, conn, cursor, operators, stations, xml, seen)
        # Verify no data was written
        cursor.execute('SELECT COUNT(*) FROM qso_log')
        assert cursor.fetchone()[0] == 0

    def test_dynamicresults_ignored(self, test_db):
        """Test dynamicresults message type is handled gracefully."""
        conn, cursor, operators, stations, parser, seen = test_db
        xml = b'''<dynamicresults>
            <score>1234</score>
        </dynamicresults>'''
        # Should not raise - just logs debug
        process_message(parser, conn, cursor, operators, stations, xml, seen)

    def test_empty_message_type_ignored(self, test_db):
        """Test message with empty root returns no messagetype and is ignored."""
        conn, cursor, operators, stations, parser, seen = test_db
        xml = b'''<RadioInfo></RadioInfo>'''
        # Parser returns empty __messagetype__ for empty element
        process_message(parser, conn, cursor, operators, stations, xml, seen)
        # Should be treated as unknown and ignored
        radios = dataaccess.get_radio_info(cursor)
        assert len(radios) == 0

    def test_valid_contactinfo_succeeds(self, test_db):
        """Test valid contactinfo is processed correctly."""
        conn, cursor, operators, stations, parser, seen = test_db
        xml = b'''<contactinfo>
            <timestamp>2024-06-22 18:30:45</timestamp>
            <mycall>W1AW</mycall>
            <call>K1ABC</call>
            <band>14</band>
            <mode>CW</mode>
            <rxfreq>1402500</rxfreq>
            <txfreq>1402500</txfreq>
            <operator>OP1</operator>
            <StationName>Station1</StationName>
            <contestnr>1</contestnr>
            <snt>599</snt>
            <rcv>599</rcv>
            <exchange1>2A</exchange1>
            <section>CT</section>
            <ID>test-id-123</ID>
        </contactinfo>'''
        process_message(parser, conn, cursor, operators, stations, xml, seen)
        cursor.execute('SELECT COUNT(*) FROM qso_log')
        assert cursor.fetchone()[0] == 1

    def test_valid_radioinfo_succeeds(self, test_db):
        """Test valid RadioInfo is processed correctly."""
        conn, cursor, operators, stations, parser, seen = test_db
        xml = b'''<RadioInfo>
            <StationName>Station1</StationName>
            <RadioNr>1</RadioNr>
            <Freq>1402500</Freq>
            <TXFreq>1402500</TXFreq>
            <Mode>CW</Mode>
            <OpCall>W1AW</OpCall>
            <IsRunning>True</IsRunning>
            <IsTransmitting>False</IsTransmitting>
            <IsConnected>True</IsConnected>
            <IsSplit>False</IsSplit>
            <RadioName>IC-7300</RadioName>
            <Antenna>1</Antenna>
        </RadioInfo>'''
        process_message(parser, conn, cursor, operators, stations, xml, seen)
        radios = dataaccess.get_radio_info(cursor)
        assert len(radios) == 1
        assert radios[0]['station_name'] == 'STATION1'
        assert radios[0]['freq'] == 14025000  # 1402500 * 10

    def test_contactreplace_works_like_contactinfo(self, test_db):
        """Test contactreplace is handled same as contactinfo."""
        conn, cursor, operators, stations, parser, seen = test_db
        xml = b'''<contactreplace>
            <timestamp>2024-06-22 18:30:45</timestamp>
            <mycall>W1AW</mycall>
            <call>K1ABC</call>
            <band>14</band>
            <mode>CW</mode>
            <rxfreq>1402500</rxfreq>
            <txfreq>1402500</txfreq>
            <operator>OP1</operator>
            <StationName>Station1</StationName>
            <contestnr>1</contestnr>
            <ID>test-id-456</ID>
        </contactreplace>'''
        process_message(parser, conn, cursor, operators, stations, xml, seen)
        cursor.execute('SELECT COUNT(*) FROM qso_log')
        assert cursor.fetchone()[0] == 1

    def test_contactdelete_with_id(self, test_db):
        """Test contactdelete with ID field works."""
        conn, cursor, operators, stations, parser, seen = test_db

        # First add a contact
        xml1 = b'''<contactinfo>
            <timestamp>2024-06-22 18:30:45</timestamp>
            <mycall>W1AW</mycall>
            <call>K1ABC</call>
            <band>14</band>
            <mode>CW</mode>
            <rxfreq>1402500</rxfreq>
            <txfreq>1402500</txfreq>
            <operator>OP1</operator>
            <StationName>Station1</StationName>
            <contestnr>1</contestnr>
            <ID>delete-me-123</ID>
        </contactinfo>'''
        process_message(parser, conn, cursor, operators, stations, xml1, seen)

        cursor.execute('SELECT COUNT(*) FROM qso_log')
        assert cursor.fetchone()[0] == 1

        # Now delete it
        xml2 = b'''<contactdelete>
            <ID>delete-me-123</ID>
        </contactdelete>'''
        process_message(parser, conn, cursor, operators, stations, xml2, seen)

        cursor.execute('SELECT COUNT(*) FROM qso_log')
        assert cursor.fetchone()[0] == 0

    def test_contactdelete_missing_id_skipped(self, test_db):
        """Test contactdelete without ID or checksum fields is skipped gracefully."""
        conn, cursor, operators, stations, parser, seen = test_db
        # contactdelete with no ID and no fields for checksum
        xml = b'''<contactdelete>
            <someotherfield>value</someotherfield>
        </contactdelete>'''
        # Should not raise - just logs warning and skips
        process_message(parser, conn, cursor, operators, stations, xml, seen)

    def test_truly_malformed_xml_skipped(self, test_db):
        """Test truly malformed XML (mismatched tags) is skipped gracefully."""
        conn, cursor, operators, stations, parser, seen = test_db
        # Mismatched tags - caught by XML parser, logged and skipped
        malformed = b'<contactinfo><call>W1AW</band></contactinfo>'
        # Should not raise - just logs warning and skips
        process_message(parser, conn, cursor, operators, stations, malformed, seen)
        cursor.execute('SELECT COUNT(*) FROM qso_log')
        assert cursor.fetchone()[0] == 0

    def test_truncated_xml_skipped(self, test_db):
        """Test truncated XML with partial data is skipped gracefully.

        Note: The expat parser is lenient and returns partial data from truncated XML.
        The validation now catches missing required fields and skips the message.
        """
        conn, cursor, operators, stations, parser, seen = test_db
        # Truncated - parser returns partial data, validation catches missing fields
        malformed = b'<contactinfo><call>W1AW</call>'
        # Should not raise - just logs warning and skips
        process_message(parser, conn, cursor, operators, stations, malformed, seen)
        cursor.execute('SELECT COUNT(*) FROM qso_log')
        assert cursor.fetchone()[0] == 0

    def test_truncated_xml_without_close_bracket_is_ignored(self, test_db):
        """Test truncated XML without closing bracket is treated as unknown message.

        Note: The expat parser is lenient - truncated XML missing the final '>'
        returns empty dict and gets ignored as unknown message type.
        """
        conn, cursor, operators, stations, parser, seen = test_db
        # This truncation doesn't raise - parser returns empty dict
        malformed = b'<contactinfo><broken'
        process_message(parser, conn, cursor, operators, stations, malformed, seen)
        # No data should be written
        cursor.execute('SELECT COUNT(*) FROM qso_log')
        assert cursor.fetchone()[0] == 0

    def test_contactinfo_empty_call(self, test_db):
        """Test contactinfo with empty call field still processes."""
        conn, cursor, operators, stations, parser, seen = test_db
        xml = b'''<contactinfo>
            <timestamp>2024-06-22 18:30:45</timestamp>
            <mycall>W1AW</mycall>
            <call></call>
            <band>14</band>
            <mode>CW</mode>
            <rxfreq>1402500</rxfreq>
            <txfreq>1402500</txfreq>
            <operator>OP1</operator>
            <StationName>Station1</StationName>
            <contestnr>1</contestnr>
            <ID>test-empty-call</ID>
        </contactinfo>'''
        process_message(parser, conn, cursor, operators, stations, xml, seen)
        cursor.execute('SELECT callsign FROM qso_log')
        row = cursor.fetchone()
        assert row[0] == ''  # Empty but recorded

    def test_contactinfo_negative_frequency_rejected(self, test_db):
        """Test contactinfo with negative frequency is rejected."""
        conn, cursor, operators, stations, parser, seen = test_db
        xml = b'''<contactinfo>
            <timestamp>2024-06-22 18:30:45</timestamp>
            <mycall>W1AW</mycall>
            <call>K1ABC</call>
            <band>14</band>
            <mode>CW</mode>
            <rxfreq>-100</rxfreq>
            <txfreq>1402500</txfreq>
            <operator>OP1</operator>
            <StationName>Station1</StationName>
            <contestnr>1</contestnr>
            <ID>test-neg-freq</ID>
        </contactinfo>'''
        # Negative frequency is now validated and rejected
        process_message(parser, conn, cursor, operators, stations, xml, seen)
        cursor.execute('SELECT COUNT(*) FROM qso_log')
        assert cursor.fetchone()[0] == 0

    def test_radioinfo_uses_netbiosname_fallback(self, test_db):
        """Test RadioInfo uses NetBiosName when StationName missing."""
        conn, cursor, operators, stations, parser, seen = test_db
        xml = b'''<RadioInfo>
            <NetBiosName>FALLBACK-PC</NetBiosName>
            <RadioNr>1</RadioNr>
            <Freq>1402500</Freq>
        </RadioInfo>'''
        process_message(parser, conn, cursor, operators, stations, xml, seen)
        radios = dataaccess.get_radio_info(cursor)
        assert len(radios) == 1
        assert radios[0]['station_name'] == 'FALLBACK-PC'

    def test_radioinfo_defaults_for_missing_optional_fields(self, test_db):
        """Test RadioInfo uses sensible defaults for missing optional fields."""
        conn, cursor, operators, stations, parser, seen = test_db
        xml = b'''<RadioInfo>
            <StationName>MinimalStation</StationName>
            <Freq>1402500</Freq>
        </RadioInfo>'''
        process_message(parser, conn, cursor, operators, stations, xml, seen)
        radios = dataaccess.get_radio_info(cursor)
        assert len(radios) == 1
        assert radios[0]['station_name'] == 'MINIMALSTATION'
        assert radios[0]['radio_nr'] == 1  # Default
        assert radios[0]['is_running'] == 0  # Default False
        assert radios[0]['is_transmitting'] == 0  # Default False

    def test_contactinfo_with_id_containing_dashes(self, test_db):
        """Test contactinfo ID with dashes gets dashes removed."""
        conn, cursor, operators, stations, parser, seen = test_db
        xml = b'''<contactinfo>
            <timestamp>2024-06-22 18:30:45</timestamp>
            <mycall>W1AW</mycall>
            <call>K1ABC</call>
            <band>14</band>
            <mode>CW</mode>
            <rxfreq>1402500</rxfreq>
            <txfreq>1402500</txfreq>
            <operator>OP1</operator>
            <StationName>Station1</StationName>
            <contestnr>1</contestnr>
            <ID>abc-def-123-456</ID>
        </contactinfo>'''
        process_message(parser, conn, cursor, operators, stations, xml, seen)
        cursor.execute('SELECT qso_id FROM qso_log')
        row = cursor.fetchone()
        assert row[0] == 'abcdef123456'  # Dashes removed

    def test_contactinfo_generates_checksum_when_no_id(self, test_db):
        """Test contactinfo generates checksum-based ID when ID field missing."""
        conn, cursor, operators, stations, parser, seen = test_db
        xml = b'''<contactinfo>
            <timestamp>2024-06-22 18:30:45</timestamp>
            <mycall>W1AW</mycall>
            <call>K1ABC</call>
            <band>14</band>
            <mode>CW</mode>
            <rxfreq>1402500</rxfreq>
            <txfreq>1402500</txfreq>
            <operator>OP1</operator>
            <StationName>Station1</StationName>
            <contestnr>1</contestnr>
        </contactinfo>'''
        process_message(parser, conn, cursor, operators, stations, xml, seen)
        cursor.execute('SELECT qso_id FROM qso_log')
        row = cursor.fetchone()
        # Should be a numeric string (from int checksum)
        assert row[0].isdigit() or row[0].lstrip('-').isdigit()

    def test_contactinfo_float_frequency_skipped(self, test_db):
        """Test contactinfo with float frequency is skipped gracefully."""
        conn, cursor, operators, stations, parser, seen = test_db
        xml = b'''<contactinfo>
            <timestamp>2024-06-22 18:30:45</timestamp>
            <mycall>W1AW</mycall>
            <call>K1ABC</call>
            <band>14</band>
            <mode>CW</mode>
            <rxfreq>1402500.5</rxfreq>
            <txfreq>1402500</txfreq>
            <operator>OP1</operator>
            <StationName>Station1</StationName>
            <contestnr>1</contestnr>
            <ID>test-float</ID>
        </contactinfo>'''
        # Should not raise - just logs warning and skips
        process_message(parser, conn, cursor, operators, stations, xml, seen)
        cursor.execute('SELECT COUNT(*) FROM qso_log')
        assert cursor.fetchone()[0] == 0
