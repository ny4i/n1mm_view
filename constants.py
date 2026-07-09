"""
this file contains useful constants for n1mm_view application.
"""

__author__ = 'Jeffrey B. Otterson, N1KDO'
__copyright__ = 'Copyright 2016, 2020 Jeffrey B. Otterson'
__license__ = 'Simplified BSD'

import time
import logging

from config import Config

config = Config()

logging.info('Starting constants.py')

class Bands:
    """
    this is all the bands that are supported.
    contest bands only for now.
    """

    BANDS_LIST = ['N/A', '1.8', '3.5', '7', '14', '21', '28', '50', '144', '420']
    BANDS_TITLE = ['No Band', '160M', '80M', '40M', '20M', '15M', '10M', '6M', '2M', '70cm']
    BANDS = {elem: index for index, elem in enumerate(BANDS_LIST)}

    # Approximate amateur band edges (Hz) -> band title, for mapping a live
    # radio frequency to a band (used for the duplicate band/mode alert).
    BAND_EDGES_HZ = [
        (1_800_000, 2_000_000, '160M'),
        (3_500_000, 4_000_000, '80M'),
        (7_000_000, 7_300_000, '40M'),
        (10_100_000, 10_150_000, '30M'),
        (14_000_000, 14_350_000, '20M'),
        (18_068_000, 18_168_000, '17M'),
        (21_000_000, 21_450_000, '15M'),
        (24_890_000, 24_990_000, '12M'),
        (28_000_000, 29_700_000, '10M'),
        (50_000_000, 54_000_000, '6M'),
        (144_000_000, 148_000_000, '2M'),
        (420_000_000, 450_000_000, '70cm'),
    ]

    @classmethod
    def get_band_number(cls, band_name):
        return Bands.BANDS.get(band_name)

    # Lower edge (Hz) of the US Extra-class phone/image sub-band per band.
    # A PHONE-mode signal below this (but still in the band) is in the
    # CW/data-only segment -> out of band. None = no phone allowed on the band
    # at all (e.g. 30m), so any phone there is out of band.
    PHONE_LOWER_HZ = {
        '160M': 1_800_000,
        '80M': 3_600_000,
        '40M': 7_125_000,
        '30M': None,
        '20M': 14_150_000,
        '17M': 18_110_000,
        '15M': 21_200_000,
        '12M': 24_930_000,
        '10M': 28_300_000,
        '6M': 50_100_000,
        '2M': 144_100_000,
        '70cm': 420_000_000,
    }

    @classmethod
    def freq_to_band(cls, freq_hz):
        """Map a frequency in Hz to a band title (e.g. '20M'), or None."""
        try:
            f = int(freq_hz)
        except (TypeError, ValueError):
            return None
        for lo, hi, title in cls.BAND_EDGES_HZ:
            if lo <= f <= hi:
                return title
        return None

    @classmethod
    def is_out_of_band(cls, freq_hz, mode_group=None):
        """True if a (non-zero) frequency is out of band: either outside every
        ham band, or -- for PHONE mode -- below the Extra-class phone sub-band
        edge for its band (or on a band where phone isn't allowed)."""
        try:
            f = int(freq_hz)
        except (TypeError, ValueError):
            return False
        if not f:
            return False
        band = cls.freq_to_band(f)
        if band is None:
            return True
        if mode_group == 'PHONE':
            lower = cls.PHONE_LOWER_HZ.get(band)
            if lower is None:
                return True   # no phone allowed on this band
            if f < lower:
                return True
        return False

    @classmethod
    def count(cls):
        return len(Bands.BANDS_LIST)


