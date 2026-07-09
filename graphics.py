# holds code that returns graphs.
#
#
import calendar
import json
import logging
import os
import datetime

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import cartopy.feature.nightshade as nightshade
import cartopy.io.shapereader as shapereader
import matplotlib
import matplotlib.backends.backend_agg as agg
import matplotlib.cm
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import pygame
from matplotlib.dates import HourLocator, DateFormatter, AutoDateLocator

from config import Config
from constants import *

__author__ = 'Jeffrey B. Otterson, N1KDO'
__copyright__ = 'Copyright 2016, 2019, 2021, 2024, 2025 Jeffrey B. Otterson and n1mm_view maintainers'
__license__ = 'Simplified BSD'

config = Config()

# UI Colors
RED = pygame.Color('#ff0000')
GREEN = pygame.Color('#33cc33')
BLUE = pygame.Color('#3333cc')
BRIGHT_BLUE = pygame.Color('#6666ff')
YELLOW = pygame.Color('#cccc00')
CYAN = pygame.Color('#00cccc')
MAGENTA = pygame.Color('#cc00cc')
ORANGE = pygame.Color('#ff9900')
BLACK = pygame.Color('#000000')
WHITE = pygame.Color('#ffffff')
GRAY = pygame.Color('#cccccc')
DARK_GRAY = pygame.Color('#666666')

# Map colors (used with matplotlib, not pygame). Configurable via the [MAP]
# section of the ini; these are the fallback defaults (see config.py).
MAP_OCEAN_COLOR = config.MAP_OCEAN_COLOR
MAP_LAKE_COLOR = config.MAP_LAKE_COLOR
MAP_LAND_COLOR = config.MAP_LAND_COLOR

# Radio strip font sizes
STRIP_FREQ_FONT_SIZE = 96
STRIP_LABEL_FONT_SIZE = 52
STRIP_STATUS_FONT_SIZE = 44

# Initialize font support
pygame.font.init()
view_font = pygame.font.Font('VeraMoBd.ttf', config.VIEW_FONT)
bigger_font = pygame.font.SysFont('VeraMoBd.ttf', config.BIGGER_FONT)
strip_freq_font = pygame.font.Font('VeraMoBd.ttf', STRIP_FREQ_FONT_SIZE)
strip_label_font = pygame.font.Font('VeraMoBd.ttf', STRIP_LABEL_FONT_SIZE)
strip_status_font = pygame.font.Font('VeraMoBd.ttf', STRIP_STATUS_FONT_SIZE)
view_font_height = view_font.get_height()

if matplotlib.__version__.startswith('3.6'):  # hack for raspberry pi.
    image_format = 'RGB'
else:
    image_format = 'ARGB'

logging.warning(f'set image format to {image_format}')
_map = None


def init_display():
    """
    set up the pygame display, full screen
    """

    # Check which frame buffer drivers are available
    # Start with fbcon since directfb hangs with composite output
    # x11 needed for Raspbian Stretch.  Put fbcon before directfb to not hang composite output
    drivers = ['x11', 'dga', 'fbcon', 'directfb', 'svgalib', 'ggi', 'wayland', 'kmsdrm', 'aalib', 'directx', 'windib',
               'windows']
    found = False
    driver = None
    for driver in drivers:
        # Make sure that SDL_VIDEODRIVER is set
        if not os.getenv('SDL_VIDEODRIVER'):
            os.putenv('SDL_VIDEODRIVER', driver)
        try:
            pygame.display.init()
        except pygame.error as ex:
            logging.debug(f'pygame error {ex}')
            logging.debug('Driver: %s failed.' % driver)
            continue
        found = True
        logging.info(f'Discovered compatible driver {driver}')
        break

    if not found or driver is None:
        raise Exception('No suitable video driver found!')

    size = (pygame.display.Info().current_w, pygame.display.Info().current_h)
    pygame.mouse.set_visible(0)
    if driver != 'directx':  # debugging hack runs in a window on Windows
        screen = pygame.display.set_mode(size, pygame.FULLSCREEN)
    else:
        logging.info('running in windowed mode')
        # set window origin for windowed usage
        os.putenv('SDL_VIDEO_WINDOW_POS', '0,0')
        # size = (size[0]-10, size[1] - 30)
        screen = pygame.display.set_mode(size, pygame.NOFRAME)

    logging.info('display size: %d x %d', size[0], size[1])
    return screen, size


def show_graph(screen, size, surf):
    """
    display a surface on the screen.
    """
    logging.debug('show_graph()')
    if surf is not None:
        x_offset = (size[0] - surf.get_width()) / 2
        screen.fill((0, 0, 0))
        screen.blit(surf, (x_offset, 0))
    logging.debug('show_graph() done')


def save_image(image_data, image_size, filename):
    if not all(image_size):
       logging.debug('Returning early from save_image since image_size is {0,0}')
       return
    surface = pygame.image.frombuffer(image_data, image_size, image_format)
    logging.debug('Saving file to %s', filename)
    pygame.image.save(surface, filename)


