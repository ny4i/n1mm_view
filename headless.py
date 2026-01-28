#!/usr/bin/python3
"""
n1mm_view_headless
create images from contest data
non-interactive version.  This creates files on the disk and updates them periodically.
"""

import gc
import logging
import os
import re
import sqlite3
import sys
import time
#import subprocess

from config import Config
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

    try:
        image_data, image_size = graphics.draw_radio_info(size, radio_info)
        if image_data is not None:
            filename = makePNGTitle(image_dir, 'radio_info')
            graphics.save_image(image_data, image_size, filename)
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
    background: #1a1a2e;
    color: #e0e0e0;
    overflow: hidden;
    height: 100vh;
    display: flex;
    flex-direction: column;
  }}
  header {{
    background: #16213e;
    padding: 0.6rem 1rem;
    text-align: center;
    border-bottom: 3px solid #0f3460;
    flex-shrink: 0;
  }}
  header h1 {{
    font-size: 1.25rem;
    color: #e94560;
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
    color: #a0a0b8;
    flex-shrink: 0;
  }}
  .slide img {{
    max-width: 95%;
    max-height: calc(100vh - 7rem);
    object-fit: contain;
  }}
  .nav-btn {{
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    background: rgba(15, 52, 96, 0.7);
    color: #e0e0e0;
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
    background: #0f3460;
    cursor: pointer;
    transition: background 0.3s;
  }}
  .dot.active {{ background: #e94560; }}
  footer {{
    text-align: center;
    padding: 0.3rem;
    font-size: 0.7rem;
    color: #606080;
    flex-shrink: 0;
  }}
</style>
</head>
<body>

<header>
  <h1>{event_name}</h1>
</header>

<div class="carousel" id="carousel">
  <button class="nav-btn prev" id="prev">&lsaquo;</button>
  <button class="nav-btn next" id="next">&rsaquo;</button>

  <div class="slide"><h2>{constants.get_mult_title()} Map</h2>
    <img src="sections_worked_map.png" alt="{constants.get_mult_title()} Map"></div>
  <div class="slide"><h2>Recent QSOs</h2>
    <img src="last_qso_table.png" alt="Last QSOs Table"></div>
  <div class="slide"><h2>QSO Summary</h2>
    <img src="qso_summary_table.png" alt="QSO Summary Table"></div>
  <div class="slide"><h2>QSO Rates</h2>
    <img src="qso_rates_table.png" alt="QSO Rates Table"></div>
  <div class="slide"><h2>QSO Rate Over Time</h2>
    <img src="qso_rates_graph.png" alt="QSO Rates Graph"></div>
  <div class="slide"><h2>QSOs by Operator</h2>
    <img src="qso_operators_graph.png" alt="QSO Operators Pie Chart"></div>
  <div class="slide"><h2>Operator Totals</h2>
    <img src="qso_operators_table.png" alt="QSO Operators Table"></div>
  <div class="slide"><h2>All Operator Stats</h2>
    <img src="qso_operators_table_all.png" alt="QSO Operators Table All"></div>
  <div class="slide"><h2>QSOs by Station</h2>
    <img src="qso_stations_graph.png" alt="QSO Stations Pie Chart"></div>
  <div class="slide"><h2>QSOs by Band</h2>
    <img src="qso_bands_graph.png" alt="QSO Bands Pie Chart"></div>
  <div class="slide"><h2>QSOs by Mode</h2>
    <img src="qso_modes_graph.png" alt="QSO Modes Pie Chart"></div>
  <div class="slide"><h2>QSOs by Class</h2>
    <img src="qso_classes_graph.png" alt="QSO Classes Pie Chart"></div>
  <div class="slide"><h2>QSOs by Category</h2>
    <img src="qso_categories_graph.png" alt="QSO Categories Pie Chart"></div>
  <div class="slide"><h2>Radio Status</h2>
    <img src="radio_info.png" alt="Radio Status"></div>
</div>

<div class="dots" id="dots"></div>

<footer>
  Powered by n1mm_view &mdash; N1KDO &amp; NY4I
</footer>

<script>
(function() {{
  var slides = document.querySelectorAll('.slide');
  var dotsC = document.getElementById('dots');
  var cur = 0;
  var dwell = {dwell} * 1000;
  var timer;

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
    // reload images when we wrap around to bust cache
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
