#!/usr/bin/env python3
"""
generate_blank_charts.py - write a blank placeholder PNG for every dashboard
chart, on demand.

When the database is empty (e.g. just wiped of test data) the chart builders
return None and nothing is written, so the slideshow keeps showing stale images
from the previous session. Run this to refresh every chart slot to a clean
"no data yet" placeholder. It's also handy for debugging: it confirms the image
pipeline and IMAGE_DIR are working without needing any QSO data.

The headless renderer overwrites these blanks with real charts as soon as data
arrives, so it's safe to run any time.

    python3 generate_blank_charts.py            # blank every known chart
    python3 generate_blank_charts.py --list     # just list the files it targets

Run it on the pi (it reads IMAGE_DIR from the same n1mm_view.ini the services
use).
"""
import argparse
import os
import sys

import pygame

import constants
import graphics
from config import Config

# Match the size headless renders charts at (graphics scales internally).
CHART_SIZE = (1280, 1024)

# (filename, title) for every chart the dashboard can show. Titles mirror the
# slide labels in headless.py. Optional/feature-gated charts are included too so
# a blank exists regardless of which features are enabled. radio_info.png is the
# sidebar panel.
CHARTS = [
    ('sections_worked_map.png',      'Sections Worked Map'),
    ('qso_summary_table.png',        'QSO Summary'),
    ('qso_rates_table.png',          'QSO Rates'),
    ('qso_rates_graph.png',          'QSO Rate Over Time'),
    ('qso_operators_graph.png',      'QSOs by Operator'),
    ('qso_operators_table.png',      'Operator Totals'),
    ('qso_operators_table_all.png',  'All Operator Stats'),
    ('qso_stations_graph.png',       'QSOs by Station'),
    ('qso_bands_graph.png',          'QSOs by Band'),
    ('qso_modes_graph.png',          'QSOs by Mode'),
    ('qso_classes_graph.png',        'QSOs by Class'),
    ('qso_categories_graph.png',     'QSOs by Category'),
    ('mults_progress.png',           'Multiplier Progress'),
    ('mults_remaining.png',          '%s Remaining' % constants.get_mult_name()),
    ('operator_leaderboard.png',     'Operator Leaderboard'),
    # WRTC special-callsign roster (derived from qso_log, so it should clear on
    # a DB wipe; also starts blank before the calls are issued).
    ('wrtc_stations.png',            'WRTC Stations Worked'),
    # Recent QSOs sidebar (derived from qso_log, so it should clear on a DB wipe).
    ('last_qso_table.png',           'Recent QSOs'),
    # NOTE: intentionally NOT blanked -- these don't come from the current
    # event's QSO data and display correctly even after a wipe:
    #   * radio_info.png        -- live radio telemetry (radio_info table)
    #   * new_ops_race/roster   -- incorporate prior-year reference data
    #   * new_ops_yoy/_slide    -- historical year-over-year totals
]


def main(argv=None):
    ap = argparse.ArgumentParser(description='Write blank placeholder charts for the dashboard.')
    ap.add_argument('--list', action='store_true',
                    help='list the target files and exit (writes nothing)')
    ap.add_argument('--message', default='— no data yet —',
                    help='placeholder message drawn on each chart')
    args = ap.parse_args(argv)

    image_dir = Config().IMAGE_DIR or './images'

    if args.list:
        for filename, title in CHARTS:
            print(os.path.join(image_dir, filename), '   #', title)
        return 0

    if not os.path.isdir(image_dir):
        os.makedirs(image_dir, exist_ok=True)
        print(f'created IMAGE_DIR {image_dir}')

    pygame.init()
    written = 0
    for filename, title in CHARTS:
        raw, size = graphics.make_blank_chart(CHART_SIZE, title, args.message)
        path = os.path.join(image_dir, filename)
        graphics.save_image(raw, size, path)
        written += 1
        print(f'  wrote {path}')
    print(f'\nDone: {written} blank chart(s) written to {image_dir}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
