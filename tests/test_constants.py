"""
Tests for constants.py - Band, Mode lookups and multiplier functions.
"""
import pytest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import Bands, Modes, CONTEST_SECTIONS, US_STATES, CATEGORY_NAMES


class TestBands:
    """Tests for the Bands class."""

    def test_get_band_number_valid_bands(self):
        """Test that all valid bands return correct indices."""
        assert Bands.get_band_number('1.8') == 1   # 160M
        assert Bands.get_band_number('3.5') == 2   # 80M
        assert Bands.get_band_number('7') == 3     # 40M
        assert Bands.get_band_number('14') == 4    # 20M
        assert Bands.get_band_number('21') == 5    # 15M
        assert Bands.get_band_number('28') == 6    # 10M
        assert Bands.get_band_number('50') == 7    # 6M
        assert Bands.get_band_number('144') == 8   # 2M
        assert Bands.get_band_number('420') == 9   # 70cm

    def test_get_band_number_na(self):
        """Test N/A band returns 0."""
        assert Bands.get_band_number('N/A') == 0

    def test_get_band_number_invalid(self):
        """Test invalid band returns None."""
        assert Bands.get_band_number('invalid') is None
        assert Bands.get_band_number('') is None
        assert Bands.get_band_number('999') is None

    def test_bands_count(self):
        """Test band count matches expected."""
        assert Bands.count() == 10

    def test_bands_list_and_title_alignment(self):
        """Test BANDS_LIST and BANDS_TITLE have same length."""
        assert len(Bands.BANDS_LIST) == len(Bands.BANDS_TITLE)

    def test_bands_dict_completeness(self):
        """Test all BANDS_LIST entries are in BANDS dict."""
        for band in Bands.BANDS_LIST:
            assert band in Bands.BANDS


class TestModes:
    """Tests for the Modes class."""

    def test_get_mode_number_cw(self):
        """Test CW mode returns correct index."""
        assert Modes.get_mode_number('CW') == 1

    def test_get_mode_number_phone_modes(self):
        """Test phone modes return correct indices."""
        assert Modes.get_mode_number('AM') == 2
        assert Modes.get_mode_number('FM') == 3
        assert Modes.get_mode_number('LSB') == 4
        assert Modes.get_mode_number('USB') == 5
        assert Modes.get_mode_number('SSB') == 6

    def test_get_mode_number_digital_modes(self):
        """Test digital modes return correct indices."""
        assert Modes.get_mode_number('RTTY') == 7
        assert Modes.get_mode_number('PSK') == 8
        assert Modes.get_mode_number('PSK31') == 9
        assert Modes.get_mode_number('PSK63') == 10
        assert Modes.get_mode_number('FT8') == 11
        assert Modes.get_mode_number('FT4') == 12
        assert Modes.get_mode_number('MFSK') == 13

    def test_get_mode_number_invalid_returns_zero(self):
        """Test invalid mode returns 0 (not None)."""
        assert Modes.get_mode_number('INVALID') == 0
        assert Modes.get_mode_number('') == 0
        assert Modes.get_mode_number('xyz') == 0

    def test_get_simple_mode_number_cw(self):
        """Test CW maps to simple mode 1 (CW)."""
        assert Modes.get_simple_mode_number('CW') == 1

    def test_get_simple_mode_number_phone(self):
        """Test phone modes map to simple mode 2 (PHONE)."""
        assert Modes.get_simple_mode_number('AM') == 2
        assert Modes.get_simple_mode_number('FM') == 2
        assert Modes.get_simple_mode_number('LSB') == 2
        assert Modes.get_simple_mode_number('USB') == 2
        assert Modes.get_simple_mode_number('SSB') == 2
        assert Modes.get_simple_mode_number('None') == 2

    def test_get_simple_mode_number_digital(self):
        """Test digital modes map to simple mode 3 (DATA)."""
        assert Modes.get_simple_mode_number('RTTY') == 3
        assert Modes.get_simple_mode_number('PSK') == 3
        assert Modes.get_simple_mode_number('PSK31') == 3
        assert Modes.get_simple_mode_number('PSK63') == 3
        assert Modes.get_simple_mode_number('FT8') == 3
        assert Modes.get_simple_mode_number('FT4') == 3
        assert Modes.get_simple_mode_number('MFSK') == 3
        assert Modes.get_simple_mode_number('NoMode') == 3

    def test_get_simple_mode_number_invalid(self):
        """Test invalid mode returns None for simple mode."""
        assert Modes.get_simple_mode_number('INVALID') is None

    def test_modes_count(self):
        """Test mode count."""
        assert Modes.count() == 16

    def test_mode_to_simple_mode_alignment(self):
        """Test MODE_TO_SIMPLE_MODE has correct length."""
        assert len(Modes.MODE_TO_SIMPLE_MODE) == len(Modes.MODES_LIST)

    def test_simple_mode_points(self):
        """Test point values for simple modes."""
        assert Modes.SIMPLE_MODE_POINTS[0] == 0  # N/A
        assert Modes.SIMPLE_MODE_POINTS[1] == 2  # CW
        assert Modes.SIMPLE_MODE_POINTS[2] == 1  # PHONE
        assert Modes.SIMPLE_MODE_POINTS[3] == 2  # DATA


