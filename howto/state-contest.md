# HOWTO: Set up n1mm_view for a State contest

This guide sets up the dashboard for a contest whose multipliers are US
states, such as a state QSO party worked from outside the state.

With `MULTS = STATES`, n1mm_view shows:

| Slide | Setting |
|---|---|
| North America map of states worked, shaded by QSO count | `MULTS = STATES` |
| States Progress (worked/51) and States Remaining | `SHOW_MULT_PROGRESS`, `SHOW_MULT_REMAINING` |
| New-state alert crawl | `SHOW_MULT_ALERT` |
| Last-10-QSOs log table, with a State column | always on |

The state list is the 50 states plus DC (51 total). Canadian provinces, DX
and counties are not counted as multipliers in this mode.

All settings go in your live ini, normally `~/.config/n1mm_view.ini`. See
`n1mm_view.ini.sample` for the full list with comments.

## 1. Back up the ini and start a new database

```bash
cp ~/.config/n1mm_view.ini ~/.config/n1mm_view.ini.$(date +%Y%m%d-%H%M%S).bak
```

Use a new database file for each contest, e.g.
`n1mm_view.2026FLQP.db`. The collector creates it on the first QSO.

## 2. Edit the ini

```ini
[GLOBAL]
DATABASE_FILENAME = n1mm_view.2026FLQP.db
MULTS = STATES
; List only the modes the contest allows
CONTEST_MODES = CW,PHONE

[EVENT INFO]
NAME = Florida QSO Party 2026
START_TIME = 2026-04-25 16:00:00
END_TIME = 2026-04-26 21:59:59
QTH_LATITUDE = 27.98
QTH_LONGITUDE = -82.75

[FEATURES]
SHOW_MULT_PROGRESS = True
SHOW_MULT_REMAINING = True
SHOW_MULT_ALERT = True
; Field Day charts that don't apply
SHOW_QSOS_BY_CLASS = False
SHOW_QSOS_BY_CATEGORY = False
; Set False for a single-mode contest or a single station
;SHOW_QSOS_BY_MODE = False
;SHOW_QSOS_BY_STATION = False

[HOOKS]
; Optional: run a script on each new state
;NEW_MULTIPLIER_SCRIPT = /home/pi/n1mm_view/examples/vesta_hook.sh
; Set true if the contest counts each state once per band
;MULT_PER_BAND = false
```

Leave `SHOW_COUNTRIES`, `SHOW_COUNTRY_MAP` and `SHOW_MULTS_BY_BAND` off; they
are for DX contests (see [cq-zone-contest.md](cq-zone-contest.md)).

Note that a section header such as `[FEATURES]` must not be commented out. If
it is, every key under it is silently ignored.

## 3. Where the state comes from

In `STATES` mode the collector takes the state from the contact packet's
`<section>` field. Your logger must put the received state abbreviation
(e.g. `FL`, `NY`) there. Values that aren't one of the 51 abbreviations are
stored but don't count toward the map or progress.

Check this before the contest: log a test QSO, then confirm the state shows
up in the State column of the last-QSOs table and is shaded on the map.

## 4. Restart the services

```bash
sudo systemctl restart n1mm_view_collector n1mm_view_headless n1mm_view_webserver
```

Confirm the settings were read (needs `LOG_LEVEL = INFO` or lower):

```bash
sudo journalctl -u n1mm_view_headless -b | grep "Feature toggles" | tail -1
```

## 5. Test before the contest

1. Log a few test QSOs, or have the logger resend its QSOs over UDP.
2. Open the dashboard (`http://<pi-address>:8080/`) and check that the states
   are shaded on the map and counted on the States Progress slide.
3. **Start a fresh database for the contest itself.** Either delete the test
   DB or point `DATABASE_FILENAME` at a new name, then restart the collector.

If you set `[DEBUG] SKIP_TIMESTAMP_CHECK = True` while testing, set it back to
`False` before the contest.
