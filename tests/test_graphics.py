"""
Tests for graphics.py - Pure utility functions.

Note: graphics.py has pygame initialization side effects at import time.
We mock pygame to avoid needing a display for testing pure functions.
"""
import pytest
import sys
import os
from unittest.mock import MagicMock, patch

# Mock pygame before importing graphics
sys.modules['pygame'] = MagicMock()
sys.modules['pygame.font'] = MagicMock()

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestFormatFrequency:
    """Tests for the format_frequency function."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Import format_frequency with mocked pygame."""
        # Import here to use mocked pygame
        from graphics import format_frequency
        self.format_frequency = format_frequency

    def test_format_20m_frequency(self):
        """Test formatting a 20m frequency."""
        # 14.250.00 MHz = 14250000 Hz
        result = self.format_frequency(14250000)
        assert result == '14.250.00'

    def test_format_40m_frequency(self):
        """Test formatting a 40m frequency."""
        # 7.125.50 MHz = 7125500 Hz
        result = self.format_frequency(7125500)
        assert result == '7.125.50'

    def test_format_80m_frequency(self):
        """Test formatting an 80m frequency."""
        # 3.850.00 MHz = 3850000 Hz
        result = self.format_frequency(3850000)
        assert result == '3.850.00'

    def test_format_2m_frequency(self):
        """Test formatting a 2m frequency."""
        # 146.520.00 MHz = 146520000 Hz
        result = self.format_frequency(146520000)
        assert result == '146.520.00'

    def test_format_frequency_with_decimal_khz(self):
        """Test frequency with non-zero decimal part."""
        # 14.025.35 MHz
        result = self.format_frequency(14025350)
        assert result == '14.025.35'

    def test_format_zero_frequency(self):
        """Test zero frequency returns placeholder."""
        result = self.format_frequency(0)
        assert result == '-.---.--'

    def test_format_none_frequency(self):
        """Test None frequency returns placeholder."""
        result = self.format_frequency(None)
        assert result == '-.---.--'

    def test_format_10m_frequency(self):
        """Test formatting a 10m frequency."""
        # 28.400.00 MHz
        result = self.format_frequency(28400000)
        assert result == '28.400.00'

    def test_format_6m_frequency(self):
        """Test formatting a 6m frequency."""
        # 50.125.00 MHz
        result = self.format_frequency(50125000)
        assert result == '50.125.00'

    def test_format_160m_frequency(self):
        """Test formatting a 160m frequency."""
        # 1.850.00 MHz = 1850000 Hz
        result = self.format_frequency(1850000)
        assert result == '1.850.00'

    def test_format_frequency_rounding(self):
        """Test frequency rounding behavior."""
        # 14.025.555 Hz should round to 14.025.56
        result = self.format_frequency(14025555)
        assert result == '14.025.56'

    def test_format_small_frequency(self):
        """Test formatting a small frequency (LF/MF)."""
        # 0.475.00 MHz = 475000 Hz (600m band)
        result = self.format_frequency(475000)
        assert result == '0.475.00'


class TestDrawMultsProgress:
    """Tests for the draw_mults_progress function."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Import draw_mults_progress with mocked pygame."""
        from graphics import draw_mults_progress
        self.draw_mults_progress = draw_mults_progress
        # Configure font mocks to return proper size tuples
        import graphics
        graphics.bigger_font.size.return_value = (200, 50)
        graphics.bigger_font.get_height.return_value = 50
        graphics.view_font.size.return_value = (150, 20)
        graphics.view_font.get_height.return_value = 20

    def test_returns_none_for_empty_mult_dict(self):
        """Test that empty mult dictionary returns None."""
        # Mock get_mult_dictionary to return empty dict
        with patch('graphics.get_mult_dictionary', return_value={}):
            result, size = self.draw_mults_progress((800, 600), {})
            assert result is None
            assert size == (0, 0)

    def test_returns_data_for_valid_input(self):
        """Test that valid input returns data."""
        mock_mults = {'CT': 'Connecticut', 'NY': 'New York', 'MA': 'Massachusetts'}
        qsos_by_mult = {'CT': 5, 'NY': 3}  # 2 of 3 worked
        with patch('graphics.get_mult_dictionary', return_value=mock_mults):
            result, size = self.draw_mults_progress((800, 600), qsos_by_mult)
            # With mocked pygame, we should get some data back
            assert size != (0, 0)

    def test_handles_none_qsos_by_mult(self):
        """Test that None qsos_by_mult is handled."""
        mock_mults = {'CT': 'Connecticut', 'NY': 'New York'}
        with patch('graphics.get_mult_dictionary', return_value=mock_mults):
            result, size = self.draw_mults_progress((800, 600), None)
            # Should not raise exception
            assert size != (0, 0)