class Modes:
    """
    all the modes that are supported.
    """
    MODES_LIST = ['N/A', 'CW', 'AM', 'FM', 'LSB', 'USB', 'SSB', 'RTTY', 'PSK', 'PSK31', 'PSK63', 'FT8', 'FT4', 'MFSK', 'DATA', 'NoMode', 'None']
    MODES = {elem: index for index, elem in enumerate(MODES_LIST)}

    """
    simplified modes for score reporting: CW, PHONE, DATA
    """
    SIMPLE_MODES_LIST = ['N/A', 'CW', 'PHONE', 'DATA']
    MODE_TO_SIMPLE_MODE = [0, 1, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 3, 3, 2]
    SIMPLE_MODE_POINTS = [0, 2, 1, 2]  # n/a, CW, phone, digital
    SIMPLE_MODES = {'N/A': 0, 'CW': 1,
                    'AM': 2, 'FM': 2, 'LSB': 2, 'USB': 2, 'SSB': 2, 'None': 2,
                    'RTTY': 3, 'PSK': 3, 'PSK31': 3, 'PSK63': 3, 'FT8': 3, 'FT4': 3, 'MFSK': 3, 'DATA': 3, 'NoMode': 3,
                    }

    @classmethod
    def get_mode_number(cls, mode_name):
        mode_number = Modes.MODES.get(mode_name)
        if mode_number is None:
            logging.warning('unknown mode {}'.format(mode_name))
            mode_number = 0
        return mode_number

    @classmethod
    def count(cls):
        return len(Modes.MODES)

    @classmethod
    def get_simple_mode_number(cls, mode_name):
        return Modes.SIMPLE_MODES.get(mode_name)

    @classmethod
    def get_simple_mode_name(cls, mode_name):
        """Return the simple mode-group name (CW/PHONE/DATA), or 'N/A'."""
        return Modes.SIMPLE_MODES_LIST[Modes.SIMPLE_MODES.get(mode_name, 0)]


"""
Every section that is valid for field day, except "DX"
"""
CONTEST_SECTIONS = {
    'AB': 'Alberta',
    'AK': 'Alaska',
    'AL': 'Alabama',
    'AR': 'Arkansas',
    'AZ': 'Arizona',
    'BC': 'British Columbia',
    'CO': 'Colorado',
    'CT': 'Connecticut',
    'DE': 'Delaware',
    'EB': 'East Bay',
    'EMA': 'Eastern Massachusetts',
    'ENY': 'Eastern New York',
    'EPA': 'Eastern Pennsylvania',
    'EWA': 'Eastern Washington',
    'GA': 'Georgia',
    'GH': 'Golden Horseshoe',
    # 'GTA': 'Greater Toronto Area',  # renamed GH 2023-03-15
    'IA': 'Iowa',
    'ID': 'Idaho',
    'IL': 'Illinois',
    'IN': 'Indiana',
    'KS': 'Kansas',
    'KY': 'Kentucky',
    'LA': 'Louisiana',
    'LAX': 'Los Angeles',
    # 'MAR': 'Maritime',  # OBSOLETE 2023-01-01, replaced with NB and NS
    'MB': 'Manitoba',
    'MDC': 'Maryland - DC',
    'ME': 'Maine',
    'MI': 'Michigan',
    'MN': 'Minnesota',
    'MO': 'Missouri',
    'MS': 'Mississippi',
    'MT': 'Montana',
    'NB': 'New Brunswick',
    'NC': 'North Carolina',
    'ND': 'North Dakota',
    'NE': 'Nebraska',
    'NFL': 'Northern Florida',
    'NH': 'New Hampshire',
    'NLI': 'New York City - Long Island',
    'NL': 'Newfoundland/Labrador',
    'NM': 'New Mexico',
    'NNJ': 'Northern New Jersey',
    'NNY': 'Northern New York',
    'NS': 'Nova Scotia',
    # 'NT': 'Northern Territories',  # renamed TER 2023-03-15
    'NTX': 'North Texas',
    'NV': 'Nevada',
    'OH': 'Ohio',
    'OK': 'Oklahoma',
    'ONE': 'Ontario East',
    'ONN': 'Ontario North',
    'ONS': 'Ontario South',
    'ORG': 'Orange',
    'OR': 'Oregon',
    'PAC': 'Pacific',
    'PE': 'Prince Edward Island',
    'PR': 'Puerto Rico',
    'QC': 'Quebec',
    'RI': 'Rhode Island',
    'SB': 'Santa Barbara',
    'SC': 'South Carolina',
    'SCV': 'Santa Clara Valley',
    'SDG': 'San Diego',
    'SD': 'South Dakota',
    'SFL': 'Southern Florida',
    'SF': 'San Francisco',
    'SJV': 'San Joaquin Valley',
    'SK': 'Saskatchewan',
    'SNJ': 'Southern New Jersey',
    'STX': 'South Texas',
    'SV': 'Sacramento Valley',
    'TER': 'Northern Territories',
    'TN': 'Tennessee',
    'UT': 'Utah',
    'VA': 'Virginia',
    'VI': 'Virgin Islands',
    'VT': 'Vermont',
    'WCF': 'West Central Florida',
    'WI': 'Wisconsin',
    'WMA': 'Western Massachusetts',
    'WNY': 'Western New York',
    'WPA': 'Western Pennsylvania',
    'WTX': 'West Texas',
    'WV': 'West Virginia',
    'WWA': 'Western Washington',
    'WY': 'Wyoming',
}

