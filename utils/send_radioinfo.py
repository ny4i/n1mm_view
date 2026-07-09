#!/usr/bin/env python3
"""
send_radioinfo.py - RadioInfo UDP traffic generator for testing n1mm_view.

Sends N1MM/TR4W-style <RadioInfo> broadcasts to UDP port 12060 so you can
verify the dashboard handles any number of stations and any station-name
spelling (hyphens, spaces, duplicates, etc.) WITHOUT needing the real radios.

Run it on your Mac (or anywhere that can reach the collector):

    # 3 virtual stations, unicast to the pi at 192.168.1.50
    python3 send_radioinfo.py --host 192.168.1.50 \
        --station STATION1 --station STATION-3 --station "FIELD DAY 2"

    # mimic TR4W's real behaviour: UDP broadcast to the whole subnet
    python3 send_radioinfo.py --broadcast

    # collision test: two different boxes claiming the SAME name
    python3 send_radioinfo.py --host 192.168.1.50 \
        --station NODE1 --station NODE1

Each --station may be NAME[:RADIONR[:FREQ_MHZ[:MODE]]], e.g.
    --station "STATION1:1:14.074:FT8"     # FT8 station
    --station "STATION-3:1:7.040:CW"      # hyphen in the name
The default (no --station given) sends an FT8 station, a hyphenated name,
and a name containing a space.

It keeps re-sending every --interval seconds (default 3) so rows stay fresh
and never age out of the dashboard. Ctrl+C to stop.

Notes
-----
* The collector's ALLOWED_APPS filter defaults to {n1mmlogger.net, tr4w}; this
  script tags packets with app=TR4W so they pass. Use --app NAME to change it,
  or --app '' to omit the <app> element entirely (also passes the filter).
* Freq in the XML is in tens-of-Hz (N1MM convention); the script converts the
  MHz value you give it for you.
"""
import argparse
import socket
import sys
import time

# Mode groups, embedded from constants.py (Modes.SIMPLE_MODES / SIMPLE_MODES_LIST)
# so this stays a single portable file. The project classifies every mode into
# N/A / CW / PHONE / DATA -- note FT8, FT4, RTTY, PSK and DATA all map to DATA.
# Keep this in sync with constants.py if the project's mode list changes.
GROUP_NAMES = ['N/A', 'CW', 'PHONE', 'DATA']
MODE_GROUP = {
    'N/A': 0, 'CW': 1,
    'AM': 2, 'FM': 2, 'LSB': 2, 'USB': 2, 'SSB': 2, 'None': 2,
    'RTTY': 3, 'PSK': 3, 'PSK31': 3, 'PSK63': 3, 'FT8': 3, 'FT4': 3,
    'MFSK': 3, 'DATA': 3, 'NoMode': 3,
}
ALL_MODES = list(MODE_GROUP.keys())

# Representative dial frequency (MHz) per simple group, so packets look realistic.
GROUP_FREQ = {'CW': 14.040, 'PHONE': 14.250, 'DATA': 14.074, 'N/A': 14.100}


def group_of(mode):
    """Return the simple mode-group name (CW/PHONE/DATA) for a mode string."""
    return GROUP_NAMES[MODE_GROUP.get(mode, 0)]


def build_packet(station_name, radio_nr, freq_mhz, mode, op_call, app,
                 is_running, is_active):
    """Return a RadioInfo XML packet (bytes) matching N1MM/TR4W format."""
    # N1MM Freq field is in units of 10 Hz; collector multiplies by 10 to get Hz.
    freq_tens_hz = int(round(freq_mhz * 1_000_000 / 10))
    app_el = f'  <app>{app}</app>\n' if app else ''
    xml = (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        "<RadioInfo>\n"
        f"{app_el}"
        f'  <StationName>{station_name}</StationName>\n'
        f'  <RadioNr>{radio_nr}</RadioNr>\n'
        f'  <Freq>{freq_tens_hz}</Freq>\n'
        f'  <TXFreq>{freq_tens_hz}</TXFreq>\n'
        f'  <Mode>{mode}</Mode>\n'
        f'  <OpCall>{op_call}</OpCall>\n'
        f'  <IsRunning>{"True" if is_running else "False"}</IsRunning>\n'
        '  <FocusEntry>0</FocusEntry>\n'
        '  <Antenna>0</Antenna>\n'
        '  <Rotors></Rotors>\n'
        f'  <FocusRadioNr>{radio_nr}</FocusRadioNr>\n'
        '  <IsStereo>False</IsStereo>\n'
        '  <IsSplit>False</IsSplit>\n'
        f'  <ActiveRadioNr>{radio_nr if is_active else 0}</ActiveRadioNr>\n'
        '  <IsTransmitting>False</IsTransmitting>\n'
        '  <FunctionKeyCaption></FunctionKeyCaption>\n'
        '  <RadioName>TestRig</RadioName>\n'
        '  <AuxAntSelected>-1</AuxAntSelected>\n'
        '  <AuxAntSelectedName></AuxAntSelectedName>\n'
        '  <IsConnected>True</IsConnected>\n'
        '</RadioInfo>\n'
    )
    return xml.encode('utf-8')


