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

    @classmethod
    def get_band_number(cls, band_name):
        return Bands.BANDS.get(band_name)

    @classmethod
    def count(cls):
        return len(Bands.BANDS_LIST)


class Modes:
    """
    all the modes that are supported.
    """
    MODES_LIST = ['N/A', 'CW', 'AM', 'FM', 'LSB', 'USB', 'SSB', 'RTTY', 'PSK', 'PSK31', 'PSK63', 'FT8', 'FT4', 'MFSK', 'NoMode', 'None']
    MODES = {elem: index for index, elem in enumerate(MODES_LIST)}

    """
    simplified modes for score reporting: CW, PHONE, DATA
    """
    SIMPLE_MODES_LIST = ['N/A', 'CW', 'PHONE', 'DATA']
    MODE_TO_SIMPLE_MODE = [0, 1, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 3, 2]
    SIMPLE_MODE_POINTS = [0, 2, 1, 2]  # n/a, CW, phone, digital
    SIMPLE_MODES = {'N/A': 0, 'CW': 1,
                    'AM': 2, 'FM': 2, 'LSB': 2, 'USB': 2, 'SSB': 2, 'None': 2,
                    'RTTY': 3, 'PSK': 3, 'PSK31': 3, 'PSK63': 3, 'FT8': 3, 'FT4': 3, 'MFSK': 3, 'NoMode': 3,
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


def get_mult_dictionary():
    """Return the appropriate multiplier dictionary based on config.MULTS."""
    if config.MULTS == 'STATES':
        return US_STATES
    return CONTEST_SECTIONS


def get_mult_title():
    """Return the appropriate title based on config.MULTS."""
    if config.MULTS == 'STATES':
        return 'States Worked'
    return 'Sections Worked'


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