US_STATES = {
    'AL': 'Alabama',
    'AK': 'Alaska',
    'AZ': 'Arizona',
    'AR': 'Arkansas',
    'CA': 'California',
    'CO': 'Colorado',
    'CT': 'Connecticut',
    'DE': 'Delaware',
    'DC': 'District of Columbia',
    'FL': 'Florida',
    'GA': 'Georgia',
    'HI': 'Hawaii',
    'ID': 'Idaho',
    'IL': 'Illinois',
    'IN': 'Indiana',
    'IA': 'Iowa',
    'KS': 'Kansas',
    'KY': 'Kentucky',
    'LA': 'Louisiana',
    'ME': 'Maine',
    'MD': 'Maryland',
    'MA': 'Massachusetts',
    'MI': 'Michigan',
    'MN': 'Minnesota',
    'MS': 'Mississippi',
    'MO': 'Missouri',
    'MT': 'Montana',
    'NE': 'Nebraska',
    'NV': 'Nevada',
    'NH': 'New Hampshire',
    'NJ': 'New Jersey',
    'NM': 'New Mexico',
    'NY': 'New York',
    'NC': 'North Carolina',
    'ND': 'North Dakota',
    'OH': 'Ohio',
    'OK': 'Oklahoma',
    'OR': 'Oregon',
    'PA': 'Pennsylvania',
    'RI': 'Rhode Island',
    'SC': 'South Carolina',
    'SD': 'South Dakota',
    'TN': 'Tennessee',
    'TX': 'Texas',
    'UT': 'Utah',
    'VT': 'Vermont',
    'VA': 'Virginia',
    'WA': 'Washington',
    'WV': 'West Virginia',
    'WI': 'Wisconsin',
    'WY': 'Wyoming',
}


# Radio zones partition the globe and are used as the multiplier in zone
# contests: ITU zones 1..90 (IARU HF Championship) and CQ zones 1..40 (CQ WW,
# CQ WPX-by-zone, etc.). Geometry lives in shapes/itu_zones.geojson and
# shapes/cq_zones.geojson (see utils/extract_zones.py). Keys are zone numbers as
# strings so they match the 'zone' property in the GeoJSON and the value logged
# in the QSO record.
ITU_ZONES = {str(n): 'Zone %d' % n for n in range(1, 91)}
CQ_ZONES = {str(n): 'Zone %d' % n for n in range(1, 41)}