def parse_station(spec, default_freq, default_mode):
    """Parse a NAME[:RADIONR[:FREQ_MHZ[:MODE]]] station spec.

    Fields are positional after the name; names with hyphens/spaces are
    preserved verbatim (only ':' separates fields, and station names don't
    normally contain ':').
    """
    parts = spec.split(':')
    name = parts[0]
    radio_nr = int(parts[1]) if len(parts) >= 2 and parts[1] else 1
    freq = float(parts[2]) if len(parts) >= 3 and parts[2] else default_freq
    mode = parts[3].upper() if len(parts) >= 4 and parts[3] else default_mode
    return name, radio_nr, freq, mode


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Send test RadioInfo UDP packets to n1mm_view.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument('--host', default='127.0.0.1',
                    help='destination host/IP of the collector (default: 127.0.0.1)')
    ap.add_argument('--port', type=int, default=12060,
                    help='destination UDP port (default: 12060)')
    ap.add_argument('--broadcast', action='store_true',
                    help='send to the 255.255.255.255 broadcast address (overrides --host), '
                         'mimicking how TR4W/N1MM actually broadcast')
    ap.add_argument('--station', action='append', dest='stations',
                    metavar='NAME[:RADIONR[:FREQ[:MODE]]]',
                    help='a virtual station; repeat for several. Default: a 3-station '
                         'set exercising an FT8 station, a hyphen, and a space.')
    ap.add_argument('--all-modes', action='store_true',
                    help='ignore --station and send one station for every known mode '
                         '(CW/PHONE/DATA groups), so you can see which modes the '
                         'dashboard renders. Useful for the FT8/digital case.')
    ap.add_argument('--interval', type=float, default=3.0,
                    help='seconds between refresh broadcasts (default: 3)')
    ap.add_argument('--count', type=int, default=0,
                    help='stop after N refresh rounds (default: 0 = run forever)')
    ap.add_argument('--app', default='TR4W',
                    help="value for the <app> element (default: TR4W). "
                         "Use --app '' to omit the element entirely.")
    ap.add_argument('--freq', type=float, default=14.074,
                    help='default frequency in MHz for stations without an explicit freq')
    ap.add_argument('--opcall', default='TEST',
                    help='OpCall to report (default: TEST)')
    ap.add_argument('--mode', default='CW',
                    help='default mode for stations without an explicit mode (default: CW)')
    args = ap.parse_args(argv)

    if args.all_modes:
        # One station per concrete on-air mode, named by mode, frequency chosen
        # to match its group. Exercises every CW/PHONE/DATA mode at once.
        skip = {'N/A', 'None', 'NoMode'}
        modes = [m for m in ALL_MODES if m not in skip]
        stations = [(f'{m}-STN', 1, GROUP_FREQ.get(group_of(m), args.freq), m)
                    for m in modes]
    else:
        # Default set reproduces the dry-run mix: an FT8 station (the one that
        # went missing), a hyphenated name, and a name with a space.
        specs = args.stations or [
            'STATION1:1:14.074:FT8',
            'STATION-3:1:7.040:CW',
            'FIELD DAY 2:1:14.250:SSB',
        ]
        stations = [parse_station(s, args.freq, args.mode) for s in specs]

    # Flag any mode the project wouldn't recognise (mirrors the collector, which
    # warns "unknown mode" and the dashboard may then fail to classify it).
    for name, _radio_nr, _freq, mode in stations:
        if mode not in MODE_GROUP:
            print(f'  WARNING: station {name!r} mode {mode!r} is not in the known '
                  f'mode groups {GROUP_NAMES[1:]}; dashboard may not display it.')

    dest_host = '255.255.255.255' if args.broadcast else args.host
    dest = (dest_host, args.port)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if args.broadcast:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    print(f'Sending RadioInfo to {dest_host}:{args.port} '
          f'every {args.interval}s  (app={args.app or "<omitted>"})')
    for name, radio_nr, freq, mode in stations:
        print(f'  station {name!r}  radio_nr={radio_nr}  freq={freq} MHz  '
              f'mode={mode} (group {group_of(mode)})')
    print('Ctrl+C to stop.\n')

    rounds = 0
    try:
        while True:
            rounds += 1
            for idx, (name, radio_nr, freq, mode) in enumerate(stations):
                # Nudge the frequency a little each round so the dashboard
                # visibly updates; mark the first station as the active one.
                live_freq = freq + (rounds % 10) * 0.0001
                pkt = build_packet(name, radio_nr, live_freq, mode,
                                   args.opcall, args.app,
                                   is_running=(idx == 0), is_active=(idx == 0))
                sock.sendto(pkt, dest)
            print(f'[{time.strftime("%H:%M:%S")}] round {rounds}: '
                  f'sent {len(stations)} RadioInfo packet(s)')
            if args.count and rounds >= args.count:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print('\nStopped.')
    finally:
        sock.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