def make_blank_chart(size, title, message='— no data yet —'):
    """Render a blank placeholder chart: black background with a centered title
    and message. Used to refresh/clear every chart image on demand so the
    dashboard shows clean placeholders instead of stale data (e.g. after the
    database is wiped). Returns (raw_data, size) like the other chart builders."""
    surf = pygame.Surface(size)
    surf.fill(BLACK)
    title_surf = strip_label_font.render(title, True, WHITE)
    surf.blit(title_surf, title_surf.get_rect(centerx=size[0] // 2, top=30))
    msg_surf = strip_status_font.render(message, True, GRAY)
    surf.blit(msg_surf, msg_surf.get_rect(center=(size[0] // 2, size[1] // 2)))
    raw_data = pygame.image.tostring(surf, image_format)
    return raw_data, surf.get_size()


# A pie with more than this many slices crowds its small wedges into an
# unreadable pile of overlapping labels; above it, make_pie() renders a sorted
# horizontal bar chart instead (readable at any count / data range).
MAX_PIE_SLICES = 9


def make_barh(size, values, labels, title):
    """
    Sorted horizontal bar chart, used in place of a pie when there are too many
    categories (see MAX_PIE_SLICES). Bars run largest-first, top to bottom, each
    annotated with its count. Same dark theme and return shape as make_pie.
    """
    logging.debug('make_barh(...,...,%s)', title)
    pairs = sorted(zip(values, labels), key=lambda p: p[0], reverse=True)
    values = [p[0] for p in pairs]
    labels = [p[1] for p in pairs]

    width_inches = size[0] / 100.0
    height_inches = size[1] / 100.0
    fig = plt.figure(figsize=(width_inches, height_inches), dpi=100,
                     tight_layout={'pad': 1.0}, facecolor='k')
    ax = fig.add_subplot(111)
    ax.set_facecolor('k')

    n = len(values)
    palette = list(mcolors.TABLEAU_COLORS.values())
    colors = [palette[i % len(palette)] for i in range(n)]
    # Scale label size to the number of bars so 30+ rows still fit.
    fontsize = max(7, min(16, int(560 / n)))

    y = list(range(n))
    bars = ax.barh(y, values, color=colors, edgecolor='k', linewidth=0.25)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, color='w', fontsize=fontsize)
    ax.invert_yaxis()  # largest bar on top
    ax.bar_label(bars, labels=[str(v) for v in values],
                 padding=3, color='w', fontsize=fontsize)

    ax.set_title(title, color='white', size=48, weight='bold')
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.get_xaxis().set_visible(False)
    ax.set_xlim(0, max(values) * 1.12)  # headroom so the count labels don't clip

    canvas = agg.FigureCanvasAgg(fig)
    canvas.draw()
    renderer = canvas.get_renderer()
    canvas_size = canvas.get_width_height()
    if image_format == 'ARGB':
        raw_data = renderer.tostring_argb()
    else:
        raw_data = renderer.tostring_rgb()

    plt.close(fig)
    logging.debug('make_barh(...,...,%s) done', title)
    return raw_data, canvas_size


def make_pie(size, values, labels, title):
    """
    make a pie chart using matplotlib.
    return the chart as a pygame surface
    make the pie chart a square that is as tall as the display.

    Falls back to a horizontal bar chart when there are too many categories for
    a pie to stay legible (see MAX_PIE_SLICES).
    """
    if len(values) > MAX_PIE_SLICES:
        return make_barh(size, values, labels, title)
    logging.debug('make_pie(...,...,%s)', title)
    new_labels = []
    for i in range(0, len(labels)):
        new_labels.append(f'{labels[i]} ({values[i]})')

    width_inches = size[0] / 100.0
    height_inches = size[1] / 100.0
    fig = plt.figure(figsize=(width_inches, height_inches), dpi=100, tight_layout={'pad': 0.10, }, facecolor='k')
    ax = fig.add_subplot(111)
    ax.pie(values, labels=new_labels, autopct='%1.1f%%', textprops={'color': 'w', 'fontsize': 14},
           wedgeprops={'linewidth': 0.25}, colors=mcolors.TABLEAU_COLORS)
    ax.set_title(title, color='white', size=48, weight='bold')

    # No legend: each slice is already labelled with its name and count around
    # the pie, so a top-5 legend was redundant and collided with the slice
    # labels in the upper-right corner. High-cardinality data goes to make_barh
    # (see MAX_PIE_SLICES), so pies here always have few, well-spaced labels.

    canvas = agg.FigureCanvasAgg(fig)
    canvas.draw()
    renderer = canvas.get_renderer()
    canvas_size = canvas.get_width_height()
    if image_format == 'ARGB':
        raw_data = renderer.tostring_argb()
    else:
        raw_data = renderer.tostring_rgb()

    plt.close(fig)

    logging.debug('make_pie(...,...,%s) done', title)
    return raw_data, canvas_size


def qso_operators_graph(size, qso_operators):
    """
    create the QSOs by Operators pie chart
    """
    # calculate QSO by Operator
    if qso_operators is None or len(qso_operators) == 0:
        return None, (0, 0)
    labels = []
    values = []
    for d in qso_operators:
        labels.append(d[0])
        values.append(d[1])
    return make_pie(size, values, labels, "QSOs by Operator")


def qso_classes_graph(size, qso_classes):
    """
    create the QSOs by Class pie chart
    """
    if qso_classes is None or len(qso_classes) == 0:
        return None, (0, 0)
    # Classes are validated upstream (invalid exchanges are bucketed into '?'),
    # so the FD class set is small and bounded -- show each as its own slice
    # rather than collapsing the small ones into an 'others' slice.
    qso_classes = sorted(qso_classes, key=lambda x: x[0], reverse=True)

    labels = []
    values = []
    for d in qso_classes:
        labels.append(d[1])
        values.append(d[0])
    return make_pie(size, values, labels, "QSOs by Class")

def qso_categories_graph(size, qso_categories):
    """
    create the QSOs by Category pie chart
    """
    if qso_categories is None or len(qso_categories) == 0:
        return None, (0, 0)
    qso_categories = sorted(qso_categories, key=lambda x: x[0], reverse=True)
    labels = []
    values = []
    for d in qso_categories:
        labels.append(CATEGORY_NAMES.get(d[1], d[1]))
        values.append(d[0])
    return make_pie(size, values, labels, "QSOs by Category")

def qso_table(size, qsos):
    """
    create the a table of the qso log
    """
    if len(qsos) == 0:
        return None, (0, 0)

    count = 0
    mult_header = 'State' if config.MULTS == 'STATES' else 'Section'
    cells = [['Time', 'Call', 'Band', 'Mode', 'Operator', mult_header]] #, 'Station']]
    
    for d in qsos[:10]:
        cells.append( ['%s' % datetime.datetime.utcfromtimestamp(d[0]).strftime('%m-%d-%y %Tz') # Time
                     ,'%s' % d[1] # Call
                     ,'%s' % d[2] # Band
                     ,'%s' % d[3] # Mode
                     ,'%s' % d[4] # Operator
                     ,'%s' % d[6] # Section
       #              ,'%s' % d[7] # Station
                     ])
        count += 1

    if count == 0:
        return None, (0, 0)
    else:
        return draw_table(size, cells, "Last 10 QSOs")
        
def qso_operators_table(size, qso_operators):
    """
    create the Top 5 QSOs by Operators table
    """
    if len(qso_operators) == 0:
        return None, (0, 0)

    count = 0
    cells = [['Operator', 'QSOs']]
    for d in qso_operators:
        cells.append(['%s' % d[0], '%5d' % d[1]])
        count += 1
        if count >= 5:
            break

    if count == 0:
        return None, (0, 0)
    else:
        return draw_table(size, cells, "Top 5 Operators", bigger_font)


def qso_operators_table_all(size, qso_operators):
    """
    create the QSOs by All Operators table
    """
    if len(qso_operators) == 0:
        return None, (0, 0)

    data_rows = [['%s' % d[0], '%5d' % d[1]] for d in qso_operators]
    header, rows, label_cols = maybe_two_up(['Operator', 'QSOs'], data_rows, {1})
    cells = [header] + rows
    return draw_table(size, cells, "QSOs by All Operators", bigger_font,
                      label_cols=label_cols)


def qso_stations_graph(size, qso_stations):
    """
    create the QSOs by Station pie chart
    """
    if qso_stations is None or len(qso_stations) == 0:
        return None, (0, 0)
    labels = []
    values = []
    # for d in qso_stations:
    for d in sorted(qso_stations, key=lambda count: count[1], reverse=True):
        labels.append(d[0])
        values.append(d[1])
    return make_pie(size, values, labels, "QSOs by Station")


def qso_bands_graph(size, qso_band_modes):
    """
    create the QSOs by Band pie chart
    """
    if qso_band_modes is None or len(qso_band_modes) == 0:
        return None, (0, 0)

    labels = []
    values = []
    band_data = [[band, 0] for band in range(0, Bands.count())]
    total = 0
    for i in range(0, Bands.count()):
        band_data[i][1] = qso_band_modes[i][1] + qso_band_modes[i][2] + qso_band_modes[i][3]
        total += band_data[i][1]

    if total == 0:
        return None, (0, 0)

    for bd in sorted(band_data[1:], key=lambda count: count[1], reverse=True):
        if bd[1] > 0:
            labels.append(Bands.BANDS_TITLE[bd[0]])
            values.append(bd[1])
    return make_pie(size, values, labels, 'QSOs by Band')


def qso_modes_graph(size, qso_band_modes):
    """
    create the QSOs by Mode pie chart
    """
    if qso_band_modes is None or len(qso_band_modes) == 0:
        return None, (0, 0)

    labels = []
    values = []
    mode_data = [[mode, 0] for mode in range(0, len(Modes.SIMPLE_MODES_LIST))]
    total = 0
    for i in range(0, Bands.count()):
        for mode_num in range(1, len(Modes.SIMPLE_MODES_LIST)):
            mode_data[mode_num][1] += qso_band_modes[i][mode_num]
            total += qso_band_modes[i][mode_num]

    if total == 0:
        return None, (0, 0)

    for md in sorted(mode_data[1:], key=lambda count: count[1], reverse=True):
        if md[1] > 0:
            labels.append(Modes.SIMPLE_MODES_LIST[md[0]])
            values.append(md[1])
    return make_pie(size, values, labels, "QSOs by Mode")


def make_score_table(qso_band_modes):
    """
    create the score table from data
    """
    # Only render the simple-mode columns the contest allows (config.CONTEST_MODES).
    # Canonical CW/PHONE/DATA order is preserved by walking SIMPLE_MODES_LIST.
    active_modes = [i for i in range(1, len(Modes.SIMPLE_MODES_LIST))
                    if Modes.SIMPLE_MODES_LIST[i] in config.CONTEST_MODES]

    cell_data = [[0 for m in Modes.SIMPLE_MODES_LIST] for b in Bands.BANDS_TITLE]

    for band_num in range(1, Bands.count()):
        for mode_num in active_modes:
            cell_data[band_num][mode_num] = qso_band_modes[band_num][mode_num]
            cell_data[band_num][0] += qso_band_modes[band_num][mode_num]
            cell_data[0][mode_num] += qso_band_modes[band_num][mode_num]

    total = 0
    for mode_num in active_modes:
        total += cell_data[0][mode_num]
    cell_data[0][0] = total

    # '%5s' keeps the original column widths: 'CW'->'   CW', 'Phone', ' Data'.
    def _mode_label(name):
        return name if name == 'CW' else name.title()

    # the totals are in the 0th row and 0th column, move them to last.
    header = [''] + ['%5s' % _mode_label(Modes.SIMPLE_MODES_LIST[i])
                     for i in active_modes] + ['Total']
    cell_text = [header]
    band_num = 0
    for row in cell_data[1:]:
        band_num += 1
        row_text = ['%5s' % Bands.BANDS_TITLE[band_num]]

        for mode_num in active_modes:
            row_text.append('%5d' % row[mode_num])
        row_text.append('%5d' % row[0])
        cell_text.append(row_text)

    row = cell_data[0]
    row_text = ['Total']
    for mode_num in active_modes:
        row_text.append('%5d' % row[mode_num])
    row_text.append('%5d' % row[0])
    cell_text.append(row_text)
    return cell_text


def qso_summary_table(size, qso_band_modes):
    """
    create the QSO Summary Table
    """
    return draw_table(size, make_score_table(qso_band_modes), "QSOs Summary")


def qso_rates_table(size, operator_qso_rates):
    """
    create the QSO Rates by Operator table
    """
    if operator_qso_rates is None or len(operator_qso_rates) < 3:
        return None, (0, 0)
    else:
        return draw_table(size, operator_qso_rates, "QSO/Hour Rates")


def qso_rates_graph(size, qsos_per_hour):
    """
    make the qsos per hour per band chart
    returns a pygame surface
    """
    
    title = 'QSOs per Hour by Band'
    qso_counts = [[], [], [], [], [], [], [], [], [], []]

    if qsos_per_hour is None or len(qsos_per_hour) == 0:
        logging.debug('No QSOs so size will be invalid')
        return None, (0, 0)

    data_valid = len(qsos_per_hour) != 0

    for qpm in qsos_per_hour:
        for i in range(0, Bands.count()):
            c = qpm[i]
            cl = qso_counts[i]
            cl.append(c)
    # TODO FIXME remove bands with no data here?
    logging.debug('make_plot(...,...,%s)', title)
    width_inches = size[0] / 100.0
    height_inches = size[1] / 100.0
    fig = plt.Figure(figsize=(width_inches, height_inches), dpi=100, tight_layout={'pad': 0.10}, facecolor='black')

    if matplotlib.__version__[0] == '1':
        ax = fig.add_subplot(111, axis_bgcolor='black')
    else:
        ax = fig.add_subplot(111, facecolor='black')

    ax.set_title(title, color='white', size=48, weight='bold')

    st = calendar.timegm(config.EVENT_START_TIME.timetuple())
    lt = calendar.timegm(qsos_per_hour[-1][0].timetuple())
    if data_valid:
        dates = matplotlib.dates.date2num(qso_counts[0])
        labels = Bands.BANDS_TITLE[1:]
        if lt < st:
            start_date = dates[0]  # matplotlib.dates.date2num(qsos_per_hour[0][0].timetuple())
            end_date = dates[-1]  # matplotlib.dates.date2num(qsos_per_hour[-1][0].timetuple())
        else:
            start_date = matplotlib.dates.date2num(config.EVENT_START_TIME)
            end_date = matplotlib.dates.date2num(config.EVENT_END_TIME)
        # Ensure minimum 1-day span to prevent HourLocator from generating excessive ticks
        if end_date - start_date < 1.0:
            end_date = start_date + 1.0
        ax.set_xlim(start_date, end_date)

        ax.stackplot(dates, qso_counts[1], qso_counts[2], qso_counts[3], qso_counts[4], qso_counts[5], qso_counts[6],
                     qso_counts[7], qso_counts[8], qso_counts[9], labels=labels, colors=mcolors.TABLEAU_COLORS,
                     linewidth=0.2)
        # Soft grid so it frames the data without drowning the thin band lines.
        ax.grid(True, color='#555555', linewidth=0.5, alpha=0.5)
        legend = ax.legend(loc='best', ncol=Bands.count() - 1)
        legend.get_frame().set_color((0, 0, 0, 0))
        legend.get_frame().set_edgecolor('w')
        for text in legend.get_texts():
            plt.setp(text, color='w')
        ax.spines['left'].set_color('w')
        ax.spines['right'].set_color('w')
        ax.spines['top'].set_color('w')
        ax.spines['bottom'].set_color('w')
        ax.tick_params(axis='y', colors='w')
        ax.tick_params(axis='x', colors='w')
        ax.set_ylabel('QSO Rate/Hour', color='w', size='x-large', weight='bold')
        ax.set_xlabel('UTC Hour', color='w', size='x-large', weight='bold')
        # Adaptive tick/grid density: scales to the actual span so a wide
        # window (sparse pre-event data spanning days) doesn't pack the axis
        # with hundreds of gridlines, while a normal event window still gets
        # hourly-ish ticks.
        ax.xaxis.set_major_locator(AutoDateLocator(minticks=4, maxticks=12))
        ax.xaxis.set_major_formatter(DateFormatter('%H'))
    canvas = agg.FigureCanvasAgg(fig)
    canvas.draw()
    renderer = canvas.get_renderer()
    if image_format == 'ARGB':
        raw_data = renderer.tostring_argb()
    else:
        raw_data = renderer.tostring_rgb()

    plt.close(fig)
    canvas_size = canvas.get_width_height()
    return raw_data, canvas_size


# A single-column table taller than this many data rows is laid out in two
# side-by-side groups (e.g. the all-operators / leaderboard tables) so it does
# not run off the bottom of the display.
TABLE_TWO_UP_MIN = 17


def maybe_two_up(header, data_rows, label_cols):
    """Optionally lay a long table out in two side-by-side groups.

    header: list of column titles for ONE group.
    data_rows: list of rows (each a list matching header) for ONE group.
    label_cols: 1-based label columns within ONE group (rendered white).

    Returns (header, rows, label_cols) ready for draw_table: unchanged when the
    table is short, or doubled-width (left group = first half, right group =
    second half, shorter side blank-padded) when it exceeds TABLE_TWO_UP_MIN.
    """
    if len(data_rows) <= TABLE_TWO_UP_MIN:
        return list(header), data_rows, set(label_cols)
    ncol = len(header)
    half = (len(data_rows) + 1) // 2
    blank = [''] * ncol
    rows = []
    for i in range(half):
        right = data_rows[half + i] if half + i < len(data_rows) else blank
        rows.append(list(data_rows[i]) + list(right))
    new_header = list(header) + list(header)
    new_label_cols = set(label_cols) | {c + ncol for c in label_cols}
    return new_header, rows, new_label_cols


def draw_table(size, cell_text, title, font=None, label_cols=None):
    """
    draw a table

    label_cols: 1-based column numbers rendered in the header (white) colour
    rather than the gray data colour. Defaults to {1} (the first column), the
    historical behaviour. Multi-up tables (e.g. two Operator|QSOs pairs side by
    side) pass the column number of each label column, e.g. {1, 3}.
    """
    logging.debug('draw_table(...,%s)', title)
    if font is None:
        table_font = view_font
    else:
        table_font = font
    if label_cols is None:
        label_cols = {1}

    text_y_offset = 4
    text_x_offset = 4
    line_width = 4

    # calculate column widths
    rows = len(cell_text)
    cols = len(cell_text[0])
    col_widths = [0] * cols
    widest = 0
    for row in cell_text:
        col_num = 0
        for col in row:
            text_size = table_font.size(col)
            text_width = text_size[0] + 2 * text_x_offset
            if text_width > col_widths[col_num]:
                col_widths[col_num] = text_width
            if text_width > widest:
                widest = text_width
            col_num += 1

    header_width = table_font.size(title)[0]
    table_width = sum(col_widths) + line_width / 2
    row_height = table_font.get_height()
    height = (rows + 1) * row_height + line_width / 2
    surface_width = table_width
    x_offset = 0
    if header_width > surface_width:
        surface_width = header_width
        x_offset = (header_width - table_width) / 2

    surf = pygame.Surface((surface_width, height))

    surf.fill(BLACK)
    text_color = GRAY
    head_color = WHITE
    grid_color = GRAY

    # draw the title
    text = table_font.render(title, True, head_color)
    textpos = text.get_rect()
    textpos.y = 0
    textpos.centerx = surface_width / 2
    surf.blit(text, textpos)

    starty = row_height
    origin = (x_offset, row_height)

    # draw the grid
    x = x_offset
    y = starty
    for r in range(0, rows + 1):
        sp = (x, y)
        ep = (x + table_width, y)
        pygame.draw.line(surf, grid_color, sp, ep, line_width)
        y += row_height

    x = x_offset
    y = starty
    for cw in col_widths:
        sp = (x, y)
        ep = (x, y + height)
        pygame.draw.line(surf, grid_color, sp, ep, line_width)
        x += cw
    sp = (x, y)
    ep = (x, y + height)
    pygame.draw.line(surf, grid_color, sp, ep, line_width)

    y = starty + text_y_offset
    row_number = 0
    for row in cell_text:
        row_number += 1
        x = origin[0]
        column_number = 0
        for col in row:
            x += col_widths[column_number]
            column_number += 1
            if row_number == 1 or column_number in label_cols:
                text = table_font.render(col, True, head_color)
            else:
                text = table_font.render(col, True, text_color)
            textpos = text.get_rect()
            textpos.y = y - text_y_offset
            textpos.right = x - text_x_offset
            surf.blit(text, textpos)
        y += row_height
    logging.debug('draw_table(...,%s) done', title)
    size = surf.get_size()
    data = pygame.image.tostring(surf, image_format)

    return data, size


def format_frequency(freq_hz):
    """
    Convert frequency in Hz to display format like '14.250.00'.
    Returns '-.---.--' for zero or None.
    """
    if not freq_hz:
        return '-.---.--'
    freq_khz = freq_hz / 1000.0
    mhz = int(freq_khz / 1000)
    remainder_khz = freq_khz - mhz * 1000
    khz_part = int(remainder_khz)
    decimal_part = int(round((remainder_khz - khz_part) * 100))
    return '%d.%03d.%02d' % (mhz, khz_part, decimal_part)


def draw_radio_info(size, radios):
    """
    Draw flight-strip style radio status display.
    Returns (raw_data, (w, h)) or (None, (0, 0)).
    """
    import time as _time

    if not radios:
        return None, (0, 0)

    now = int(_time.time())
    stale_threshold = 60  # seconds - clear frequency data after this

    # Drop rows older than RADIO_HIDE_SECONDS so leftovers from previous
    # test sessions don't clutter the display.
    hide = getattr(config, 'RADIO_HIDE_SECONDS', 0)
    if hide and hide > 0:
        radios = [r for r in radios if (now - r['last_update']) <= hide]
        if not radios:
            return None, (0, 0)

    logging.debug('draw_radio_info()')

    # Precompute band + simple mode group per radio and count band/group pairs so
    # we can alert when two radios share a band+category (CW/PHONE/DATA).
    from collections import Counter
    bm_counts = Counter()
    for r in radios:
        b = Bands.freq_to_band(r.get('freq'))
        g = Modes.get_simple_mode_name(r.get('mode') or '')
        r['_band'] = b
        r['_group'] = g
        # Only live radios count toward collisions. Stale (greyed-out) leftovers
        # of stations that have gone away must not flag a live radio as a DUP.
        r['_live'] = (now - r['last_update']) <= stale_threshold
        if r['_live'] and b and g not in (None, 'N/A'):
            bm_counts[(b, g)] += 1
    # Flag dup radios and remember a per-station "BAND/GROUP" label for the header.
    dup_stations = {}
    for r in radios:
        r['_dup'] = bool(r['_live'] and r['_band'] and r['_group'] not in (None, 'N/A')
                         and bm_counts[(r['_band'], r['_group'])] > 1)
        if r['_dup']:
            dup_stations[r['station_name']] = '%s/%s' % (r['_band'], r['_group'])

    surface_width = size[0]

    # Lay out vertically and size the surface to fit EVERY station + radio. The
    # rsync'd remote shows this static PNG (no /api/radio to swap to the live
    # scrollable panel), so a fixed height would silently drop stations off the
    # bottom. Compute the needed height from the content instead.
    strip_margin = 10
    strip_padding = 6
    border_width = 3
    line1_h = strip_label_font.get_height()
    line2_h = strip_freq_font.get_height()
    line3_h = strip_status_font.get_height()
    strip_height = line1_h + line2_h + line3_h + strip_padding * 4
    strip_width = surface_width - 2 * strip_margin
    title_h = strip_label_font.get_height()
    num_stations = len(set(r['station_name'] for r in radios))
    surface_height = (title_h + 15
                      + num_stations * (line1_h + 4)
                      + len(radios) * (strip_height + 4)
                      + strip_margin)
    surf = pygame.Surface((surface_width, surface_height))
    surf.fill(BLACK)

    # Colors for radio info display
    border_tx = RED
    border_default = GRAY
    dim_color = DARK_GRAY
    title_color = WHITE
    label_color = WHITE
    freq_color = GREEN
    status_color = CYAN
    header_color = YELLOW
    tx_freq_color = ORANGE

    # Title
    title_text = strip_label_font.render('Radio Status', True, title_color)
    title_rect = title_text.get_rect()
    title_rect.centerx = surface_width // 2
    title_rect.y = 5
    surf.blit(title_text, title_rect)

    y_cursor = title_rect.bottom + 10

    # Group radios by station name
    current_station = None
    for radio in radios:
        station = radio['station_name']
        is_stale = (now - radio['last_update']) > stale_threshold
        stale_seconds = now - radio['last_update']
        is_dup = radio.get('_dup', False)
        is_contact = radio.get('source') == 'contactinfo'
        is_offband = Bands.is_out_of_band(radio.get('freq'), radio.get('_group'))

        # Station header
        if station != current_station:
            current_station = station
            station_dup = station in dup_stations
            if station_dup and not is_stale:
                hdr_color = RED
                hdr_str = '-- %s  ** DUP %s ** ' % (station, dup_stations[station])
            else:
                hdr_color = dim_color if is_stale else header_color
                hdr_str = '-- %s ' % station
            header_text = strip_label_font.render(hdr_str, True, hdr_color)
            # Draw header with line
            surf.blit(header_text, (strip_margin, y_cursor))
            line_x = strip_margin + header_text.get_width() + 4
            line_y = y_cursor + line1_h // 2
            if line_x < surface_width - strip_margin:
                pygame.draw.line(surf, hdr_color, (line_x, line_y),
                                 (surface_width - strip_margin, line_y), 1)
            y_cursor += line1_h + 4

        if y_cursor + strip_height > surface_height:
            break  # no room for more strips

        # Determine border color
        if radio['is_transmitting']:
            b_color = border_tx
        else:
            b_color = border_default

        if is_stale:
            b_color = dim_color

        # Out-of-band -> orange border; duplicate band/mode -> red (takes priority).
        if is_offband and not is_stale:
            b_color = ORANGE
        if is_dup and not is_stale:
            b_color = RED

        # Draw strip border
        strip_rect = pygame.Rect(strip_margin, y_cursor, strip_width, strip_height)
        pygame.draw.rect(surf, b_color, strip_rect, border_width)

        inner_x = strip_margin + strip_padding + border_width
        inner_right = strip_margin + strip_width - strip_padding - border_width
        text_y = y_cursor + strip_padding + border_width

        # Choose text colors based on stale status
        l_color = dim_color if is_stale else label_color
        f_color = dim_color if is_stale else freq_color
        s_color = dim_color if is_stale else status_color
        tf_color = dim_color if is_stale else tx_freq_color

        # Line 1: Radio number + name, operator right-aligned
        radio_label = 'R%d' % radio['radio_nr']
        if radio['radio_name']:
            radio_label += '  %s' % radio['radio_name']
        if is_contact:
            radio_label += '  (via QSO)'
        line1_surf = strip_label_font.render(radio_label, True, l_color)
        surf.blit(line1_surf, (inner_x, text_y))

        op_text = ''
        if radio['op_call']:
            op_text = 'Op: %s' % radio['op_call']
        if is_stale:
            op_text += '  (%ds ago)' % stale_seconds
        if op_text:
            op_surf = strip_label_font.render(op_text, True, l_color)
            op_rect = op_surf.get_rect()
            op_rect.right = inner_right
            op_rect.y = text_y
            surf.blit(op_surf, op_rect)

        text_y += line1_h + strip_padding

        # Line 2: RX frequency (large), TX frequency if split (right-aligned)
        # Clear frequency data if stale (no update in 60+ seconds)
        if is_stale:
            rx_str = '-.---.--'
        else:
            rx_str = format_frequency(radio['freq'])
        rx_surf = strip_freq_font.render(rx_str, True, f_color)
        surf.blit(rx_surf, (inner_x, text_y))

        if not is_stale and radio['is_split'] and radio['tx_freq'] and radio['tx_freq'] != radio['freq']:
            tx_str = 'TX: %s' % format_frequency(radio['tx_freq'])
            tx_surf = strip_freq_font.render(tx_str, True, tf_color)
            tx_rect = tx_surf.get_rect()
            tx_rect.right = inner_right
            tx_rect.y = text_y
            surf.blit(tx_surf, tx_rect)
        elif not is_stale and is_offband:
            ob_surf = strip_status_font.render('OUT-OF-BAND', True, ORANGE)
            ob_rect = ob_surf.get_rect()
            ob_rect.right = inner_right
            ob_rect.centery = text_y + line2_h // 2
            surf.blit(ob_surf, ob_rect)

        text_y += line2_h + strip_padding

        # Line 3: Mode, RUN/S&P, SPLIT, TX, CONN/DISC
        status_parts = []
        if radio['mode']:
            status_parts.append(radio['mode'])
        if radio['is_running']:
            status_parts.append('RUN')
        else:
            status_parts.append('S&P')
        if radio['is_split']:
            status_parts.append('SPLIT')

        left_status = '   '.join(status_parts)
        left_surf = strip_status_font.render(left_status, True, s_color)
        surf.blit(left_surf, (inner_x, text_y))

        right_parts = []
        if radio.get('is_active'):
            right_parts.append('ACTIVE')
        if radio['is_transmitting']:
            right_parts.append('TX')
        if radio['is_connected']:
            right_parts.append('CONN')
        else:
            right_parts.append('DISC')

        right_status = '   '.join(right_parts)
        right_surf = strip_status_font.render(right_status, True, s_color)
        right_rect = right_surf.get_rect()
        right_rect.right = inner_right
        right_rect.y = text_y
        surf.blit(right_surf, right_rect)

        y_cursor += strip_height + 4

    result_size = surf.get_size()
    raw_data = pygame.image.tostring(surf, image_format)
    logging.debug('draw_radio_info() done')
    return raw_data, result_size


def _mult_sort_key(code):
    """Sort key for multiplier codes: numeric multipliers (ITU/CQ zones) sort
    numerically (so 9 comes before 89/90, not between them), while alphabetic
    multipliers (sections, states) keep their normal alphabetical order."""
    return (0, int(code)) if code.isdigit() else (1, code)


def draw_mults_progress(size, qsos_by_mult):
    """
    Draw a multiplier progress display with progress bar and percentage.
    Shows "67/85 sections worked (79%)" with visual progress bar.
    Returns (raw_data, size) or (None, (0,0)) if no data.
    """
    logging.debug('draw_mults_progress()')

    mult_dict = get_mult_dictionary()
    total_mults = len(mult_dict)

    if qsos_by_mult is None:
        qsos_by_mult = {}

    # Count worked mults
    worked_mults = sum(1 for mult in mult_dict.keys() if qsos_by_mult.get(mult, 0) > 0)

    if total_mults == 0:
        return None, (0, 0)

    percentage = (worked_mults / total_mults) * 100
    mult_type = get_mult_name()

    # Get actual font heights for proper spacing
    title_font = bigger_font
    title_height = title_font.get_height()
    main_font = view_font
    main_height = main_font.get_height()

    # Calculate text content first to determine width needed. Title is generic
    # ('Multiplier Progress') so it reads sensibly for any contest; the body
    # still names the specific multiplier (sections/states/zones).
    title = 'Multiplier Progress'
    main_text = f'{worked_mults}/{total_mults} {mult_type.lower()} worked ({percentage:.0f}%)'
    remaining = total_mults - worked_mults
    remaining_text = f'{remaining} remaining'

    title_width = title_font.size(title)[0]
    main_width = main_font.size(main_text)[0]
    remaining_width = main_font.size(remaining_text)[0]

    # Layout calculations
    padding = 30
    bar_height = 50
    bar_margin = 50
    min_bar_width = 400

    # Calculate surface width based on content
    content_width = max(title_width, main_width, remaining_width)
    surface_width = max(content_width + padding * 2, min_bar_width + bar_margin * 2)
    surface_width = min(surface_width, size[0])  # Don't exceed screen width

    # Calculate total height needed
    y_cursor = padding
    title_y = y_cursor
    y_cursor += title_height + padding
    main_y = y_cursor
    y_cursor += main_height + padding * 2
    bar_y = y_cursor
    y_cursor += bar_height + padding
    remaining_y = y_cursor
    y_cursor += main_height + padding

    surface_height = y_cursor
    surf = pygame.Surface((surface_width, surface_height))
    surf.fill(BLACK)

    # Title
    title_surf = title_font.render(title, True, WHITE)
    title_rect = title_surf.get_rect()
    title_rect.centerx = surface_width // 2
    title_rect.y = title_y
    surf.blit(title_surf, title_rect)

    # Main text: "2/51 states worked (4%)"
    main_surf = main_font.render(main_text, True, CYAN)
    main_rect = main_surf.get_rect()
    main_rect.centerx = surface_width // 2
    main_rect.y = main_y
    surf.blit(main_surf, main_rect)

    # Progress bar
    bar_width = surface_width - 2 * bar_margin

    # Background bar (empty)
    bar_bg_rect = pygame.Rect(bar_margin, bar_y, bar_width, bar_height)
    pygame.draw.rect(surf, GRAY, bar_bg_rect, 3)

    # Filled portion
    if worked_mults > 0:
        fill_width = int(bar_width * worked_mults / total_mults)
        if fill_width < 6:
            fill_width = 6  # Minimum visible width
        fill_rect = pygame.Rect(bar_margin + 3, bar_y + 3, fill_width - 6, bar_height - 6)
        # Color gradient based on progress
        if percentage >= 75:
            fill_color = GREEN
        elif percentage >= 50:
            fill_color = YELLOW
        elif percentage >= 25:
            fill_color = ORANGE
        else:
            fill_color = RED
        pygame.draw.rect(surf, fill_color, fill_rect)

    # Remaining count
    remaining_surf = main_font.render(remaining_text, True, GRAY)
    remaining_rect = remaining_surf.get_rect()
    remaining_rect.centerx = surface_width // 2
    remaining_rect.y = remaining_y
    surf.blit(remaining_surf, remaining_rect)

    result_size = surf.get_size()
    raw_data = pygame.image.tostring(surf, image_format)
    logging.debug('draw_mults_progress() done')
    return raw_data, result_size


def draw_mults_remaining(size, qsos_by_mult):
    """
    Draw a multi-column table of all multipliers.
    Worked mults shown dimmed, unworked mults shown bright.
    Title shows count remaining.
    Returns (raw_data, size) or (None, (0,0)) if no data.
    """
    logging.debug('draw_mults_remaining()')

    mult_dict = get_mult_dictionary()

    if qsos_by_mult is None:
        qsos_by_mult = {}

    # Get all mults sorted, track which are worked. Numeric multipliers (ITU/CQ
    # zones) sort numerically so 9 doesn't land between 89 and 90; alpha
    # multipliers (sections, states) keep their normal alphabetical order.
    all_mults = sorted(mult_dict.keys(), key=_mult_sort_key)
    worked_set = {code for code in all_mults if qsos_by_mult.get(code, 0) > 0}
    num_worked = len(worked_set)
    num_remaining = len(all_mults) - num_worked

    # Get actual font heights
    title_font = view_font
    title_height = title_font.get_height()
    cell_font = view_font
    cell_height = cell_font.get_height() + 8
    padding = 20

    mult_type = get_mult_name()

    if num_remaining == 0:
        # All mults worked - show congratulations
        title = f'All {mult_type} Worked!'
        title_surf = bigger_font.render(title, True, GREEN)

        surface_width = title_surf.get_width() + padding * 2
        surface_height = bigger_font.get_height() + padding * 2
        surf = pygame.Surface((surface_width, surface_height))
        surf.fill(BLACK)

        title_rect = title_surf.get_rect()
        title_rect.centerx = surface_width // 2
        title_rect.centery = surface_height // 2
        surf.blit(title_surf, title_rect)

        result_size = surf.get_size()
        raw_data = pygame.image.tostring(surf, image_format)
        return raw_data, result_size

    # Calculate layout - show ALL mults
    title = f'{num_remaining} {mult_type} Remaining'

    # Calculate cell width based on widest code + padding
    max_code_width = max(cell_font.size(code)[0] for code in all_mults)
    cell_width = max_code_width + 30  # Add padding between codes

    # Determine columns based on total count
    num_mults = len(all_mults)
    if num_mults <= 10:
        num_cols = 2
    elif num_mults <= 20:
        num_cols = 3
    elif num_mults <= 40:
        num_cols = 4
    elif num_mults <= 60:
        num_cols = 5
    else:
        num_cols = 6

    num_rows = (num_mults + num_cols - 1) // num_cols

    # Calculate sizes
    table_width = num_cols * cell_width
    table_height = num_rows * cell_height

    title_width = title_font.size(title)[0]
    surface_width = max(table_width + padding * 2, title_width + padding * 2)

    # Calculate positions dynamically
    title_y = padding
    grid_y = title_y + title_height + padding
    surface_height = grid_y + table_height + padding

    surf = pygame.Surface((surface_width, surface_height))
    surf.fill(BLACK)

    # Draw title
    title_surf = title_font.render(title, True, YELLOW)
    title_rect = title_surf.get_rect()
    title_rect.centerx = surface_width // 2
    title_rect.y = title_y
    surf.blit(title_surf, title_rect)

    # Draw grid of ALL mults - bright for unworked, dim for worked
    start_x = (surface_width - table_width) // 2

    for i, code in enumerate(all_mults):
        col = i % num_cols
        row = i // num_cols
        x = start_x + col * cell_width
        y = grid_y + row * cell_height

        # Unworked = bright white, Worked = dim gray
        color = DARK_GRAY if code in worked_set else WHITE
        code_surf = cell_font.render(code, True, color)
        code_rect = code_surf.get_rect()
        code_rect.centerx = x + cell_width // 2
        code_rect.y = y
        surf.blit(code_surf, code_rect)

    result_size = surf.get_size()
    raw_data = pygame.image.tostring(surf, image_format)
    logging.debug('draw_mults_remaining() done')
    return raw_data, result_size


def draw_hq_stations(size, qsos_by_hq):
    """
    Draw the IARU HQ-station multiplier chart: a worked/total header with a
    progress bar, over a grid of the full HQ-society roster with worked
    abbreviations highlighted (bright green) and unworked ones dimmed.

    HQ stations are a secondary IARU multiplier that coexists with the ITU-zone
    map, so this is its own slide rather than part of the zone charts. Unlike
    the zone "remaining" chart there is no realistic goal of working every
    society, so worked ones are highlighted (celebrating what's in the log)
    rather than dimmed.

    Returns (raw_data, size) or (None, (0,0)) if there is no HQ roster.
    """
    logging.debug('draw_hq_stations()')

    all_hq = sorted(IARU_HQ)
    total_hq = len(all_hq)
    if total_hq == 0:
        return None, (0, 0)

    if qsos_by_hq is None:
        qsos_by_hq = {}

    worked_set = {abbr for abbr in all_hq if qsos_by_hq.get(abbr, 0) > 0}
    num_worked = len(worked_set)
    percentage = (num_worked / total_hq) * 100

    padding = 20

    title_font = bigger_font
    title = 'HQ Stations Worked'
    title_height = title_font.get_height()

    sub_font = view_font
    sub_text = f'{num_worked}/{total_hq} HQ worked ({percentage:.0f}%)'
    sub_height = sub_font.get_height()

    cell_font = view_font
    cell_height = cell_font.get_height() + 8

    # HQ abbreviations are short, so pack more columns than the zone grid to keep
    # the ~180-entry roster from getting excessively tall.
    max_code_width = max(cell_font.size(code)[0] for code in all_hq)
    cell_width = max_code_width + 30
    num_cols = 8
    num_rows = (total_hq + num_cols - 1) // num_cols

    table_width = num_cols * cell_width
    table_height = num_rows * cell_height

    bar_height = 40
    min_bar_width = 400

    title_width = title_font.size(title)[0]
    sub_width = sub_font.size(sub_text)[0]
    content_width = max(title_width, sub_width, table_width, min_bar_width)
    surface_width = content_width + padding * 2

    # Vertical layout: title, subtitle, progress bar, then the roster grid.
    y_cursor = padding
    title_y = y_cursor
    y_cursor += title_height + padding
    sub_y = y_cursor
    y_cursor += sub_height + padding
    bar_y = y_cursor
    y_cursor += bar_height + padding
    grid_y = y_cursor
    y_cursor += table_height + padding
    surface_height = y_cursor

    surf = pygame.Surface((surface_width, surface_height))
    surf.fill(BLACK)

    # Title
    title_surf = title_font.render(title, True, WHITE)
    title_rect = title_surf.get_rect()
    title_rect.centerx = surface_width // 2
    title_rect.y = title_y
    surf.blit(title_surf, title_rect)

    # Subtitle count
    sub_surf = sub_font.render(sub_text, True, CYAN)
    sub_rect = sub_surf.get_rect()
    sub_rect.centerx = surface_width // 2
    sub_rect.y = sub_y
    surf.blit(sub_surf, sub_rect)

    # Progress bar (green fill; the bar is a rough "how much of the roster" gauge)
    bar_margin = 50
    bar_width = surface_width - 2 * bar_margin
    bar_bg_rect = pygame.Rect(bar_margin, bar_y, bar_width, bar_height)
    pygame.draw.rect(surf, GRAY, bar_bg_rect, 3)
    if num_worked > 0:
        fill_width = int(bar_width * num_worked / total_hq)
        if fill_width < 6:
            fill_width = 6
        fill_rect = pygame.Rect(bar_margin + 3, bar_y + 3, fill_width - 6, bar_height - 6)
        pygame.draw.rect(surf, GREEN, fill_rect)

    # Roster grid: worked = bright green, unworked = dim gray.
    start_x = (surface_width - table_width) // 2
    for i, code in enumerate(all_hq):
        col = i % num_cols
        row = i // num_cols
        x = start_x + col * cell_width
        y = grid_y + row * cell_height
        color = GREEN if code in worked_set else DARK_GRAY
        code_surf = cell_font.render(code, True, color)
        code_rect = code_surf.get_rect()
        code_rect.centerx = x + cell_width // 2
        code_rect.y = y
        surf.blit(code_surf, code_rect)

    result_size = surf.get_size()
    raw_data = pygame.image.tostring(surf, image_format)
    logging.debug('draw_hq_stations() done')
    return raw_data, result_size


def draw_wrtc_stations(size, qsos_by_wrtc, all_calls):
    """
    Draw the WRTC-station roster chart: a worked/total header with a progress
    bar over a grid of the WRTC special callsigns, worked ones highlighted
    (bright green) and unworked ones dimmed.

    WRTC (World Radiosport Team Championship) is IARU HF's every-four-years
    "contest within the contest": ~50 teams issued special callsigns just before
    the start. Unlike the open-ended HQ roster, working all of them is a real
    goal, so the progress bar is a genuine gauge. The roster (all_calls) is read
    from a file at render time; only callsigns are shown -- never team
    identities -- in line with WRTC's anti-cheerleading policy.

    Returns (raw_data, size) or (None, (0,0)) if the roster is empty (e.g.
    before the callsigns have been issued).
    """
    logging.debug('draw_wrtc_stations()')

    all_calls = sorted(all_calls or [])
    total = len(all_calls)
    if total == 0:
        return None, (0, 0)

    if qsos_by_wrtc is None:
        qsos_by_wrtc = {}

    worked_set = {call for call in all_calls if qsos_by_wrtc.get(call, 0) > 0}
    num_worked = len(worked_set)
    percentage = (num_worked / total) * 100

    padding = 20

    title_font = bigger_font
    title = 'WRTC Stations Worked'
    title_height = title_font.get_height()

    sub_font = view_font
    sub_text = f'{num_worked}/{total} WRTC worked ({percentage:.0f}%)'
    sub_height = sub_font.get_height()

    cell_font = view_font
    cell_height = cell_font.get_height() + 8

    # Callsigns are wider than the short HQ abbreviations, so pack fewer columns.
    max_code_width = max(cell_font.size(code)[0] for code in all_calls)
    cell_width = max_code_width + 30
    num_cols = 6
    num_rows = (total + num_cols - 1) // num_cols

    table_width = num_cols * cell_width
    table_height = num_rows * cell_height

    bar_height = 40
    min_bar_width = 400

    title_width = title_font.size(title)[0]
    sub_width = sub_font.size(sub_text)[0]
    content_width = max(title_width, sub_width, table_width, min_bar_width)
    surface_width = content_width + padding * 2

    # Vertical layout: title, subtitle, progress bar, then the roster grid.
    y_cursor = padding
    title_y = y_cursor
    y_cursor += title_height + padding
    sub_y = y_cursor
    y_cursor += sub_height + padding
    bar_y = y_cursor
    y_cursor += bar_height + padding
    grid_y = y_cursor
    y_cursor += table_height + padding
    surface_height = y_cursor

    surf = pygame.Surface((surface_width, surface_height))
    surf.fill(BLACK)

    # Title
    title_surf = title_font.render(title, True, WHITE)
    title_rect = title_surf.get_rect()
    title_rect.centerx = surface_width // 2
    title_rect.y = title_y
    surf.blit(title_surf, title_rect)

    # Subtitle count
    sub_surf = sub_font.render(sub_text, True, CYAN)
    sub_rect = sub_surf.get_rect()
    sub_rect.centerx = surface_width // 2
    sub_rect.y = sub_y
    surf.blit(sub_surf, sub_rect)

    # Progress bar (green fill; here it is a true "how many of the 50 teams" gauge)
    bar_margin = 50
    bar_width = surface_width - 2 * bar_margin
    bar_bg_rect = pygame.Rect(bar_margin, bar_y, bar_width, bar_height)
    pygame.draw.rect(surf, GRAY, bar_bg_rect, 3)
    if num_worked > 0:
        fill_width = int(bar_width * num_worked / total)
        if fill_width < 6:
            fill_width = 6
        fill_rect = pygame.Rect(bar_margin + 3, bar_y + 3, fill_width - 6, bar_height - 6)
        pygame.draw.rect(surf, GREEN, fill_rect)

    # Roster grid: worked = bright green, unworked = dim gray.
    start_x = (surface_width - table_width) // 2
    for i, code in enumerate(all_calls):
        col = i % num_cols
        row = i // num_cols
        x = start_x + col * cell_width
        y = grid_y + row * cell_height
        color = GREEN if code in worked_set else DARK_GRAY
        code_surf = cell_font.render(code, True, color)
        code_rect = code_surf.get_rect()
        code_rect.centerx = x + cell_width // 2
        code_rect.y = y
        surf.blit(code_surf, code_rect)

    result_size = surf.get_size()
    raw_data = pygame.image.tostring(surf, image_format)
    logging.debug('draw_wrtc_stations() done')
    return raw_data, result_size


def draw_operator_leaderboard(size, qso_operators):
    """
    Draw a ranked operator leaderboard table.
    Shows position (1st, 2nd, 3rd...), operator name, QSO count, percentage.
    Returns (raw_data, size) or (None, (0,0)) if no data.
    """
    logging.debug('draw_operator_leaderboard()')

    if qso_operators is None or len(qso_operators) == 0:
        return None, (0, 0)

    # Calculate total QSOs
    total_qsos = sum(op[1] for op in qso_operators)
    if total_qsos == 0:
        return None, (0, 0)

    # Build table data
    ordinals = ['1st', '2nd', '3rd', '4th', '5th', '6th', '7th', '8th', '9th', '10th',
                '11th', '12th', '13th', '14th', '15th', '16th', '17th', '18th', '19th', '20th']

    data_rows = []
    for i, (name, count) in enumerate(qso_operators):
        rank = ordinals[i] if i < len(ordinals) else f'{i+1}th'
        pct = (count / total_qsos) * 100
        data_rows.append([rank, name, f'{count}', f'{pct:.1f}%'])

    header, rows, label_cols = maybe_two_up(['Rank', 'Operator', 'QSOs', '%'],
                                            data_rows, {1})
    cells = [header] + rows
    title = 'Operator Leaderboard'

    logging.debug('draw_operator_leaderboard() done')
    return draw_table(size, cells, title, label_cols=label_cols)


def draw_new_ops_race(size, current_first_qsos, prior_op_names, prior_curve,
                      prior_new_curve=None, prior_event_label='Last Year'):
    """
    Race-curve chart of cumulative distinct operators over event-elapsed time.

    Series:
      - Prior event ALL (reference): from prior_curve, (elapsed_secs, count) pairs.
      - Prior event NEW (reference): from prior_new_curve -- the operators who
        were new in the prior event's year, so the current NEW line has a true
        new-vs-new benchmark to race.
      - Current event TOTAL: cumulative distinct operators in current_first_qsos.
      - Current event NEW:   subset whose name is not in prior_op_names.

    `current_first_qsos` is the list returned by
    dataaccess.get_operator_first_qsos (sorted ascending by first_ts).
    Returns (raw_data, size) or (None, (0,0)).
    """
    if not current_first_qsos and not prior_curve:
        return None, (0, 0)

    # Anchor the current-event timeline to EVENT_START_TIME (UTC). Negative
    # offsets are clipped to 0 (anyone who logged before official start).
    event_start = calendar.timegm(config.EVENT_START_TIME.timetuple())

    cur_total_pts = []  # (hours_elapsed, cumulative_count)
    cur_new_pts = []
    total = 0
    new_total = 0
    prior_set = prior_op_names or set()
    for r in current_first_qsos:
        offset_h = max(0.0, (r['first_ts'] - event_start) / 3600.0)
        total += 1
        cur_total_pts.append((offset_h, total))
        if r['name'].strip().lower() not in prior_set:
            new_total += 1
        cur_new_pts.append((offset_h, new_total))

    prior_pts = [(secs / 3600.0, n) for secs, n in (prior_curve or [])]
    prior_new_pts = [(secs / 3600.0, n) for secs, n in (prior_new_curve or [])]

    # Plot
    width_inches = size[0] / 100.0
    height_inches = size[1] / 100.0
    fig = plt.Figure(figsize=(width_inches, height_inches), dpi=100,
                     tight_layout={'pad': 0.3}, facecolor='black')
    if matplotlib.__version__[0] == '1':
        ax = fig.add_subplot(111, axis_bgcolor='black')
    else:
        ax = fig.add_subplot(111, facecolor='black')
    ax.set_title('Operators On The Air — Race vs. %s' % prior_event_label,
                 color='white', size=42, weight='bold')

    def _step(points):
        if not points:
            return [], []
        xs = [0.0]
        ys = [0]
        for x, y in points:
            xs.append(x); ys.append(ys[-1])  # horizontal to next event time
            xs.append(x); ys.append(y)       # vertical step up
        return xs, ys

    drawn = False
    if prior_pts:
        xs, ys = _step(prior_pts)
        ax.plot(xs, ys, color='#888888', linewidth=3,
                label='%s — All Ops' % prior_event_label, linestyle='--')
        drawn = True
    if prior_new_pts:
        xs, ys = _step(prior_new_pts)
        ax.plot(xs, ys, color='#c9a227', linewidth=3,
                label='%s — NEW Ops' % prior_event_label, linestyle='--')
        drawn = True
    if cur_total_pts:
        xs, ys = _step(cur_total_pts)
        ax.plot(xs, ys, color='#5fff9c', linewidth=4, label='This Year — All Ops')
        drawn = True
    if cur_new_pts:
        xs, ys = _step(cur_new_pts)
        ax.plot(xs, ys, color='#ffd24a', linewidth=4, label='This Year — NEW Ops')
        drawn = True

    if not drawn:
        plt.close(fig)
        return None, (0, 0)

    # X-axis spans event duration if known, otherwise data extent.
    try:
        event_end = calendar.timegm(config.EVENT_END_TIME.timetuple())
        event_hours = max(1.0, (event_end - event_start) / 3600.0)
    except Exception:
        event_hours = 24.0
    data_hours = max(
        cur_total_pts[-1][0] if cur_total_pts else 0,
        cur_new_pts[-1][0] if cur_new_pts else 0,
        prior_pts[-1][0] if prior_pts else 0,
        prior_new_pts[-1][0] if prior_new_pts else 0,
    )
    ax.set_xlim(0, max(event_hours, data_hours))

    # Y-axis: 0 to max series, with a bit of headroom.
    y_max = max(
        cur_total_pts[-1][1] if cur_total_pts else 0,
        cur_new_pts[-1][1] if cur_new_pts else 0,
        prior_pts[-1][1] if prior_pts else 0,
        prior_new_pts[-1][1] if prior_new_pts else 0,
    )
    ax.set_ylim(0, max(5, y_max + 2))

    # Annotate the latest current-year value at the right edge of the curve.
    if cur_total_pts:
        x, y = cur_total_pts[-1]
        ax.annotate('%d total' % y, xy=(x, y), xytext=(6, 4),
                    textcoords='offset points', color='#5fff9c',
                    size=22, weight='bold')
    if cur_new_pts:
        x, y = cur_new_pts[-1]
        ax.annotate('%d new' % y, xy=(x, y), xytext=(6, -22),
                    textcoords='offset points', color='#ffd24a',
                    size=22, weight='bold')

    ax.grid(True, color='#333333')
    ax.set_xlabel('Hours since event start', color='w', size='x-large', weight='bold')
    ax.set_ylabel('Cumulative operators', color='w', size='x-large', weight='bold')
    legend = ax.legend(loc='upper left', facecolor='black', edgecolor='white',
                       labelcolor='white', fontsize='x-large')
    for spine in ('left', 'right', 'top', 'bottom'):
        ax.spines[spine].set_color('w')
    ax.tick_params(axis='both', colors='w', labelsize=14)

    canvas = agg.FigureCanvasAgg(fig)
    canvas.draw()
    renderer = canvas.get_renderer()

    # Shrink the title if it overflows the figure width. The title size is fixed
    # at 42, but a long prior-event label (e.g. "2025 ARRL FD") can push it past
    # both edges, so measure the rendered width and scale down to fit if needed.
    fig_px = fig.get_figwidth() * fig.get_dpi()
    title_bb = ax.title.get_window_extent(renderer)
    if title_bb.width > fig_px * 0.98:
        ax.title.set_fontsize(ax.title.get_fontsize() * fig_px * 0.98 / title_bb.width)
        canvas.draw()
        renderer = canvas.get_renderer()

    raw_data = renderer.tostring_argb() if image_format == 'ARGB' else renderer.tostring_rgb()
    plt.close(fig)
    return raw_data, canvas.get_width_height()


def draw_new_ops_yoy(size, yoy_rows, current_year=None, current_new_count=None,
                     current_total_count=None):
    """
    Vertical bar chart of "new operators" per event, year-over-year.
    yoy_rows = [(label, year, total_ops, new_ops), ...] (already sorted).
    Year-1 (the earliest year) is treated as the baseline and shown in gray.
    If current_year/current_new_count are provided AND current_year is later
    than every yoy row, an additional bar is appended in the accent color.
    Sized for the sidebar — height should be ~size[1] for the slide variant
    and smaller for the sidebar PNG.
    """
    bars = []  # list of (label, year, count, is_current, is_baseline)
    earliest_year = yoy_rows[0][1] if yoy_rows else None
    for label, year, _total, new_ops in yoy_rows:
        is_baseline = (year == earliest_year)
        bars.append((label, year, new_ops, False, is_baseline))
    if (current_year is not None and current_new_count is not None and
            (not yoy_rows or current_year > yoy_rows[-1][1])):
        bars.append(('%s (live)' % current_year, current_year,
                     current_new_count, True, False))

    if not bars:
        return None, (0, 0)

    width_inches = size[0] / 100.0
    height_inches = size[1] / 100.0
    fig = plt.Figure(figsize=(width_inches, height_inches), dpi=100,
                     tight_layout={'pad': 0.4}, facecolor='black')
    if matplotlib.__version__[0] == '1':
        ax = fig.add_subplot(111, axis_bgcolor='black')
    else:
        ax = fig.add_subplot(111, facecolor='black')

    title = 'New Operators Per Year'
    ax.set_title(title, color='white', size=22 if size[0] < 800 else 32,
                 weight='bold')

    xs = list(range(len(bars)))
    heights = [b[2] for b in bars]
    colors = []
    for _, _, _, is_current, is_baseline in bars:
        if is_current:
            colors.append('#5fff9c')   # green for live current
        elif is_baseline:
            colors.append('#888888')   # gray for the earliest "everyone is new" bar
        else:
            colors.append('#ffd24a')   # yellow for true new-per-year

    bar_rects = ax.bar(xs, heights, color=colors, edgecolor='white', linewidth=0.5)
    ax.set_xticks(xs)
    label_size = 12 if size[0] < 800 else 16
    ax.set_xticklabels(
        [('%d*' % b[1]) if b[3] else str(b[1]) for b in bars],
        color='w', rotation=0, size=label_size)
    ax.tick_params(axis='y', colors='w', labelsize=label_size)
    ax.set_ylabel('Operators', color='w', size=label_size, weight='bold')
    for spine in ('left', 'right', 'top', 'bottom'):
        ax.spines[spine].set_color('w')
    ax.grid(True, axis='y', color='#333333')
    ax.set_axisbelow(True)

    y_max = max(heights) if heights else 1
    ax.set_ylim(0, y_max + max(2, y_max * 0.15))

    # Annotate each bar with its count.
    for rect, h in zip(bar_rects, heights):
        ax.text(rect.get_x() + rect.get_width() / 2.0, h,
                str(h), ha='center', va='bottom', color='white',
                size=label_size, weight='bold')

    canvas = agg.FigureCanvasAgg(fig)
    canvas.draw()
    renderer = canvas.get_renderer()
    raw_data = renderer.tostring_argb() if image_format == 'ARGB' else renderer.tostring_rgb()
    plt.close(fig)
    return raw_data, canvas.get_width_height()


def draw_new_ops_roster(size, current_first_qsos, prior_op_names,
                        event_label='This Event'):
    """
    Table listing this event's new operators (name not in prior_op_names),
    each with their first-QSO time, band, mode, and callsign worked.
    """
    if not current_first_qsos:
        return None, (0, 0)
    prior_set = prior_op_names or set()
    new_rows = [r for r in current_first_qsos
                if r['name'].strip().lower() not in prior_set]
    if not new_rows:
        # Render a "no new ops yet" placeholder so the slide doesn't vanish.
        cells = [['Callsign', 'First QSO (UTC)', 'Band', 'Mode', 'Worked'],
                 ['(none yet)', '—', '—', '—', '—']]
        return draw_table(size, cells, 'New Operators — %s' % event_label)

    cells = [['Callsign', 'First QSO (UTC)', 'Band', 'Mode', 'Worked']]
    for r in new_rows:
        ts = datetime.datetime.utcfromtimestamp(r['first_ts']).strftime('%H:%M:%S')
        band = Bands.BANDS_TITLE[r['band_id']] if 0 <= r['band_id'] < Bands.count() else '?'
        mode_simple = Modes.SIMPLE_MODES_LIST[Modes.MODE_TO_SIMPLE_MODE[r['mode_id']]] \
            if 0 <= r['mode_id'] < len(Modes.MODE_TO_SIMPLE_MODE) else '?'
        cells.append([r['name'], ts, band, mode_simple, r.get('worked') or ''])
    return draw_table(size, cells, 'New Operators — %s' % event_label)


# Map extent [lon_min, lon_max, lat_min, lat_max] and coastline resolution per
# multiplier mode. Section/State contests are North-America regional; the IARU
# HF Championship is worked worldwide against ITU zones, so it needs the whole
# globe (and a coarser coastline, which is plenty at world scale and faster).
# Zone-multiplier map views share one world extent. '50m' coastline is used
# (not '110m') because it is already cached offline from the section map; the FD
# site has no internet to fetch datasets.
_WORLD_VIEW = {'extent': [-180, 180, -85, 85], 'coastline': '50m',
               'extent_crs': ccrs.PlateCarree()}
MAP_VIEWS = {
    'ITUZONES': _WORLD_VIEW,
    'CQZONES':  _WORLD_VIEW,
    # GRID starts from the world view but draw_map auto-fits the extent to the
    # worked grids (grid contests are usually regional).
    'GRID':     _WORLD_VIEW,
    'DEFAULT':  {'extent': [-168, -52, 10, 60], 'coastline': '50m',
                 'extent_crs': ccrs.Geodetic()},
}


def grid_to_bbox(grid):
    """Convert a Maidenhead locator to its cell box (lon_min, lat_min, lon_max,
    lat_max), or None if invalid. Precision is taken from the locator length:
    2 chars = field (20x10 deg), 4 = square (2x1 deg), 6 = subsquare (5'x2.5').
    """
    if not grid:
        return None
    g = grid.strip().upper()
    if len(g) not in (2, 4, 6):
        return None
    if not ('A' <= g[0] <= 'R' and 'A' <= g[1] <= 'R'):
        return None
    lon = -180.0 + (ord(g[0]) - ord('A')) * 20.0
    lat = -90.0 + (ord(g[1]) - ord('A')) * 10.0
    lon_size, lat_size = 20.0, 10.0
    if len(g) >= 4:
        if not (g[2].isdigit() and g[3].isdigit()):
            return None
        lon += int(g[2]) * 2.0
        lat += int(g[3]) * 1.0
        lon_size, lat_size = 2.0, 1.0
    if len(g) >= 6:
        if not ('A' <= g[4] <= 'X' and 'A' <= g[5] <= 'X'):
            return None
        lon += (ord(g[4]) - ord('A')) * (2.0 / 24.0)
        lat += (ord(g[5]) - ord('A')) * (1.0 / 24.0)
        lon_size, lat_size = 2.0 / 24.0, 1.0 / 24.0
    return (lon, lat, lon + lon_size, lat + lat_size)

# Per-mode zone fill-polygon geojson, built by utils/extract_zones.py from the
# Leaflet.ITUzones / Leaflet.CQzones boundary data.
ZONE_GEOJSON = {
    'ITUZONES': 'shapes/itu_zones.geojson',
    'CQZONES':  'shapes/cq_zones.geojson',
}

_zone_geometry_cache = {}


def _load_zone_geometries(path):
    """Load and cache the zone fill polygons from a zones geojson.

    Returns {zone_number_str: shapely geometry}. Returns {} (with a warning) if
    the file is missing so the map still renders.
    """
    if path in _zone_geometry_cache:
        return _zone_geometry_cache[path]
    from shapely.geometry import shape
    geometries = {}
    if not os.path.exists(path):
        logging.warning('zone geometry not found: %s (run utils/extract_zones.py)' % path)
    else:
        with open(path) as fh:
            fc = json.load(fh)
        for feature in fc.get('features', []):
            zone = str(feature.get('properties', {}).get('zone', '')).strip()
            if zone:
                geometries[zone] = shape(feature['geometry'])
    _zone_geometry_cache[path] = geometries
    return geometries


def draw_map(size, qsos_by_section):
    """
    make the choropleth with Cartopy: ARRL section/US-state shapefiles for
    regional contests, ITU/CQ zone polygons on a world map for the zone modes,
    or computed Maidenhead grid cells (auto-fit extent) when MULTS=GRID
    """
    logging.debug('draw_section map()')
    width_inches = size[0] / 100.0
    height_inches = size[1] / 100.0
    fig = plt.Figure(figsize=(width_inches, height_inches), dpi=100, facecolor='black')

    view = MAP_VIEWS.get(config.MULTS, MAP_VIEWS['DEFAULT'])
    zone_geometries = _load_zone_geometries(ZONE_GEOJSON[config.MULTS]) \
        if config.MULTS in ZONE_GEOJSON else None

    projection = ccrs.PlateCarree()
    ax = fig.add_axes([0, 0, 1, 1], projection=projection)
    ax.set_extent(view['extent'], view['extent_crs'])
    # Pin physical fills to 110m: these features default to scale='auto', which
    # switches to 50m/10m when the extent is zoomed in (e.g. a regional GRID
    # auto-fit) and tries to DOWNLOAD those datasets -- fatal at the offline FD
    # site. Only the 110m physical set and 50m coastline are cached locally.
    ax.add_feature(cfeature.OCEAN.with_scale('110m'), color=MAP_OCEAN_COLOR)
    ax.add_feature(cfeature.LAKES.with_scale('110m'), color=MAP_LAKE_COLOR)
    ax.add_feature(cfeature.LAND.with_scale('110m'), color=MAP_LAND_COLOR)

    ax.coastlines(view['coastline'])
    ax.annotate(get_mult_title(), xy=(0.5, 1), xycoords='axes fraction', ha='center', va='top',
                color='white', size=48, weight='bold')
    
    ax.text(0.83, 0, datetime.datetime.utcnow().strftime("%d %b %Y %H:%M %Zz"),
            transform=ax.transAxes, style='italic', size=14, color='white')
    ranges = [0, 1, 2, 10, 20, 50, 100]  # , 500]  # , 1000]
    num_colors = len(ranges)
    # color_palette = matplotlib.cm.viridis(np.linspace(0.33, 1, num_colors + 1))
    delta = 1 / (num_colors + 1)
    colors = [delta * i for i in range(num_colors+1)]
    color_palette = matplotlib.cm.viridis(colors)

    def color_index_for(qsos):
        idx = 0
        for range_max in ranges:
            if range_max == -1 or qsos <= range_max:
                break
            idx += 1
            if idx == num_colors:
                break
        return idx

    if config.MULTS == 'GRID':
        # Maidenhead grids: no fixed geometry file -- compute each worked grid's
        # cell box from its identifier and fill it. Only worked grids exist in
        # qsos_by_section, so every cell is coloured (no black placeholders), and
        # the map auto-fits to the worked area (grid contests are regional).
        from shapely.geometry import box as shp_box
        bounds = None  # [lon_min, lat_min, lon_max, lat_max] across worked grids
        for grid_name, qsos in qsos_by_section.items():
            bbox = grid_to_bbox(grid_name)
            if bbox is None:
                logging.warning('unparseable grid %r, skipping', grid_name)
                continue
            ci = color_index_for(qsos) or 1  # worked -> at least the first colour
            ax.add_geometries([shp_box(*bbox)], projection, linewidth=0.5,
                              edgecolor='w', facecolor=color_palette[ci])
            if bounds is None:
                bounds = list(bbox)
            else:
                bounds = [min(bounds[0], bbox[0]), min(bounds[1], bbox[1]),
                          max(bounds[2], bbox[2]), max(bounds[3], bbox[3])]
        if bounds is not None:
            pad_lon = max(5.0, (bounds[2] - bounds[0]) * 0.15)
            pad_lat = max(5.0, (bounds[3] - bounds[1]) * 0.15)
            ax.set_extent([max(-180, bounds[0] - pad_lon), min(180, bounds[2] + pad_lon),
                           max(-90, bounds[1] - pad_lat), min(90, bounds[3] + pad_lat)],
                          ccrs.PlateCarree())

    mult_dict = get_mult_dictionary()
    for section_name in mult_dict.keys():
        qsos = qsos_by_section.get(section_name)
        if qsos is None:
            qsos = 0

        color_index = 0
        for range_max in ranges:
            if range_max == -1 or qsos <= range_max:
                break
            color_index += 1
            if color_index == num_colors:
                break

        section_color = 'k' if color_index == 0 else color_palette[color_index]

        if zone_geometries is not None:
            # ITU zones: fill polygons come from the shared GeoJSON, one
            # (Multi)Polygon per zone number, rather than a file per key.
            geometry = zone_geometries.get(section_name)
            if geometry is None:
                logging.warning('ITU zone geometry missing: %s, skipping' % section_name)
                continue
            # Zones tile the whole globe, so filling unworked zones solid black
            # would hide every continent. Leave them transparent instead, so the
            # base map shows through and only worked zones are coloured.
            zone_face = 'none' if color_index == 0 else section_color
            ax.add_geometries([geometry], projection, linewidth=0.7, edgecolor="w", facecolor=zone_face)
            continue

        shape_file_name = 'shapes/{}.shp'.format(section_name)
        if not os.path.exists(shape_file_name):
            logging.warning('Shapefile not found: %s, skipping' % shape_file_name)
            continue
        reader = shapereader.Reader(shape_file_name)
        shapes = reader.records()
        while True:
            shape = next(shapes, None)
            if shape is None:
                break
            shape.attributes['name'] = section_name
            ax.add_geometries([shape.geometry], projection, linewidth=0.7, edgecolor="w", facecolor=section_color)

    # show terminator (day/night shading). Opacity is configurable so the night
    # side can be lightened -- alpha=0.5 washed the map out very dark.
    date = datetime.datetime.utcnow()  # this might have some timezone problems?
    if config.MAP_TERMINATOR_ALPHA > 0:
        ax.add_feature(nightshade.Nightshade(date, alpha=config.MAP_TERMINATOR_ALPHA))

    # show QTH marker
    ax.plot(config.QTH_LONGITUDE, config.QTH_LATITUDE, '.', color='r')

    canvas = agg.FigureCanvasAgg(fig)
    canvas.draw()
    renderer = canvas.get_renderer()
    if image_format == 'ARGB':
        raw_data = renderer.tostring_argb()
    else:
        raw_data = renderer.tostring_rgb()

    fig.clf()
    plt.close(fig)
    canvas_size = canvas.get_width_height()
    logging.debug('draw_map() done')
    return raw_data, canvas_size
