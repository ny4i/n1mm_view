#!/usr/bin/python3
"""
n1mm_view_headless
create images from contest data
non-interactive version.  This creates files on the disk and updates them periodically.
"""

import gc
import json
import logging
import os
import re
import sqlite3
import sys
import time
#import subprocess

from config import Config, VERSION
import constants
import dataaccess
import graphics

__author__ = 'Jeffrey B. Otterson, N1KDO'
__copyright__ = 'Copyright 2017 Jeffrey B. Otterson'
__license__ = 'Simplified BSD'

config = Config()
#logging.basicConfig(format='%(asctime)s.%(msecs)03d %(levelname)-8s %(module)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S',
#                    level=config.LOG_LEVEL)
#logging.Formatter.converter = time.gmtime
logger = logging.getLogger(__name__)
logging.debug('Getting started here in headless.py')

# Web interface theme colors
THEME = {
    'bg_primary': '#1a1a2e',      # Main background
    'bg_secondary': '#16213e',    # Header/sidebar background
    'border': '#0f3460',          # Border color
    'accent': '#e94560',          # Accent/highlight color
    'text_primary': '#e0e0e0',    # Main text color
    'text_secondary': '#a0a0b8',  # Secondary text color
    'text_muted': '#606080',      # Muted/footer text
    'dot_inactive': '#0f3460',    # Carousel dot inactive
    'sidebar_width': '350px',     # Sidebar width
    'sidebar_min_width': '310px', # Sidebar minimum width
}

def makePNGTitle(image_dir, title):
    if image_dir is None:
        image_dir = './images'
    title = title.replace(' ', '_')
    return f'{image_dir}/{title}.png'
    # return ''.join([image_dir, '/', re.sub('[^\w\-_]', '_', title), '.png'])


