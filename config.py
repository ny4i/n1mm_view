#!/usr/bin/python3

"""
this file is a rewrite of config.py to implement a configParser to keep the config in n1mm_view.ini
"""

__author__ = 'Tom Schaefer NY4I'
__copyright__ = 'Copyright 2024 Thomas M. Schaefer'
__license__ = 'Simplified BSD'

VERSION = '2.1.0'

import configparser
import logging
import datetime
import os
import time

# Note LOG_FORMATS is here rather than constants.py to avoid a circular import
LOG_FORMAT = '%(asctime)s.%(msecs)03d %(levelname)-8s [%(module)s::%(funcName)s] %(message)s'



BASE_CONFIG_NAME = 'n1mm_view.ini'
CONFIG_NAMES = [ os.path.dirname(__file__) + '/' + BASE_CONFIG_NAME
                ,os.path.expanduser('~/' + BASE_CONFIG_NAME)
                ,os.path.expanduser('~/.config/' + BASE_CONFIG_NAME)                             
               ]
               
# Setup logging. This is the first occurrence so this is the only place basicConfig is called
logging.basicConfig( format=LOG_FORMAT, datefmt='%Y-%m-%d %H:%M:%S'
                    ,level=logging.DEBUG # Set to DEBUG so we get all until we grab the value from the config file. THis allows config.py to log before we read the log level
                   )
logging.Formatter.converter = time.gmtime                   
class Singleton(type):
    def __init__(self, name, bases, mmbs):
        super(Singleton, self).__init__(name, bases, mmbs)
        self._instance = super(Singleton, self).__call__()

    def __call__(self, *args, **kw):
        return self._instance