class TestContestSections:
    """Tests for CONTEST_SECTIONS dictionary."""

    def test_section_count(self):
        """Test we have expected number of sections."""
        # Should have 83 sections as of current version
        assert len(CONTEST_SECTIONS) >= 80

    def test_common_sections_exist(self):
        """Test common sections exist with correct names."""
        assert CONTEST_SECTIONS['CT'] == 'Connecticut'
        assert CONTEST_SECTIONS['EMA'] == 'Eastern Massachusetts'
        assert CONTEST_SECTIONS['WMA'] == 'Western Massachusetts'
        assert CONTEST_SECTIONS['CO'] == 'Colorado'
        assert CONTEST_SECTIONS['LAX'] == 'Los Angeles'

    def test_canadian_sections_exist(self):
        """Test Canadian sections exist."""
        assert 'AB' in CONTEST_SECTIONS  # Alberta
        assert 'BC' in CONTEST_SECTIONS  # British Columbia
        assert 'ON' not in CONTEST_SECTIONS  # Ontario is split
        assert 'ONE' in CONTEST_SECTIONS  # Ontario East
        assert 'ONN' in CONTEST_SECTIONS  # Ontario North
        assert 'ONS' in CONTEST_SECTIONS  # Ontario South

    def test_obsolete_sections_removed(self):
        """Test obsolete sections are not present."""
        assert 'MAR' not in CONTEST_SECTIONS  # Maritime - replaced with NB/NS
        assert 'GTA' not in CONTEST_SECTIONS  # GTA - renamed to GH
        assert 'NT' not in CONTEST_SECTIONS   # Northern Territories - renamed TER


class TestUSStates:
    """Tests for US_STATES dictionary."""

    def test_state_count(self):
        """Test we have all 50 states plus DC."""
        assert len(US_STATES) == 51

    def test_common_states_exist(self):
        """Test common states exist."""
        assert US_STATES['NY'] == 'New York'
        assert US_STATES['CA'] == 'California'
        assert US_STATES['TX'] == 'Texas'
        assert US_STATES['FL'] == 'Florida'
        assert US_STATES['DC'] == 'District of Columbia'


class TestCategoryNames:
    """Tests for CATEGORY_NAMES dictionary."""

    def test_wfd_categories(self):
        """Test Winter Field Day categories."""
        assert 'H' in CATEGORY_NAMES  # Home
        assert 'I' in CATEGORY_NAMES  # Indoor
        assert 'O' in CATEGORY_NAMES  # Outdoor
        assert 'M' in CATEGORY_NAMES  # Mobile

    def test_arrl_fd_categories(self):
        """Test ARRL Field Day categories."""
        assert 'A' in CATEGORY_NAMES  # Club/Portable
        assert 'B' in CATEGORY_NAMES  # 1-2 Person Portable
        assert 'C' in CATEGORY_NAMES  # Mobile
        assert 'D' in CATEGORY_NAMES  # Home
        assert 'E' in CATEGORY_NAMES  # Home/Emerg Power
        assert 'F' in CATEGORY_NAMES  # EOC