def create_images(size, image_dir, last_qso_timestamp):
    """
    load data from the database tables
    """
    logging.debug('load data')

    qso_operators = []
    qso_stations = []
    qso_band_modes = []
    operator_qso_rates = []
    qsos_per_hour = []
    qsos_by_section = {}
    qso_classes = []
    qso_categories = []
    qsos = []
    radio_info = []

    db = None
    data_updated = False

    try:
        logging.debug('connecting to database')
        db = sqlite3.connect(config.DATABASE_FILENAME)
        cursor = db.cursor()
        logging.debug('database connected')

        # Handy routine to dump the database to help debug strange problems
        #if logging.getLogger().isEnabledFor(logging.DEBUG):
        #   cursor.execute('SELECT timestamp, callsign, section, operator_id, operator.name FROM qso_log join operator WHERE operator.id = operator_id')
        #  for row in cursor: 
        #      logging.debug('QSO: %s\t%s\t%s\t%s\t%s' % (row[0], row[1], row[2], row[3], row[4])) 
              
        # get timestamp from the last record in the database
        last_qso_time, message = dataaccess.get_last_qso(cursor)

        logging.debug('old_timestamp = %s, timestamp = %s' % (last_qso_timestamp, last_qso_time))
        if config.SKIP_TIMESTAMP_CHECK: 
           logging.warn('Skipping check for a recent QSO - Please just use this for debug - Review SKIP_TIMESTAMP_CHECK in ini file')
        if last_qso_time != last_qso_timestamp or config.SKIP_TIMESTAMP_CHECK:
            # last_qso_time is passed as the result and updated in call to this function.
            logging.debug('data updated!')
            data_updated = True

            # load qso_operators
            qso_operators = dataaccess.get_operators_by_qsos(cursor)

            # load qso_stations -- maybe useless chartjunk
            qso_stations = dataaccess.get_station_qsos(cursor)

            # get something else.
            qso_band_modes = dataaccess.get_qso_band_modes(cursor)

            # load QSOs per Hour by Operator
            operator_qso_rates = dataaccess.get_qsos_per_hour_per_operator(cursor, last_qso_time)

            # load QSO rates per Hour by Band
            qsos_per_hour, qsos_per_band = dataaccess.get_qsos_per_hour_per_band(cursor)

            # load qso exchange data: what class are the other stations?
            qso_classes = dataaccess.get_qso_classes(cursor)

            # load qso exchange data by category (letter only)
            qso_categories = dataaccess.get_qso_categories(cursor)

            # load last 10 qsos
            qsos = dataaccess.get_last_N_qsos(cursor, 10) # Note this returns last 10 qsos in reverse order so oldest is first

        # load QSOs by Section/State -- always load this since map is always drawn
        if config.MULTS == 'STATES':
            qsos_by_section = dataaccess.get_qsos_by_state(cursor)
        else:
            qsos_by_section = dataaccess.get_qsos_by_section(cursor)
        logging.debug("get_qsos_by_section returned %s qsos" % (qsos_by_section))

        # load radio info
        radio_info = dataaccess.get_radio_info(cursor)

        logging.info('load data done')
    except sqlite3.OperationalError as error:
        logging.exception(error)
        return
    finally:
        if db is not None:
            logging.debug('Closing DB')
            cursor.close()
            db.close()
            db = None

    if data_updated:
        try:
            image_data, image_size = graphics.qso_summary_table(size, qso_band_modes)
            if image_data is not None:
               filename = makePNGTitle(image_dir, 'qso_summary_table')
               graphics.save_image(image_data, image_size, filename)
        except Exception as e:
            logging.exception(e)
        
        try:
            image_data, image_size = graphics.qso_rates_table(size, operator_qso_rates)
            if image_data is not None:
               filename = makePNGTitle(image_dir, 'qso_rates_table')
               graphics.save_image(image_data, image_size, filename)
        except Exception as e:
            logging.exception(e)
        
        try:
            image_data, image_size = graphics.qso_operators_graph(size, qso_operators)
            if image_data is not None:
               filename = makePNGTitle(image_dir, 'qso_operators_graph')
               graphics.save_image(image_data, image_size, filename)
        except Exception as e:
            logging.exception(e)
        
        try:
            image_data, image_size = graphics.qso_operators_table(size, qso_operators)
            if image_data is not None:
               filename = makePNGTitle(image_dir, 'qso_operators_table')
               graphics.save_image(image_data, image_size, filename)
        except Exception as e:
            logging.exception(e)
        
        try:
            image_data, image_size = graphics.qso_operators_table_all(size, qso_operators)
            if image_data is not None:
               filename = makePNGTitle(image_dir, 'qso_operators_table_all')
               graphics.save_image(image_data, image_size, filename)
        except Exception as e:
            logging.exception(e)  
        
        try:
            image_data, image_size = graphics.qso_stations_graph(size, qso_stations)
            if image_data is not None:
               filename = makePNGTitle(image_dir, 'qso_stations_graph')
               graphics.save_image(image_data, image_size, filename)
        except Exception as e:
            logging.exception(e)
        
        try:
            image_data, image_size = graphics.qso_bands_graph(size, qso_band_modes)
            if image_data is not None:
               filename = makePNGTitle(image_dir, 'qso_bands_graph')
               graphics.save_image(image_data, image_size, filename)
        except Exception as e:
            logging.exception(e)
        
        try:
            image_data, image_size = graphics.qso_modes_graph(size, qso_band_modes)
            if image_data is not None:
               filename = makePNGTitle(image_dir, 'qso_modes_graph')
               graphics.save_image(image_data, image_size, filename)
        except Exception as e:
            logging.exception(e)
        
        try:
            image_data, image_size = graphics.qso_classes_graph(size, qso_classes)
            if image_data is not None:
               filename = makePNGTitle(image_dir, 'qso_classes_graph')
               graphics.save_image(image_data, image_size, filename)
        except Exception as e:
            logging.exception(e)

        try:
            image_data, image_size = graphics.qso_categories_graph(size, qso_categories)
            if image_data is not None:
               filename = makePNGTitle(image_dir, 'qso_categories_graph')
               graphics.save_image(image_data, image_size, filename)
        except Exception as e:
            logging.exception(e)

        try:
            image_data, image_size = graphics.qso_rates_graph(size, qsos_per_hour)
            if image_data is not None:
               filename = makePNGTitle(image_dir, 'qso_rates_graph')
               graphics.save_image(image_data, image_size, filename)
        except Exception as e:
            logging.exception(e)
            
        try:
            image_data, image_size = graphics.qso_table(size, qsos)
            if image_data is not None:
               filename = makePNGTitle(image_dir, 'last_qso_table')
               graphics.save_image(image_data, image_size, filename)
        except Exception as e:
            logging.exception(e)

    # map gets updated every time so grey line moves
    try:
       # There is a memory leak in the next code -- is there?
       image_data, image_size = graphics.draw_map(size, qsos_by_section)
       if image_data is not None:
          filename = makePNGTitle(image_dir, 'sections_worked_map')
          graphics.save_image(image_data, image_size, filename)
          gc.collect()
       else:
          logging.debug('image_data was None when drawing map')

    except Exception as e:
        logging.exception(e)

    if config.SHOW_RADIO_INFO:
        try:
            image_data, image_size = graphics.draw_radio_info(size, radio_info)
            if image_data is not None:
                filename = makePNGTitle(image_dir, 'radio_info')
                graphics.save_image(image_data, image_size, filename)
        except Exception as e:
            logging.exception(e)

    if config.SHOW_MULT_PROGRESS:
        try:
            image_data, image_size = graphics.draw_mults_progress(size, qsos_by_section)
            if image_data is not None:
                filename = makePNGTitle(image_dir, 'mults_progress')
                graphics.save_image(image_data, image_size, filename)
        except Exception as e:
            logging.exception(e)

    if config.SHOW_MULT_REMAINING:
        try:
            image_data, image_size = graphics.draw_mults_remaining(size, qsos_by_section)
            if image_data is not None:
                filename = makePNGTitle(image_dir, 'mults_remaining')
                graphics.save_image(image_data, image_size, filename)
        except Exception as e:
            logging.exception(e)

    if data_updated and config.SHOW_OPERATOR_LEADERBOARD:
        try:
            image_data, image_size = graphics.draw_operator_leaderboard(size, qso_operators)
            if image_data is not None:
                filename = makePNGTitle(image_dir, 'operator_leaderboard')
                graphics.save_image(image_data, image_size, filename)
        except Exception as e:
            logging.exception(e)

    # New-operator displays: race-curve, roster, and YOY bar. Prior-ops data
    # comes from PRIOR_OPERATORS_DB (built by import_prior_operators.py) with
    # a fallback to PRIOR_DB_FILENAME for first-year setups.
    if data_updated and (config.SHOW_NEW_OPS_RACE or config.SHOW_NEW_OPS_ROSTER
                          or config.SHOW_NEW_OPS_YOY):
        try:
            db = sqlite3.connect(config.DATABASE_FILENAME)
            try:
                cur_first = dataaccess.get_operator_first_qsos(db.cursor())
            finally:
                db.close()
            # Consolidated prior-ops list (built by import_prior_operators.py).
            # Fall back to PRIOR_DB_FILENAME alone if the consolidated DB has
            # not been generated yet.
            prior_names = dataaccess.get_prior_operators_from_consolidated_db(
                getattr(config, 'PRIOR_OPERATORS_DB', ''))
            if not prior_names:
                prior_names, _, _ = dataaccess.get_prior_operator_names(config.PRIOR_DB_FILENAME)
            prior_curve = dataaccess.get_prior_first_qso_curve(config.PRIOR_DB_FILENAME) \
                if config.SHOW_NEW_OPS_RACE else []

            if config.SHOW_NEW_OPS_RACE:
                try:
                    image_data, image_size = graphics.draw_new_ops_race(
                        size, cur_first, prior_names, prior_curve,
                        prior_event_label=config.PRIOR_EVENT_LABEL)
                    if image_data is not None:
                        filename = makePNGTitle(image_dir, 'new_ops_race')
                        graphics.save_image(image_data, image_size, filename)
                except Exception as e:
                    logging.exception(e)

            if config.SHOW_NEW_OPS_ROSTER:
                try:
                    image_data, image_size = graphics.draw_new_ops_roster(
                        size, cur_first, prior_names, event_label=config.EVENT_NAME)
                    if image_data is not None:
                        filename = makePNGTitle(image_dir, 'new_ops_roster')
                        graphics.save_image(image_data, image_size, filename)
                except Exception as e:
                    logging.exception(e)

            if config.SHOW_NEW_OPS_YOY:
                try:
                    yoy_rows = dataaccess.get_yoy_new_op_counts(
                        getattr(config, 'PRIOR_OPERATORS_DB', ''),
                        event_label_regex=getattr(config, 'YOY_EVENT_REGEX', None))
                    cur_year = config.EVENT_START_TIME.year
                    cur_new = sum(1 for r in cur_first
                                  if r['name'].strip().lower() not in prior_names)
                    cur_total = len(cur_first)
                    # Sidebar-sized PNG (width ~ sidebar_width px, modest height).
                    sidebar_size = (600, 360)
                    image_data, image_size = graphics.draw_new_ops_yoy(
                        sidebar_size, yoy_rows, current_year=cur_year,
                        current_new_count=cur_new, current_total_count=cur_total)
                    if image_data is not None:
                        filename = makePNGTitle(image_dir, 'new_ops_yoy')
                        graphics.save_image(image_data, image_size, filename)
                    # Also render a slide-sized variant for the carousel.
                    image_data, image_size = graphics.draw_new_ops_yoy(
                        size, yoy_rows, current_year=cur_year,
                        current_new_count=cur_new, current_total_count=cur_total)
                    if image_data is not None:
                        filename = makePNGTitle(image_dir, 'new_ops_yoy_slide')
                        graphics.save_image(image_data, image_size, filename)
                except Exception as e:
                    logging.exception(e)
        except Exception as e:
            logging.exception(e)

    #if data_updated:   # Data is always updated since the sections map is always updated. Let rsync command handle this.
    if config.POST_FILE_COMMAND is not None:
       logging.debug('Executing command %s' % (config.POST_FILE_COMMAND))
       #subprocess is for a future change as os.system is deprecated
       #args=[]
       #args.append(config.POST_FILE_COMMAND)
       #subprocess.run(args,capture_output=False);
       os.system(config.POST_FILE_COMMAND)

    return last_qso_time