class Config(metaclass = Singleton):
        
    def __init__(self, *args, **kw):
        
        cfg = configparser.ConfigParser()
        # Find and read ini file
        readCFGName = cfg.read(CONFIG_NAMES)
        # Check if there was just one config file found or none at all - Error in both cases so exit
        n = len(readCFGName) # Number of config files found
        if n > 1:
           print ('ConfigParser found more than one config file named %s' % (BASE_CONFIG_NAME))
           for s in readCFGName:
              print ('     Found %s' % (s))
           print ('Please use ONLY ONE file named %s in one of the following locations:' % (BASE_CONFIG_NAME))
           for s in CONFIG_NAMES:
              print ('     %s' % (s))   
           exit ()
        elif n == 0:
           print ('ConfigParser cannot find a config file named %s' % (BASE_CONFIG_NAME))
           print ('Please create ONLY ONE config file named %s in one of the following locations:' % (BASE_CONFIG_NAME))
           for s in CONFIG_NAMES:
              print ('     %s' % (s))   
           exit ()
        
        
       
        # Get logging level set first for subsequent logging...
        self.LOG_LEVEL = cfg.get('GLOBAL','LOG_LEVEL',fallback='ERROR')
        logging.info('Setting log level to %s' % (self.LOG_LEVEL))
        
        # Note that basicConfig is called again since n1mm_view uses the class methods in logging. 
        # While there is a setLevel to dynamically set the level, it is not a class function. 
        # So you have to call basicConfig again with the force parameter True to override the existing one.
        # If rather than call the class function, logging was instantiated as logger (accessible to all) then it could just use setLevel, but that is a bigger refactor.
        
        logging.basicConfig( format=LOG_FORMAT, datefmt='%Y-%m-%d %H:%M:%S'
                    ,level=self.LOG_LEVEL
                    ,force = True
                   )

        # Suppress noisy third-party library logging
        self.LIB_LOG_LEVEL = cfg.get('GLOBAL', 'LIB_LOG_LEVEL', fallback='WARNING')
        for lib in ['matplotlib', 'PIL', 'cartopy', 'pygame', 'fiona', 'shapely', 'pyproj']:
            logging.getLogger(lib).setLevel(self.LIB_LOG_LEVEL)

        logging.info ('Reading config file @ %s' % (readCFGName))
        
        self.DATABASE_FILENAME = cfg.get('GLOBAL','DATABASE_FILENAME',fallback='n1mm_view.db')
        logging.info ('Using database file %s' % (self.DATABASE_FILENAME))

        self.MULTS = cfg.get('GLOBAL', 'MULTS', fallback='SECTIONS').upper()
        if self.MULTS not in ('SECTIONS', 'STATES', 'ITUZONES', 'CQZONES', 'GRID'):
            logging.warning('Invalid MULTS value "%s", defaulting to SECTIONS' % self.MULTS)
            self.MULTS = 'SECTIONS'
        logging.info('MULTS mode set to %s' % self.MULTS)
        
        self.LOGO_FILENAME = cfg.get('GLOBAL','LOGO_FILENAME',fallback='logo.png')
        if not os.path.exists(self.LOGO_FILENAME):
           logging.error('Logo file %s does not exist' % (self.LOGO_FILENAME))
        else:
           logging.info ('Using logo file %s' % (self.LOGO_FILENAME))
           
        self.EVENT_NAME = cfg.get('EVENT INFO','NAME')
        
        dt = cfg.get('EVENT INFO','START_TIME')
        try:
           self.EVENT_START_TIME = datetime.datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
           logging.exception('*** INVALID START_TIME *** Value for START_TIME (%s) is not valid' % (dt))
           exit()
        
        dt = cfg.get('EVENT INFO','END_TIME')
        try:
           self.EVENT_END_TIME = datetime.datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
           logging.exception('*** INVALID END_TIME *** Value for END_TIME (%s) is not valid' % (dt))
           exit()
              
        self.N1MM_BROADCAST_PORT = cfg.getint('N1MM INFO','BROADCAST_PORT',fallback=12060)
        logging.info ('Listening on UDP port %d' % (self.N1MM_BROADCAST_PORT))
        self.N1MM_BROADCAST_ADDRESS = cfg.get('N1MM INFO','BROADCAST_ADDRESS')
        # Optional: re-send each received N1MM datagram verbatim to this UDP
        # port on localhost. Lets a co-located consumer (e.g. the Club Log
        # gateway on its own N1MM port) get the packets without the logger
        # having to broadcast to multiple destinations. 0 = disabled.
        self.UDP_FORWARD_PORT = cfg.getint('N1MM INFO', 'UDP_FORWARD_PORT', fallback=0)
        if self.UDP_FORWARD_PORT:
            logging.info('Forwarding N1MM datagrams to 127.0.0.1:%d' % self.UDP_FORWARD_PORT)
        self.N1MM_LOG_FILE_NAME = cfg.get('N1MM INFO','LOG_FILE_NAME')

        # Comma-separated allow-list for the <app> XML field. Messages whose
        # app field is not in this set are dropped by the collector. Set to
        # empty string to accept everything. Messages with no <app> field at
        # all are always accepted (back-compat). Matching is case-insensitive.
        # N1MM Logger+ uses "N1MMLogger.Net"; TR4W variants include "TR4W"
        # and "TR4QT"; DXLab uses "DXLab".
        allowed_apps_raw = cfg.get('N1MM INFO', 'ALLOWED_APPS',
                                   fallback='N1MM,TR4W')
        self.ALLOWED_APPS = {a.strip().lower()
                             for a in allowed_apps_raw.split(',')
                             if a.strip()}
        if self.ALLOWED_APPS:
            logging.info('App allow-list: %s', sorted(self.ALLOWED_APPS))
        else:
            logging.info('App allow-list is empty; accepting messages from any source.')
        
        self.QTH_LATITUDE = cfg.getfloat('EVENT INFO','QTH_LATITUDE')
        self.QTH_LONGITUDE = cfg.getfloat('EVENT INFO','QTH_LONGITUDE')

        # Map appearance [MAP]. Base-feature fills (ocean/land/lake) -- the
        # default land green (#113311) is quite dark, so it's configurable to
        # lighten the unworked continents. The worked-multiplier choropleth ramp
        # is unchanged (viridis). TERMINATOR_ALPHA is the day/night shading
        # opacity (0 = off, 1 = solid black night side).
        self.MAP_OCEAN_COLOR = cfg.get('MAP', 'OCEAN_COLOR', fallback='#000080')
        self.MAP_LAND_COLOR = cfg.get('MAP', 'LAND_COLOR', fallback='#113311')
        self.MAP_LAKE_COLOR = cfg.get('MAP', 'LAKE_COLOR', fallback='#000080')
        self.MAP_TERMINATOR_ALPHA = cfg.getfloat('MAP', 'TERMINATOR_ALPHA', fallback=0.25)
        self.DISPLAY_DWELL_TIME = cfg.getint('GLOBAL','DISPLAY_DWELL_TIME',fallback=6)
        self.DATA_DWELL_TIME = cfg.getint('GLOBAL','DATA_DWELL_TIME',fallback=60)
        self.HEADLESS_DWELL_TIME = cfg.getint('GLOBAL','HEADLESS_DWELL_TIME',fallback=180)
        self.SKIP_TIMESTAMP_CHECK = cfg.getboolean('DEBUG','SKIP_TIMESTAMP_CHECK',fallback=False)
        
        
        
        self.IMAGE_DIR = cfg.get('HEADLESS INFO','IMAGE_DIR',fallback='/mnt/ramdisk/n1mm_view/html')
        self.HEADLESS = cfg.getboolean('HEADLESS INFO','HEADLESS',fallback = False) #False
        self.POST_FILE_COMMAND = cfg.get('HEADLESS INFO','POST_FILE_COMMAND', fallback=None)

        # Built-in HTTP server that serves IMAGE_DIR and exposes a /api/radio
        # JSON endpoint for near-realtime sidebar updates. Disable if Apache or
        # another web server is already serving the same directory.
        self.WEBSERVER_ENABLED = cfg.getboolean('WEBSERVER', 'ENABLED', fallback=True)
        self.WEBSERVER_BIND = cfg.get('WEBSERVER', 'BIND', fallback='0.0.0.0')
        self.WEBSERVER_PORT = cfg.getint('WEBSERVER', 'PORT', fallback=8080)
        # Browser poll interval for /api/radio, in seconds.
        self.RADIO_POLL_SECONDS = cfg.getint('WEBSERVER', 'RADIO_POLL_SECONDS', fallback=2)
        self.VIEW_FONT = cfg.getint('FONT INFO','VIEW_FONT',fallback=64)
        self.BIGGER_FONT = cfg.getint('FONT INFO','BIGGER_FONT',fallback=180)

        # Feature toggles - new features default to False to preserve original behavior
        self.SHOW_RADIO_INFO = cfg.getboolean('FEATURES', 'SHOW_RADIO_INFO', fallback=False)
        self.SHOW_RADIO_SIDEBAR = cfg.getboolean('FEATURES', 'SHOW_RADIO_SIDEBAR', fallback=False)
        # Hide radio_info rows whose last_update is older than this many
        # seconds (drops leftover rows from previous test sessions). Used by
        # webserver.py and graphics.draw_radio_info. The 60-second dim
        # threshold in the display layer is independent of this value.
        self.RADIO_HIDE_SECONDS = cfg.getint('FEATURES', 'RADIO_HIDE_SECONDS', fallback=600)
        self.SHOW_MULT_PROGRESS = cfg.getboolean('FEATURES', 'SHOW_MULT_PROGRESS', fallback=False)
        self.SHOW_MULT_REMAINING = cfg.getboolean('FEATURES', 'SHOW_MULT_REMAINING', fallback=False)
        self.SHOW_MULT_ALERT = cfg.getboolean('FEATURES', 'SHOW_MULT_ALERT', fallback=False)
        # Maidenhead grids have no fixed multiplier total, so the progress and
        # remaining charts (which need a denominator) don't apply -- force them
        # off in GRID mode regardless of the ini. The new-mult alert still works
        # (it fires on each newly worked grid).
        if self.MULTS == 'GRID' and (self.SHOW_MULT_PROGRESS or self.SHOW_MULT_REMAINING):
            logging.info('MULTS=GRID: disabling multiplier progress/remaining charts (no fixed total)')
            self.SHOW_MULT_PROGRESS = False
            self.SHOW_MULT_REMAINING = False
        self.SHOW_OPERATOR_LEADERBOARD = cfg.getboolean('FEATURES', 'SHOW_OPERATOR_LEADERBOARD', fallback=False)
        # IARU HF HQ-station multiplier roster (worked/total grid). Independent of
        # the ITU-zone map -- HQ stations are a second IARU multiplier, logged as
        # a society abbreviation in the section field. Only meaningful for IARU.
        self.SHOW_HQ_STATIONS = cfg.getboolean('FEATURES', 'SHOW_HQ_STATIONS', fallback=False)

        # IARU HF only: WRTC ("World Radiosport Team Championship") is a
        # once-every-four-years "contest within the contest" -- ~50 teams issued
        # special callsigns shortly before the start (unknown until then). This
        # slide shows how many of those callsigns we've worked, like the HQ
        # roster. The callsign list is read from WRTC_CALLSIGNS_FILE at render
        # time (not startup) so the calls can be dropped in without a restart.
        # Only callsigns are ever read/shown -- never team identities -- in line
        # with WRTC's anti-cheerleading policy.
        self.SHOW_WRTC = cfg.getboolean('FEATURES', 'SHOW_WRTC', fallback=False)
        self.WRTC_CALLSIGNS_FILE = cfg.get('WRTC', 'CALLSIGNS_FILE',
                                           fallback='wrtc2026.txt')

        # Base count charts. These default ON (opt-out) so existing multi-op/FD
        # setups are unchanged; single-station or non-FD events can hide the ones
        # that don't apply -- QSOs by Station (one station), and Class/Category
        # (Field Day exchange concepts, empty for e.g. IARU).
        self.SHOW_QSOS_BY_STATION = cfg.getboolean('FEATURES', 'SHOW_QSOS_BY_STATION', fallback=True)
        self.SHOW_QSOS_BY_CLASS = cfg.getboolean('FEATURES', 'SHOW_QSOS_BY_CLASS', fallback=True)
        self.SHOW_QSOS_BY_CATEGORY = cfg.getboolean('FEATURES', 'SHOW_QSOS_BY_CATEGORY', fallback=True)

        # New-operator tracking: compare current event ops against a prior
        # event's operator table. An operator who logs a QSO this event and
        # whose name is NOT in PRIOR_DB_FILENAME's operator table counts as
        # "new". PRIOR_DB_FILENAME='' disables the feature regardless of the
        # SHOW_NEW_OPS_* flags.
        self.PRIOR_DB_FILENAME = cfg.get('NEW_OPERATORS', 'PRIOR_DB_FILENAME', fallback='')
        self.PRIOR_EVENT_LABEL = cfg.get('NEW_OPERATORS', 'PRIOR_EVENT_LABEL', fallback='Last Year')
        # Consolidated prior-operators DB built by import_prior_operators.py.
        # This is the runtime source for the "not new" lookup AND the YOY chart.
        self.PRIOR_OPERATORS_DB = cfg.get('NEW_OPERATORS', 'PRIOR_OPERATORS_DB',
                                          fallback='prior_operators.db')
        # ADIF directory — used only by import_prior_operators.py to build
        # PRIOR_OPERATORS_DB; not read on every render.
        self.PRIOR_ADIF_DIR = cfg.get('NEW_OPERATORS', 'PRIOR_ADIF_DIR', fallback='')
        # Regex (case-insensitive) used by the YOY chart to filter which
        # events are plotted. Default matches ARRL Field Day variants like
        # "2019 ARRL-FD", "2025ARRLFD".
        self.YOY_EVENT_REGEX = cfg.get('NEW_OPERATORS', 'YOY_EVENT_REGEX',
                                       fallback=r'ARRL.?FD')
        self.SHOW_NEW_OPS_RACE = cfg.getboolean('FEATURES', 'SHOW_NEW_OPS_RACE', fallback=False)
        self.SHOW_NEW_OPS_ROSTER = cfg.getboolean('FEATURES', 'SHOW_NEW_OPS_ROSTER', fallback=False)
        self.SHOW_NEW_OPS_YOY = cfg.getboolean('FEATURES', 'SHOW_NEW_OPS_YOY', fallback=False)

        # External slides: any [EXTERNAL_SLIDES] entry becomes an iframe slide
        # in the carousel. Key = title shown in the slide header, value = URL.
        # Some sites send X-Frame-Options: DENY and will refuse to embed; a
        # fallback "open in new tab" link is rendered below every iframe.
        self.EXTERNAL_SLIDES = []
        if cfg.has_section('EXTERNAL_SLIDES'):
            for key, value in cfg.items('EXTERNAL_SLIDES'):
                url = (value or '').strip()
                if url:
                    self.EXTERNAL_SLIDES.append((key.strip(), url))
        if self.EXTERNAL_SLIDES:
            logging.info('External slides: %s', [t for t, _ in self.EXTERNAL_SLIDES])

        logging.info('Feature toggles: RADIO_INFO=%s, RADIO_SIDEBAR=%s, MULT_PROGRESS=%s, MULT_REMAINING=%s, MULT_ALERT=%s, HQ_STATIONS=%s, WRTC=%s, OPERATOR_LEADERBOARD=%s, QSOS_BY_STATION=%s, QSOS_BY_CLASS=%s, QSOS_BY_CATEGORY=%s, NEW_OPS_RACE=%s, NEW_OPS_ROSTER=%s, NEW_OPS_YOY=%s',
                     self.SHOW_RADIO_INFO, self.SHOW_RADIO_SIDEBAR, self.SHOW_MULT_PROGRESS, self.SHOW_MULT_REMAINING, self.SHOW_MULT_ALERT, self.SHOW_HQ_STATIONS, self.SHOW_WRTC, self.SHOW_OPERATOR_LEADERBOARD, self.SHOW_QSOS_BY_STATION, self.SHOW_QSOS_BY_CLASS, self.SHOW_QSOS_BY_CATEGORY, self.SHOW_NEW_OPS_RACE, self.SHOW_NEW_OPS_ROSTER, self.SHOW_NEW_OPS_YOY)