# IARU HF Championship HQ-station multiplier. National-society headquarters
# stations and IARU officials send a society abbreviation (e.g. ARRL, DARC,
# IARU, R1) in the section/exchange field instead of an ITU zone; each distinct
# abbreviation is a separate multiplier worked alongside the zones. The
# canonical list is the scored value column of TR4W's iaruhq.dom. There is no
# meaningful "complete the set" total -- nobody works all ~170 societies -- but
# the chart still shows the full roster with the worked ones highlighted.
IARU_HQ = [
    'AARA', 'AARC', 'AARS', 'ABARS', 'AC', 'AFVL', 'AGRA', 'ARA', 'ARAB',
    'ARABH', 'ARAC', 'ARAD', 'ARAI', 'ARANC', 'ARAT', 'ARBF', 'ARCOT',
    'ARGUI', 'ARI', 'ARM', 'ARRAM', 'ARRL', 'ARRSM', 'ARSB', 'ARSI', 'ARSK',
    'ARTJ', 'ARUKR', 'ASTRA', 'BARC', 'BARL', 'BARS', 'BDARA', 'BFRA', 'BFRR',
    'BVIRL', 'CARS', 'CORA', 'CRAC', 'CRAG', 'CRAM', 'CRAS', 'CRC', 'CREN',
    'CRSA', 'CTARL', 'DARC', 'DARCI', 'EARA', 'EARS', 'EDR', 'ERASD', 'ERAU',
    'FARA', 'FMRE', 'FRA', 'FRC', 'FRR', 'FRRA', 'FRS', 'GARA', 'GARC', 'GARS',
    'GRC', 'HARTS', 'HRS', 'IRA', 'IARC', 'IARS', 'IARU', 'IRTS', 'JARA',
    'JARL', 'KARL', 'KARS', 'KFRR', 'LABRE', 'LARS', 'LCRA', 'LPRA', 'LRAA',
    'LRAL', 'LREM', 'LRMD', 'LRT', 'MARL', 'MARP', 'MARS', 'MARTS', 'MRASZ',
    'MRSF', 'NARG', 'NARL', 'NARS', 'NRRL', 'NZART', 'OEVSV', 'ORARI', 'OVSV',
    'PARA', 'PARS', 'PIARA', 'PNGARS', 'PZK', 'QARS', 'R1', 'R2', 'R3', 'RAAG',
    'RAC', 'RAL', 'RAST', 'RCA', 'RCB', 'RCCH', 'RCCR', 'RCD', 'RCH', 'RCP',
    'RCU', 'RCV', 'REF', 'REP', 'RJRAS', 'RL', 'ROARS', 'RSB', 'RSGB', 'RSM',
    'RSS', 'RSSL', 'RSTG', 'RSZ', 'SARA/SZR', 'SARC', 'SARL', 'SARS', 'SARTS',
    'SARU', 'SCG', 'SHRAK', 'SIRS', 'SLARS', 'SRAL', 'SRR', 'SRS', 'SSA',
    'SSTARS', 'SVGRS', 'TACARS', 'TARC', 'TARL', 'TRAC', 'TTARS', 'UARL',
    'UARS', 'UBA', 'URA', 'URE', 'USKA', 'VARC', 'VARS', 'VERON', 'VRAS',
    'VRONA', 'WIA', 'ZARS', 'ZRS',
]

# Common forms an operator may log that differ from the canonical abbreviation
# above (aliases from the left-hand side of iaruhq.dom, plus the split of the
# combined SARA/SZR entry). Mapped to their canonical value for counting.
_IARU_HQ_ALIASES = {
    'IAR': 'IRA',
    'SARA': 'SARA/SZR',
    'SZR': 'SARA/SZR',
}

_IARU_HQ_LOOKUP = {abbr.upper(): abbr for abbr in IARU_HQ}
_IARU_HQ_LOOKUP.update(_IARU_HQ_ALIASES)


def hq_canonical(section):
    """Map a logged section/exchange value to its canonical IARU HQ abbreviation,
    or None if it is not a recognised HQ station (e.g. it is a plain ITU zone
    number). Case-insensitive; accepts a few common aliases."""
    if not section:
        return None
    return _IARU_HQ_LOOKUP.get(section.strip().upper())


def get_mult_dictionary():
    """Return the appropriate multiplier dictionary based on config.MULTS.

    GRID (Maidenhead) has no fixed, enumerable multiplier set -- the worked
    grids are discovered from the log -- so it returns an empty dict; the map
    iterates the worked grids directly instead of this dictionary."""
    if config.MULTS == 'STATES':
        return US_STATES
    if config.MULTS == 'ITUZONES':
        return ITU_ZONES
    if config.MULTS == 'CQZONES':
        return CQ_ZONES
    if config.MULTS == 'GRID':
        return {}
    return CONTEST_SECTIONS


def get_mult_name():
    """Return the multiplier noun for the configured contest ('States',
    'Sections', 'Zones' or 'Grids'), for titling charts like '<name> Progress' /
    '<name> Remaining'."""
    if config.MULTS == 'STATES':
        return 'States'
    if config.MULTS in ('ITUZONES', 'CQZONES'):
        return 'Zones'
    if config.MULTS == 'GRID':
        return 'Grids'
    return 'Sections'


def get_mult_title():
    """Return the appropriate title based on config.MULTS."""
    return '%s Worked' % get_mult_name()


# Category letter descriptions for exchange classes.
# WFD and ARRL FD letters are unique to each other so both can live here.
CATEGORY_NAMES = {
    # Winter Field Day
    'H': 'H - Home',
    'I': 'I - Indoor',
    'O': 'O - Outdoor',
    'M': 'M - Mobile',
    # ARRL Field Day
    'A': 'A - Club/Portable',
    'B': 'B - 1-2 Person Portable',
    'C': 'C - Mobile',
    'D': 'D - Home',
    'E': 'E - Home/Emerg Power',
    'F': 'F - EOC',
}