class TestDrawMultsRemaining:
    """Tests for the draw_mults_remaining function."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Import draw_mults_remaining with mocked pygame."""
        from graphics import draw_mults_remaining
        self.draw_mults_remaining = draw_mults_remaining
        # Configure font mock to return proper size tuple
        import graphics
        graphics.view_font.size.return_value = (100, 20)
        graphics.view_font.get_height.return_value = 20

    def test_returns_data_when_all_mults_worked(self):
        """Test that 'all worked' message appears when none remaining."""
        mock_mults = {'CT': 'Connecticut', 'NY': 'New York'}
        qsos_by_mult = {'CT': 5, 'NY': 3}  # All worked
        with patch('graphics.get_mult_dictionary', return_value=mock_mults):
            result, size = self.draw_mults_remaining((800, 600), qsos_by_mult)
            assert size != (0, 0)

    def test_returns_data_with_remaining_mults(self):
        """Test that remaining mults are displayed."""
        mock_mults = {'CT': 'Connecticut', 'NY': 'New York', 'MA': 'Massachusetts'}
        qsos_by_mult = {'CT': 5}  # 2 remaining
        with patch('graphics.get_mult_dictionary', return_value=mock_mults):
            result, size = self.draw_mults_remaining((800, 600), qsos_by_mult)
            assert size != (0, 0)

    def test_handles_none_qsos_by_mult(self):
        """Test that None qsos_by_mult is handled."""
        mock_mults = {'CT': 'Connecticut', 'NY': 'New York'}
        with patch('graphics.get_mult_dictionary', return_value=mock_mults):
            result, size = self.draw_mults_remaining((800, 600), None)
            assert size != (0, 0)


class TestDrawOperatorLeaderboard:
    """Tests for the draw_operator_leaderboard function."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Import draw_operator_leaderboard with mocked pygame."""
        from graphics import draw_operator_leaderboard
        self.draw_operator_leaderboard = draw_operator_leaderboard
        # Configure font mock to return proper size tuple for draw_table
        import graphics
        graphics.view_font.size.return_value = (100, 20)
        graphics.view_font.get_height.return_value = 20

    def test_returns_none_for_empty_operators(self):
        """Test that empty operators returns None."""
        result, size = self.draw_operator_leaderboard((800, 600), [])
        assert result is None
        assert size == (0, 0)

    def test_returns_none_for_none_operators(self):
        """Test that None operators returns None."""
        result, size = self.draw_operator_leaderboard((800, 600), None)
        assert result is None
        assert size == (0, 0)

    def test_returns_data_for_valid_operators(self):
        """Test that valid operators returns data."""
        operators = [('N1KDO', 50), ('W1AW', 30), ('K1ABC', 20)]
        result, size = self.draw_operator_leaderboard((800, 600), operators)
        # Should return data since draw_table is called
        assert size != (0, 0)

    def test_returns_none_for_zero_total_qsos(self):
        """Test that zero total QSOs returns None."""
        operators = [('N1KDO', 0), ('W1AW', 0)]
        result, size = self.draw_operator_leaderboard((800, 600), operators)
        assert result is None
        assert size == (0, 0)
