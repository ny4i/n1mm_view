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
