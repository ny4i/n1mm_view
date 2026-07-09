#!/usr/bin/env python3
"""
Send mock RadioInfo UDP packets to test the flight strip display.
Usage: python3 test_radio_info.py
"""

import socket
import time

UDP_PORT = 12060
UDP_ADDR = '127.0.0.1'

RADIOS = [
    {
        'StationName': 'STATION1',
        'RadioNr': '1',
        'Freq': '1425000',     # 14.250.00 MHz in 10Hz units
        'TXFreq': '1425500',   # 14.255.00 MHz
        'Mode': 'CW',
        'OpCall': 'N1KDO',
        'IsRunning': 'True',
        'IsTransmitting': 'False',
        'IsConnected': 'True',
        'IsSplit': 'True',
        'RadioName': 'IC-7300',
        'Antenna': '1',
    },
    {
        'StationName': 'STATION1',
        'RadioNr': '2',
        'Freq': '703000',      # 7.030.00 MHz
        'TXFreq': '703000',
        'Mode': 'CW',
        'OpCall': 'NY4I',
        'IsRunning': 'False',
        'IsTransmitting': 'False',
        'IsConnected': 'True',
        'IsSplit': 'False',
        'RadioName': 'FT-991A',
        'Antenna': '2',
    },
    {
        'StationName': 'STATION2',
        'RadioNr': '1',
        'Freq': '2103500',     # 21.035.00 MHz
        'TXFreq': '2103500',
        'Mode': 'CW',
        'OpCall': 'W3ABC',
        'IsRunning': 'True',
        'IsTransmitting': 'False',
        'IsConnected': 'True',
        'IsSplit': 'False',
        'RadioName': 'TS-590',
        'Antenna': '1',
    },
]


def make_radio_info_xml(radio):
    fields = ''.join(f'<{k}>{v}</{k}>' for k, v in radio.items())
    return f'<RadioInfo>{fields}</RadioInfo>'


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f'Sending RadioInfo packets to {UDP_ADDR}:{UDP_PORT}')
    print('Press Ctrl+C to stop.\n')

    cycle = 0
    try:
        while True:
            for i, radio in enumerate(RADIOS):
                # Toggle TX on STATION2 R1 every other cycle
                if i == 2:
                    radio['IsTransmitting'] = 'True' if cycle % 2 == 0 else 'False'

                xml = make_radio_info_xml(radio)
                sock.sendto(xml.encode(), (UDP_ADDR, UDP_PORT))
                print(f'  Sent {radio["StationName"]} R{radio["RadioNr"]} '
                      f'{radio["RadioName"]} {radio["Freq"]}')

            cycle += 1
            print(f'--- cycle {cycle} done, sleeping 5s ---')
            time.sleep(5)
    except KeyboardInterrupt:
        print('\nStopped.')
    finally:
        sock.close()


if __name__ == '__main__':
    main()