def write_index_html(image_dir):
    """Write an index.html page to the image directory for web viewing."""
    event_name = config.EVENT_NAME
    dwell = config.DISPLAY_DWELL_TIME
    mult_title = constants.get_mult_title()
    # EVENT_START_TIME / EVENT_END_TIME are naive UTC (compared against
    # datetime.utcnow() in dashboard.py). Emit as ISO 8601 with Z so the
    # browser parses them as UTC regardless of viewer locale.
    start_iso = config.EVENT_START_TIME.strftime('%Y-%m-%dT%H:%M:%SZ')
    end_iso = config.EVENT_END_TIME.strftime('%Y-%m-%dT%H:%M:%SZ')
    event_name_json = json.dumps(event_name)
    radio_poll = max(1, getattr(config, 'RADIO_POLL_SECONDS', 2))

    # Build slides list - base slides always included.
    # Each entry is (title, src, kind) where kind is 'img' (PNG written by
    # create_images) or 'iframe' (external URL). Note: Radio Status and Recent
    # QSOs are in the sidebar, not the carousel.
    slides = [
        (f'{mult_title} Map', 'sections_worked_map.png', 'img'),
        ('QSO Summary', 'qso_summary_table.png', 'img'),
        ('QSO Rates', 'qso_rates_table.png', 'img'),
        ('QSO Rate Over Time', 'qso_rates_graph.png', 'img'),
        ('QSOs by Operator', 'qso_operators_graph.png', 'img'),
        ('Operator Totals', 'qso_operators_table.png', 'img'),
        ('All Operator Stats', 'qso_operators_table_all.png', 'img'),
        ('QSOs by Station', 'qso_stations_graph.png', 'img'),
        ('QSOs by Band', 'qso_bands_graph.png', 'img'),
        ('QSOs by Mode', 'qso_modes_graph.png', 'img'),
        ('QSOs by Class', 'qso_classes_graph.png', 'img'),
        ('QSOs by Category', 'qso_categories_graph.png', 'img'),
    ]

    # Add optional slides based on config (radio_info is in sidebar)
    if config.SHOW_MULT_PROGRESS:
        slides.append(('Multiplier Progress', 'mults_progress.png', 'img'))
    if config.SHOW_MULT_REMAINING:
        slides.append(('Multipliers Remaining', 'mults_remaining.png', 'img'))
    if config.SHOW_OPERATOR_LEADERBOARD:
        slides.append(('Operator Leaderboard', 'operator_leaderboard.png', 'img'))
    if config.SHOW_NEW_OPS_RACE:
        slides.append(('New Operators Race', 'new_ops_race.png', 'img'))
    if config.SHOW_NEW_OPS_ROSTER:
        slides.append(('New Operators', 'new_ops_roster.png', 'img'))
    if config.SHOW_NEW_OPS_YOY:
        slides.append(('New Operators Year-Over-Year', 'new_ops_yoy_slide.png', 'img'))

    # External URL slides from [EXTERNAL_SLIDES]. Rendered as iframes with a
    # fallback link in case the remote site sends X-Frame-Options: DENY.
    for title, url in getattr(config, 'EXTERNAL_SLIDES', []):
        slides.append((title, url, 'iframe'))

    def _slide_html(title, src, kind):
        title_esc = title.replace('<', '&lt;').replace('>', '&gt;')
        if kind == 'iframe':
            src_attr = src.replace('"', '&quot;')
            # Mirror the bare iframe used by VK5GR-IOTA for ClubLog livestream
            # (id/name/frameborder/allowtransparency, no sandbox, no
            # referrerpolicy, no `allow`). Some sites' WebSocket/session
            # handshakes break under stricter iframe settings.
            iframe_name = 'iframe_' + ''.join(c if c.isalnum() else '_' for c in title)
            return (
                f'  <div class="slide" data-kind="iframe">'
                f'<h2>{title_esc}</h2>\n'
                f'    <div class="iframe-wrap">'
                f'<iframe id="{iframe_name}" name="{iframe_name}" src="{src_attr}"'
                f' frameborder="0" allowtransparency="true" loading="lazy"></iframe>'
                f'<div class="iframe-fallback">If this page does not load, '
                f'<a href="{src_attr}" target="_blank" rel="noopener">open it in a new tab</a>.'
                f'</div></div></div>'
            )
        return (
            f'  <div class="slide" data-kind="img">'
            f'<h2>{title_esc}</h2>\n'
            f'    <img src="{src}" alt="{title_esc}"></div>'
        )

    slides_html = '\n'.join(_slide_html(t, s, k) for t, s, k in slides)

    # Sidebar content - always visible.
    # The radio section keeps the static PNG (so rsync'd remote copies still
    # show data) AND a hidden #radio-live panel. When the JS poller can reach
    # /api/radio (i.e. served from the Pi), it swaps the PNG out for live
    # HTML; otherwise the PNG stays visible.
    sidebar_radio = ''
    if config.SHOW_RADIO_SIDEBAR:
        sidebar_radio = '''
      <div class="sidebar-section radio-section">
        <h3>Radio Status</h3>
        <img id="sidebar-radio" src="radio_info.png" alt="Radio Status">
        <div id="radio-live" hidden></div>
      </div>'''

    # New-operators sidebar: PNG fallback for rsync'd copies + a hidden
    # #new-ops-live panel that the JS poller populates from /api/new_ops.
    sidebar_new_ops = ''
    if config.SHOW_NEW_OPS_ROSTER:
        sidebar_new_ops = '''
      <div class="sidebar-section new-ops-section">
        <h3>New Operators</h3>
        <img id="sidebar-new-ops" src="new_ops_roster.png" alt="New Operators">
        <div id="new-ops-live" hidden></div>
      </div>'''

    # Year-over-year new-ops bar chart (no live overlay — chart is rendered
    # to PNG by headless.py each render cycle so the current year's bar
    # reflects the live count).
    sidebar_yoy = ''
    if config.SHOW_NEW_OPS_YOY:
        sidebar_yoy = '''
      <div class="sidebar-section yoy-section">
        <h3>New Ops Year-Over-Year</h3>
        <img id="sidebar-yoy" src="new_ops_yoy.png" alt="New Operators Year-Over-Year">
      </div>'''

    t = THEME  # Shorthand for template
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>N1MM View — {event_name}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: {t['bg_primary']};
    color: {t['text_primary']};
    overflow: hidden;
    height: 100vh;
    display: flex;
    flex-direction: column;
  }}
  header {{
    background: {t['bg_secondary']};
    padding: 0.6rem 1rem;
    border-bottom: 3px solid {t['border']};
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    flex-wrap: wrap;
  }}
  header h1 {{
    font-size: 1.25rem;
    color: {t['accent']};
    flex: 1 1 auto;
    text-align: center;
  }}
  .last-qso {{
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    justify-content: center;
    font-variant-numeric: tabular-nums;
    font-size: 0.85rem;
    color: {t['text_secondary']};
    flex-shrink: 1;
    min-width: 0;
    max-width: 40%;
  }}
  .last-qso .label {{
    color: {t['text_muted']};
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }}
  .last-qso .last-qso-line {{
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 100%;
  }}
  .last-qso .last-qso-line .call {{
    color: #5fff9c;
    font-weight: 600;
  }}
  .last-qso .last-qso-line .op {{ color: #ffd24a; }}
  .last-qso .last-qso-line .age {{
    font-weight: 600;
    padding: 0.05rem 0.4rem;
    border-radius: 4px;
    background: rgba(255,255,255,0.05);
  }}
  .last-qso .last-qso-line .age.fresh {{ color: #5fff9c; background: rgba(95,255,156,0.12); }}
  .last-qso .last-qso-line .age.warm  {{ color: #ffd24a; background: rgba(255,210,74,0.12); }}
  .last-qso .last-qso-line .age.stale {{ color: #ff6666; background: rgba(255,102,102,0.15); }}
  .last-qso .last-qso-line.stale {{ color: {t['text_muted']}; }}
  .clock {{
    display: flex;
    gap: 1rem;
    align-items: center;
    font-variant-numeric: tabular-nums;
    font-size: 0.85rem;
    color: {t['text_secondary']};
    flex-shrink: 0;
  }}
  .clock .label {{
    color: {t['text_muted']};
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-right: 0.25rem;
  }}
  .clock .countdown {{
    color: {t['accent']};
    font-weight: 600;
  }}
  .clock .countdown.urgent {{ color: #ff6666; }}
  .clock .countdown.over {{ color: {t['text_muted']}; }}
  @media (max-width: 700px) {{
    header {{ justify-content: center; }}
    header h1 {{ flex: 1 0 100%; order: -1; }}
    .last-qso {{ max-width: 100%; }}
    .clock {{ font-size: 0.75rem; gap: 0.6rem; }}
  }}
  .main-content {{
    flex: 1;
    display: flex;
    overflow: hidden;
    min-height: 0;
  }}
  .sidebar {{
    width: {t['sidebar_width']};
    min-width: {t['sidebar_min_width']};
    background: {t['bg_secondary']};
    border-right: 2px solid {t['border']};
    display: flex;
    flex-direction: column;
    overflow-y: auto;
    flex-shrink: 0;
  }}
  .sidebar-section {{
    padding: 0.5rem;
    border-bottom: 1px solid {t['border']};
  }}
  .sidebar-section h3 {{
    font-size: 0.85rem;
    color: {t['accent']};
    margin-bottom: 0.4rem;
    text-align: center;
  }}
  .sidebar-section img {{
    width: 100%;
    height: auto;
    display: block;
  }}
  /* Live radio panel (populated by /api/radio when available). */
  #radio-live {{ display: flex; flex-direction: column; gap: 0.35rem; }}
  #radio-live .station-hdr {{
    color: #ffd24a;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-top: 0.25rem;
    border-bottom: 1px solid {t['border']};
    padding-bottom: 0.1rem;
  }}
  #radio-live .radio-strip {{
    border: 2px solid #777;
    border-radius: 4px;
    padding: 0.3rem 0.4rem;
    background: rgba(0,0,0,0.25);
    font-variant-numeric: tabular-nums;
  }}
  #radio-live .radio-strip.tx {{ border-color: {t['accent']}; box-shadow: 0 0 6px rgba(233,69,96,0.4); }}
  #radio-live .radio-strip.stale {{ border-color: #444; opacity: 0.55; }}
  #radio-live .radio-strip.dup {{ border-color: #ff3b3b; box-shadow: 0 0 6px rgba(255,59,59,0.5); }}
  #radio-live .radio-strip.fromqso {{ background: rgba(255,207,106,0.08); }}
  #radio-live .station-hdr.dup {{ color: #ff5b5b; font-weight: 700; border-bottom-color: #ff3b3b; }}
  #radio-live .row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 0.4rem;
  }}
  #radio-live .label {{ color: {t['text_primary']}; font-size: 0.8rem; }}
  #radio-live .op {{ color: {t['text_secondary']}; font-size: 0.75rem; }}
  #radio-live .freq {{
    color: #5fff9c;
    font-size: 1.25rem;
    font-weight: 600;
    letter-spacing: 0.02em;
  }}
  #radio-live .tx-freq {{ color: #ffa45f; font-size: 0.85rem; }}
  #radio-live .status {{
    color: #6fd0ff;
    font-size: 0.7rem;
    letter-spacing: 0.04em;
  }}
  #radio-live .status .flag {{ margin-left: 0.4rem; }}
  #radio-live .status .flag.tx {{ color: {t['accent']}; font-weight: 600; }}
  #radio-live .status .flag.active {{ color: #ffd24a; font-weight: 600; }}
  #radio-live .status .flag.disc {{ color: #ff6666; }}
  #radio-live .radio-strip.stale .freq,
  #radio-live .radio-strip.stale .tx-freq,
  #radio-live .radio-strip.stale .status,
  #radio-live .radio-strip.stale .label,
  #radio-live .radio-strip.stale .op {{ color: #666; }}
  #radio-live .stale-note {{ font-size: 0.7rem; color: #888; }}
  #radio-live .empty {{
    color: {t['text_muted']};
    font-size: 0.75rem;
    text-align: center;
    padding: 0.4rem 0;
  }}
  #radio-live .disconnected {{
    color: #ff8a6a;
    font-size: 0.7rem;
    text-align: center;
    padding: 0.2rem 0;
  }}
  /* Live new-operators panel. */
  #new-ops-live {{ display: flex; flex-direction: column; gap: 0.25rem; }}
  #new-ops-live .new-ops-summary {{
    color: #ffd24a;
    font-size: 0.8rem;
    text-align: center;
    padding-bottom: 0.2rem;
    border-bottom: 1px solid {t['border']};
  }}
  #new-ops-live .new-op-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 0.4rem;
    font-variant-numeric: tabular-nums;
    padding: 0.15rem 0;
    border-bottom: 1px solid rgba(255,255,255,0.05);
  }}
  #new-ops-live .new-op-row .call {{
    color: #5fff9c;
    font-weight: 600;
    font-size: 0.9rem;
  }}
  #new-ops-live .new-op-row .meta {{
    color: {t['text_secondary']};
    font-size: 0.7rem;
  }}
  #new-ops-live .empty {{
    color: {t['text_muted']};
    font-size: 0.75rem;
    text-align: center;
    padding: 0.4rem 0;
  }}
  .carousel-container {{
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
  }}
  .carousel {{
    flex: 1;
    position: relative;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
  }}
  .slide {{
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    opacity: 0;
    transition: opacity 0.4s ease;
    pointer-events: none;
  }}
  .slide.active {{
    opacity: 1;
    pointer-events: auto;
  }}
  .slide h2 {{
    font-size: 1rem;
    padding: 0.4rem 0;
    color: {t['text_secondary']};
    flex-shrink: 0;
  }}
  .slide img {{
    max-width: 95%;
    max-height: calc(100vh - 7rem);
    object-fit: contain;
  }}
  .slide[data-kind="iframe"] {{ width: 100%; height: 100%; }}
  .iframe-wrap {{
    width: 95%;
    height: calc(100vh - 7rem);
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }}
  .iframe-wrap iframe {{
    flex: 1 1 auto;
    width: 100%;
    border: 1px solid {t['border']};
    background: #ffffff;
    border-radius: 4px;
  }}
  .iframe-fallback {{
    font-size: 0.75rem;
    color: {t['text_muted']};
    text-align: center;
    flex-shrink: 0;
  }}
  .iframe-fallback a {{ color: #6fd0ff; text-decoration: none; }}
  .iframe-fallback a:hover {{ text-decoration: underline; }}
  .nav-btn {{
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    background: rgba(15, 52, 96, 0.7);
    color: {t['text_primary']};
    border: none;
    font-size: 2rem;
    width: 3rem;
    height: 3rem;
    border-radius: 50%;
    cursor: pointer;
    z-index: 10;
    display: flex;
    align-items: center;
    justify-content: center;
    user-select: none;
    -webkit-tap-highlight-color: transparent;
  }}
  .nav-btn:hover {{ background: rgba(15, 52, 96, 0.95); }}
  .nav-btn.prev {{ left: 0.5rem; }}
  .nav-btn.next {{ right: 0.5rem; }}
  .dots {{
    display: flex;
    justify-content: center;
    gap: 0.4rem;
    padding: 0.4rem 0;
    flex-shrink: 0;
    flex-wrap: wrap;
  }}
  .dot {{
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: {t['dot_inactive']};
    cursor: pointer;
    transition: background 0.3s;
  }}
  .dot.active {{ background: {t['accent']}; }}
  footer {{
    text-align: center;
    padding: 0.3rem;
    font-size: 0.7rem;
    color: {t['text_muted']};
    flex-shrink: 0;
  }}
  @media (max-width: 900px) {{
    .sidebar {{ width: 240px; min-width: 200px; }}
  }}
  @media (max-width: 700px) {{
    .main-content {{ flex-direction: column; }}
    .sidebar {{
      width: 100%;
      max-height: 35vh;
      border-right: none;
      border-bottom: 2px solid {t['border']};
      flex-direction: row;
      flex-wrap: wrap;
    }}
    .sidebar-section {{ flex: 1; min-width: 150px; }}
  }}
</style>
</head>
<body>

<header>
  <div class="last-qso" id="last-qso-hdr">
    <span class="label">Last QSO</span>
    <span class="last-qso-line" id="last-qso-text">&mdash;</span>
  </div>
  <h1>{event_name}</h1>
  <div class="clock">
    <span><span class="label">UTC</span><span id="clk-utc">--:--:--</span></span>
    <span><span class="label">Local</span><span id="clk-local">--:--:--</span></span>
    <span class="countdown" id="clk-countdown">&mdash;</span>
  </div>
</header>

<div class="main-content">
  <div class="sidebar">
{sidebar_radio}
{sidebar_new_ops}
{sidebar_yoy}
    <div class="sidebar-section">
      <h3>Recent QSOs</h3>
      <img id="sidebar-qsos" src="last_qso_table.png" alt="Recent QSOs">
    </div>
  </div>

  <div class="carousel-container">
    <div class="carousel" id="carousel">
      <button class="nav-btn prev" id="prev">&lsaquo;</button>
      <button class="nav-btn next" id="next">&rsaquo;</button>

{slides_html}
    </div>

    <div class="dots" id="dots"></div>
  </div>
</div>

<footer>
  Powered by n1mm_view v{VERSION} &mdash; N1KDO &amp; NY4I
</footer>

<script>
(function() {{
  // --- Clock + countdown ------------------------------------------------
  var startMs = Date.parse('{start_iso}');
  var endMs = Date.parse('{end_iso}');
  var eventName = {event_name_json};
  var utcEl = document.getElementById('clk-utc');
  var localEl = document.getElementById('clk-local');
  var cdEl = document.getElementById('clk-countdown');

  function pad(n) {{ return (n < 10 ? '0' : '') + n; }}

  function fmtDelta(ms) {{
    var s = Math.floor(ms / 1000);
    var d = Math.floor(s / 86400); s -= d * 86400;
    var h = Math.floor(s / 3600); s -= h * 3600;
    var m = Math.floor(s / 60); s -= m * 60;
    return (d > 0 ? d + 'd ' : '') + pad(h) + ':' + pad(m) + ':' + pad(s);
  }}

  function tickClock() {{
    var now = new Date();
    utcEl.textContent =
      pad(now.getUTCHours()) + ':' + pad(now.getUTCMinutes()) + ':' + pad(now.getUTCSeconds());
    localEl.textContent =
      pad(now.getHours()) + ':' + pad(now.getMinutes()) + ':' + pad(now.getSeconds());

    var t = now.getTime();
    cdEl.classList.remove('urgent', 'over');
    if (t < startMs) {{
      cdEl.textContent = 'Starts in ' + fmtDelta(startMs - t);
      if (startMs - t < 3600000) cdEl.classList.add('urgent');
    }} else if (t < endMs) {{
      cdEl.textContent = 'Ends in ' + fmtDelta(endMs - t);
      if (endMs - t < 3600000) cdEl.classList.add('urgent');
    }} else {{
      cdEl.textContent = eventName + ' is over';
      cdEl.classList.add('over');
    }}
  }}
  tickClock();
  setInterval(tickClock, 1000);

  // --- Carousel ---------------------------------------------------------
  var slides = document.querySelectorAll('.slide');
  var dotsC = document.getElementById('dots');
  var cur = 0;
  var dwell = {dwell} * 1000;
  var timer;
  var sidebarRefresh = 15000; // refresh sidebar images every 15 seconds

  // build dots
  for (var i = 0; i < slides.length; i++) {{
    var d = document.createElement('span');
    d.className = 'dot';
    d.dataset.i = i;
    d.addEventListener('click', function() {{ go(+this.dataset.i); }});
    dotsC.appendChild(d);
  }}
  var dots = dotsC.querySelectorAll('.dot');

  function show(n) {{
    slides[cur].classList.remove('active');
    dots[cur].classList.remove('active');
    cur = (n + slides.length) % slides.length;
    slides[cur].classList.add('active');
    dots[cur].classList.add('active');
  }}

  function go(n) {{
    show(n);
    resetTimer();
  }}

  function advance() {{
    show(cur + 1);
    // reload carousel images when we wrap around to bust cache
    if (cur === 0) {{
      var t = Date.now();
      slides.forEach(function(s) {{
        var img = s.querySelector('img');
        if (img) img.src = img.src.split('?')[0] + '?t=' + t;
      }});
    }}
  }}

  function resetTimer() {{
    clearInterval(timer);
    timer = setInterval(advance, dwell);
  }}

  // Refresh sidebar images periodically
  function refreshSidebar() {{
    var t = Date.now();
    var radioImg = document.getElementById('sidebar-radio');
    var qsosImg = document.getElementById('sidebar-qsos');
    if (radioImg) radioImg.src = radioImg.src.split('?')[0] + '?t=' + t;
    if (qsosImg) qsosImg.src = qsosImg.src.split('?')[0] + '?t=' + t;
  }}
  setInterval(refreshSidebar, sidebarRefresh);

  // --- Live radio polling ----------------------------------------------
  // Tries /api/radio. When served from the Pi running webserver.py, it
  // succeeds and we swap the static radio_info.png for an HTML panel that
  // refreshes every {radio_poll}s. When the page is served from somewhere
  // else (e.g. an rsync'd remote site), /api/radio 404s and we leave the
  // PNG in place — same behavior as before this feature existed.
  (function setupRadioLive() {{
    var liveEl = document.getElementById('radio-live');
    var pngEl = document.getElementById('sidebar-radio');
    if (!liveEl) return;  // SHOW_RADIO_SIDEBAR is off

    var pollMs = {radio_poll} * 1000;
    var retryMs = 30000;
    var liveMode = false;

    function pad2(n) {{ return (n < 10 ? '0' : '') + n; }}

    function fmtFreq(hz) {{
      if (!hz) return '-.---.--';
      var khz = hz / 1000.0;
      var mhz = Math.floor(khz / 1000);
      var rem = khz - mhz * 1000;
      var khzPart = Math.floor(rem);
      var dec = Math.round((rem - khzPart) * 100);
      if (dec === 100) {{ dec = 0; khzPart += 1; }}
      return mhz + '.' + (khzPart < 100 ? (khzPart < 10 ? '00' : '0') : '') + khzPart + '.' + pad2(dec);
    }}

    function renderRadios(data) {{
      var radios = ((data && data.radios) || []).slice().sort(function(a, b) {{
        var an = (a.station_name || '').toUpperCase();
        var bn = (b.station_name || '').toUpperCase();
        if (an < bn) return -1;
        if (an > bn) return 1;
        return (a.radio_nr || 0) - (b.radio_nr || 0);
      }});
      var serverNow = (data && data.server_time) || Math.floor(Date.now() / 1000);
      liveEl.replaceChildren();
      if (!radios.length) {{
        var empty = document.createElement('div');
        empty.className = 'empty';
        empty.textContent = 'No radios reporting';
        liveEl.appendChild(empty);
        return;
      }}
      // Map station -> "BAND/GROUP" for live (non-stale) radios that share a
      // band + mode group, so the header can carry a duplicate alert.
      var dupLabel = {{}};
      for (var di = 0; di < radios.length; di++) {{
        var dr = radios[di];
        var drStale = (serverNow - (dr.last_update || serverNow)) > 60;
        if (dr.dup && !drStale) {{
          dupLabel[dr.station_name] = (dr.band || '?') + '/' + (dr.mode_group || '?');
        }}
      }}
      var currentStation = null;
      for (var i = 0; i < radios.length; i++) {{
        var r = radios[i];
        if (r.station_name !== currentStation) {{
          currentStation = r.station_name;
          var hdr = document.createElement('div');
          var hDup = dupLabel[currentStation];
          hdr.className = 'station-hdr' + (hDup ? ' dup' : '');
          hdr.textContent = '-- ' + currentStation +
            (hDup ? '  ** DUP ' + hDup + ' **' : '');
          liveEl.appendChild(hdr);
        }}
        var age = serverNow - (r.last_update || serverNow);
        var stale = age > 60;
        var tx = !!r.is_transmitting && !stale;
        var dup = !!r.dup && !stale;
        var fromqso = r.source === 'contactinfo';

        var strip = document.createElement('div');
        strip.className = 'radio-strip' + (tx ? ' tx' : '') + (stale ? ' stale' : '') +
          (dup ? ' dup' : '') + (fromqso ? ' fromqso' : '');

        // Row 1: radio label + operator
        var row1 = document.createElement('div');
        row1.className = 'row';
        var lbl = document.createElement('span');
        lbl.className = 'label';
        var radioLabel = 'R' + r.radio_nr;
        if (r.radio_name) radioLabel += '  ' + r.radio_name;
        if (fromqso) radioLabel += '  (via QSO)';
        lbl.textContent = radioLabel;
        row1.appendChild(lbl);

        var op = document.createElement('span');
        op.className = 'op';
        var opText = r.op_call ? 'Op: ' + r.op_call : '';
        if (stale) opText += (opText ? '  ' : '') + '(' + age + 's ago)';
        op.textContent = opText;
        row1.appendChild(op);
        strip.appendChild(row1);

        // Row 2: RX freq + TX freq if split
        var row2 = document.createElement('div');
        row2.className = 'row';
        var rx = document.createElement('span');
        rx.className = 'freq';
        rx.textContent = stale ? '-.---.--' : fmtFreq(r.freq);
        row2.appendChild(rx);
        if (!stale && r.is_split && r.tx_freq && r.tx_freq !== r.freq) {{
          var txf = document.createElement('span');
          txf.className = 'tx-freq';
          txf.textContent = 'TX: ' + fmtFreq(r.tx_freq);
          row2.appendChild(txf);
        }}
        strip.appendChild(row2);

        // Row 3: mode/RUN/SPLIT on the left, ACTIVE/TX/CONN on the right
        var row3 = document.createElement('div');
        row3.className = 'row status';
        var left = document.createElement('span');
        var leftParts = [];
        if (r.mode) leftParts.push(r.mode);
        leftParts.push(r.is_running ? 'RUN' : 'S&P');
        if (r.is_split) leftParts.push('SPLIT');
        left.textContent = leftParts.join('   ');
        row3.appendChild(left);

        var right = document.createElement('span');
        if (r.is_active) {{
          var a = document.createElement('span'); a.className = 'flag active'; a.textContent = 'ACTIVE'; right.appendChild(a);
        }}
        if (r.is_transmitting) {{
          var t1 = document.createElement('span'); t1.className = 'flag tx'; t1.textContent = 'TX'; right.appendChild(t1);
        }}
        var conn = document.createElement('span');
        conn.className = 'flag ' + (r.is_connected ? 'conn' : 'disc');
        conn.textContent = r.is_connected ? 'CONN' : 'DISC';
        right.appendChild(conn);
        row3.appendChild(right);
        strip.appendChild(row3);

        liveEl.appendChild(strip);
      }}
    }}

    function markDisconnected() {{
      var note = liveEl.querySelector('.disconnected');
      if (!note) {{
        note = document.createElement('div');
        note.className = 'disconnected';
        note.textContent = 'live updates paused';
        liveEl.insertBefore(note, liveEl.firstChild);
      }}
    }}

    function clearDisconnected() {{
      var note = liveEl.querySelector('.disconnected');
      if (note) note.remove();
    }}

    function enterLiveMode() {{
      if (liveMode) return;
      liveMode = true;
      if (pngEl) pngEl.style.display = 'none';
      liveEl.hidden = false;
    }}

    function poll() {{
      var ctrl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
      var timeoutId = ctrl ? setTimeout(function() {{ ctrl.abort(); }}, 4000) : null;
      var opts = ctrl ? {{ signal: ctrl.signal, cache: 'no-store' }} : {{ cache: 'no-store' }};
      fetch('api/radio', opts).then(function(resp) {{
        if (timeoutId) clearTimeout(timeoutId);
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return resp.json();
      }}).then(function(data) {{
        enterLiveMode();
        clearDisconnected();
        renderRadios(data);
        setTimeout(poll, pollMs);
      }}).catch(function() {{
        if (timeoutId) clearTimeout(timeoutId);
        if (liveMode) {{
          markDisconnected();
          setTimeout(poll, pollMs);
        }} else {{
          // Never connected — likely a remote rsync'd copy. Back off.
          setTimeout(poll, retryMs);
        }}
      }});
    }}

    poll();
  }})();

  // --- Live last-QSO header --------------------------------------------
  // Poll /api/last_qso on the same cadence as the radio panel so the header
  // surfaces "what did we just work" within ~RADIO_POLL_SECONDS of the QSO
  // landing in the DB. Falls back silently if the endpoint isn't reachable.
  (function setupLastQsoHeader() {{
    var el = document.getElementById('last-qso-text');
    if (!el) return;
    var pollMs = {radio_poll} * 1000;
    var retryMs = 30000;
    var liveMode = false;

    function pad2(n) {{ return (n < 10 ? '0' : '') + n; }}
    function fmtTimeZ(ts) {{
      var d = new Date(ts * 1000);
      return pad2(d.getUTCHours()) + ':' + pad2(d.getUTCMinutes()) + ':' + pad2(d.getUTCSeconds()) + 'Z';
    }}
    function fmtAge(secs) {{
      if (secs < 60) return secs + 's ago';
      if (secs < 3600) return Math.floor(secs / 60) + 'm ago';
      return Math.floor(secs / 3600) + 'h ago';
    }}

    function render(data) {{
      if (!data || !data.last_qso) {{
        el.textContent = 'no QSOs yet';
        el.className = 'last-qso-line stale';
        return;
      }}
      var q = data.last_qso;
      var serverNow = (data && data.server_time) || Math.floor(Date.now() / 1000);
      var age = Math.max(0, serverNow - (q.timestamp || serverNow));
      // Freshness classes: fresh < 30s, warm < 300s (5 min), stale beyond.
      var ageClass = 'fresh';
      if (age >= 300) ageClass = 'stale';
      else if (age >= 30) ageClass = 'warm';
      el.className = 'last-qso-line';

      el.replaceChildren();
      // Age first — this is the heartbeat indicator.
      var ageEl = document.createElement('span');
      ageEl.className = 'age ' + ageClass;
      ageEl.textContent = fmtAge(age);
      el.appendChild(ageEl);
      el.appendChild(document.createTextNode('  '));

      var call = document.createElement('span');
      call.className = 'call';
      call.textContent = q.callsign;
      el.appendChild(call);
      if (q.band || q.mode) {{
        el.appendChild(document.createTextNode(' '));
        var meta = document.createElement('span');
        meta.className = 'meta';
        var parts = [];
        if (q.band) parts.push(q.band);
        if (q.mode) parts.push(q.mode);
        meta.textContent = parts.join('/');
        el.appendChild(meta);
      }}
      if (q.operator) {{
        el.appendChild(document.createTextNode(' by '));
        var op = document.createElement('span');
        op.className = 'op';
        op.textContent = q.operator;
        el.appendChild(op);
      }}
    }}

    function poll() {{
      var ctrl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
      var timeoutId = ctrl ? setTimeout(function() {{ ctrl.abort(); }}, 4000) : null;
      var opts = ctrl ? {{ signal: ctrl.signal, cache: 'no-store' }} : {{ cache: 'no-store' }};
      fetch('api/last_qso', opts).then(function(resp) {{
        if (timeoutId) clearTimeout(timeoutId);
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return resp.json();
      }}).then(function(data) {{
        liveMode = true;
        render(data);
        setTimeout(poll, pollMs);
      }}).catch(function() {{
        if (timeoutId) clearTimeout(timeoutId);
        setTimeout(poll, liveMode ? pollMs : retryMs);
      }});
    }}

    poll();
  }})();

  // --- Live new-ops polling --------------------------------------------
  // /api/new_ops returns the same data the new_ops_roster PNG is built from.
  // When reachable we swap the PNG for an HTML list that updates every 30s.
  // On rsync'd remote copies the endpoint 404s and we leave the PNG alone.
  (function setupNewOpsLive() {{
    var liveEl = document.getElementById('new-ops-live');
    var pngEl = document.getElementById('sidebar-new-ops');
    if (!liveEl) return;  // SHOW_NEW_OPS_ROSTER is off

    var pollMs = 30000;
    var retryMs = 60000;
    var liveMode = false;

    function pad2(n) {{ return (n < 10 ? '0' : '') + n; }}
    function fmtTime(ts) {{
      var d = new Date(ts * 1000);
      return pad2(d.getUTCHours()) + ':' + pad2(d.getUTCMinutes()) + 'Z';
    }}

    function render(data) {{
      var newOps = (data && data.new_ops) || [];
      liveEl.replaceChildren();

      var hdr = document.createElement('div');
      hdr.className = 'new-ops-summary';
      var thisYear = (data && data.total_new) || 0;
      var lastYear = (data && data.prior_total);
      var lastLabel = (data && data.prior_event_label) || 'last event';
      hdr.textContent = thisYear + ' new this event' +
        (lastYear != null ? '  (' + lastYear + ' in ' + lastLabel + ')' : '');
      liveEl.appendChild(hdr);

      if (!newOps.length) {{
        var empty = document.createElement('div');
        empty.className = 'empty';
        empty.textContent = 'No new operators yet';
        liveEl.appendChild(empty);
        return;
      }}
      for (var i = 0; i < newOps.length; i++) {{
        var r = newOps[i];
        var row = document.createElement('div');
        row.className = 'new-op-row';
        var call = document.createElement('span');
        call.className = 'call';
        call.textContent = r.name;
        row.appendChild(call);
        var meta = document.createElement('span');
        meta.className = 'meta';
        meta.textContent = fmtTime(r.first_ts) + '  ' + (r.band || '') + '  ' + (r.mode || '');
        row.appendChild(meta);
        liveEl.appendChild(row);
      }}
    }}

    function enterLiveMode() {{
      if (liveMode) return;
      liveMode = true;
      if (pngEl) pngEl.style.display = 'none';
      liveEl.hidden = false;
    }}

    function poll() {{
      var ctrl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
      var timeoutId = ctrl ? setTimeout(function() {{ ctrl.abort(); }}, 4000) : null;
      var opts = ctrl ? {{ signal: ctrl.signal, cache: 'no-store' }} : {{ cache: 'no-store' }};
      fetch('api/new_ops', opts).then(function(resp) {{
        if (timeoutId) clearTimeout(timeoutId);
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return resp.json();
      }}).then(function(data) {{
        enterLiveMode();
        render(data);
        setTimeout(poll, pollMs);
      }}).catch(function() {{
        if (timeoutId) clearTimeout(timeoutId);
        setTimeout(poll, liveMode ? pollMs : retryMs);
      }});
    }}

    poll();
  }})();

  document.getElementById('prev').addEventListener('click', function() {{ go(cur - 1); }});
  document.getElementById('next').addEventListener('click', function() {{ go(cur + 1); }});

  // keyboard
  document.addEventListener('keydown', function(e) {{
    if (e.key === 'ArrowLeft') go(cur - 1);
    else if (e.key === 'ArrowRight') go(cur + 1);
  }});

  // swipe
  var x0 = null;
  var el = document.getElementById('carousel');
  el.addEventListener('touchstart', function(e) {{ x0 = e.touches[0].clientX; }}, {{passive: true}});
  el.addEventListener('touchend', function(e) {{
    if (x0 === null) return;
    var dx = e.changedTouches[0].clientX - x0;
    if (Math.abs(dx) > 40) go(cur + (dx < 0 ? 1 : -1));
    x0 = null;
  }});

  show(0);
  resetTimer();
}})();
</script>

</body>
</html>'''
    index_path = f'{image_dir}/index.html'
    try:
        with open(index_path, 'w') as f:
            f.write(html)
        logging.info('Wrote %s' % index_path)
    except Exception as e:
        logging.exception(e)


def main():
    logging.info('headless startup...')
    size = (1280, 1024)
    image_dir = config.IMAGE_DIR
    logging.debug("Checking for IMAGE_DIR")
    logging.info("IMAGE_DIR set to %s - checking if exists" % config.IMAGE_DIR)
    # Check if the dir given exists and create if necessary
    if config.IMAGE_DIR is not None:
        if not os.path.exists(config.IMAGE_DIR):
            logging.error("%s did not exist - creating..." % config.IMAGE_DIR)
            os.makedirs(config.IMAGE_DIR)
        if not os.path.exists(config.IMAGE_DIR):
            sys.exit('Image %s directory could not be created' % config.IMAGE_DIR)
        write_index_html(config.IMAGE_DIR)

    logging.info('creating world...')
#    base_map = graphics.create_map()

    run = True
    last_qso_timestamp = '' 
    logging.info('headless running...')
    while run:
        try:
            last_qso_timestamp = create_images(size, image_dir, last_qso_timestamp)
            time.sleep(config.HEADLESS_DWELL_TIME)
        except KeyboardInterrupt:
            logging.info('Keyboard interrupt, shutting down...')
            run = False

    logging.info('headless shutdown...')


if __name__ == '__main__':
    main()
