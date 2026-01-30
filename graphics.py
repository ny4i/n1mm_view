# holds code that returns graphs.
#
#
import calendar
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
from matplotlib.dates import HourLocator, DateFormatter

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

# Map colors (used with matplotlib, not pygame)
MAP_OCEAN_COLOR = '#000080'
MAP_LAKE_COLOR = '#000080'
MAP_LAND_COLOR = '#113311'

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


def make_pie(size, values, labels, title):
    """
    make a pie chart using matplotlib.
    return the chart as a pygame surface
    make the pie chart a square that is as tall as the display.
    """
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

    handles, labels = ax.get_legend_handles_labels()
    # legend = ax.legend(handles[0:5], labels[0:5], title='Top %s' % title, loc='upper right', prop={'size': 14})
    legend = ax.legend(handles[0:5], labels[0:5], loc='upper right', prop={'size': 14})  # best
    frame = legend.get_frame()
    frame.set_color((0, 0, 0, 0.75))
    frame.set_edgecolor('w')
    legend.get_title().set_color('w')
    for text in legend.get_texts():
        plt.setp(text, color='w')

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
    create the QSOs by Operators pie chart
    """
    # calculate QSO by class
    if qso_classes is None or len(qso_classes) == 0:
        return None, (0, 0)
    qso_classes = sorted(qso_classes, key=lambda x: x[0])

    total = 0
    for qso_class in qso_classes:
        total += qso_class[0]

    summarize = 0
    threshold = 2.0
    for qso_class in qso_classes:
        pct = qso_class[0] / total * 100.0
        if pct < threshold:
            summarize = qso_class[0]
        else:
            break

    grouped_qso_classes = []
    summarized_names = []
    summarized_values = 0

    for d in qso_classes:
        if d[0] <= summarize:
            summarized_names.append(d[1])
            summarized_values += d[0]
        else:
            grouped_qso_classes.append(d)
    grouped_qso_classes = sorted(grouped_qso_classes, key=lambda x: x[0], reverse=True)
    grouped_qso_classes.append((summarized_values, f'{len(summarized_names)} others'))

    labels = []
    values = []
    for d in grouped_qso_classes:
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

    count = 0
    cells = [['Operator', 'QSOs']]
    for d in qso_operators:
        cells.append(['%s' % d[0], '%5d' % d[1]])
        count += 1

    if count == 0:
        return None, (0, 0)
    else:
        return draw_table(size, cells, "QSOs by All Operators", bigger_font)


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
    cell_data = [[0 for m in Modes.SIMPLE_MODES_LIST] for b in Bands.BANDS_TITLE]

    for band_num in range(1, Bands.count()):
        for mode_num in range(1, len(Modes.SIMPLE_MODES_LIST)):
            cell_data[band_num][mode_num] = qso_band_modes[band_num][mode_num]
            cell_data[band_num][0] += qso_band_modes[band_num][mode_num]
            cell_data[0][mode_num] += qso_band_modes[band_num][mode_num]

    total = 0
    for c in cell_data[0][1:]:
        total += c
    cell_data[0][0] = total

    # the totals are in the 0th row and 0th column, move them to last.
    cell_text = [['', '   CW', 'Phone', ' Data', 'Total']]
    band_num = 0
    for row in cell_data[1:]:
        band_num += 1
        row_text = ['%5s' % Bands.BANDS_TITLE[band_num]]

        for col in row[1:]:
            row_text.append('%5d' % col)
        row_text.append('%5d' % row[0])
        cell_text.append(row_text)

    row = cell_data[0]
    row_text = ['Total']
    for col in row[1:]:
        row_text.append('%5d' % col)
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
        ax.grid(True)
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
        hour_locator = HourLocator()
        hour_formatter = DateFormatter('%H')
        ax.xaxis.set_major_locator(hour_locator)
        ax.xaxis.set_major_formatter(hour_formatter)
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


def draw_table(size, cell_text, title, font=None):
    """
    draw a table
    """
    logging.debug('draw_table(...,%s)', title)
    if font is None:
        table_font = view_font
    else:
        table_font = font

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
            if row_number == 1 or column_number == 1:
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

    logging.debug('draw_radio_info()')

    now = int(_time.time())
    stale_threshold = 60  # seconds - clear frequency data after this

    surface_width = size[0]
    surface_height = size[1]
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
    strip_margin = 10
    strip_padding = 6
    line1_h = strip_label_font.get_height()
    line2_h = strip_freq_font.get_height()
    line3_h = strip_status_font.get_height()
    strip_height = line1_h + line2_h + line3_h + strip_padding * 4
    strip_width = surface_width - 2 * strip_margin
    border_width = 3

    # Group radios by station name
    current_station = None
    for radio in radios:
        station = radio['station_name']
        is_stale = (now - radio['last_update']) > stale_threshold
        stale_seconds = now - radio['last_update']

        # Station header
        if station != current_station:
            current_station = station
            hdr_color = dim_color if is_stale else header_color
            header_text = strip_label_font.render('-- %s ' % station, True, hdr_color)
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


def draw_mults_progress(size, qsos_by_mult):
    """
    Draw a multiplier progress display with progress bar and percentage.
    Shows "67/84 sections worked (80%)" with visual progress bar.
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
    mult_type = 'States' if config.MULTS == 'STATES' else 'Sections'

    # Get actual font heights for proper spacing
    title_font = bigger_font
    title_height = title_font.get_height()
    main_font = view_font
    main_height = main_font.get_height()

    # Calculate text content first to determine width needed
    title = f'{mult_type} Progress'
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

    # Get all mults sorted, track which are worked
    all_mults = sorted(mult_dict.keys())
    worked_set = {code for code in all_mults if qsos_by_mult.get(code, 0) > 0}
    num_worked = len(worked_set)
    num_remaining = len(all_mults) - num_worked

    # Get actual font heights
    title_font = view_font
    title_height = title_font.get_height()
    cell_font = view_font
    cell_height = cell_font.get_height() + 8
    padding = 20

    mult_type = 'States' if config.MULTS == 'STATES' else 'Sections'

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
    cells = [['Rank', 'Operator', 'QSOs', '%']]

    ordinals = ['1st', '2nd', '3rd', '4th', '5th', '6th', '7th', '8th', '9th', '10th',
                '11th', '12th', '13th', '14th', '15th', '16th', '17th', '18th', '19th', '20th']

    for i, (name, count) in enumerate(qso_operators):
        rank = ordinals[i] if i < len(ordinals) else f'{i+1}th'
        pct = (count / total_qsos) * 100
        cells.append([rank, name, f'{count}', f'{pct:.1f}%'])

    title = 'Operator Leaderboard'

    logging.debug('draw_operator_leaderboard() done')
    return draw_table(size, cells, title)


def draw_map(size, qsos_by_section):
    """
    make the choropleth with Cartopy & section shapefiles
    """
    logging.debug('draw_section map()')
    width_inches = size[0] / 100.0
    height_inches = size[1] / 100.0
    fig = plt.Figure(figsize=(width_inches, height_inches), dpi=100, facecolor='black')

    projection = ccrs.PlateCarree()
    ax = fig.add_axes([0, 0, 1, 1], projection=projection)
    ax.set_extent([-168, -52, 10, 60], ccrs.Geodetic())
    ax.add_feature(cfeature.OCEAN, color=MAP_OCEAN_COLOR)
    ax.add_feature(cfeature.LAKES, color=MAP_LAKE_COLOR)
    ax.add_feature(cfeature.LAND, color=MAP_LAND_COLOR)

    ax.coastlines('50m')
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
            section_color = 'k' if color_index == 0 else color_palette[color_index]
            ax.add_geometries([shape.geometry], projection, linewidth=0.7, edgecolor="w", facecolor=section_color)

    # show terminator
    date = datetime.datetime.utcnow()  # this might have some timezone problems?
    ax.add_feature(nightshade.Nightshade(date, alpha=0.5))

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
