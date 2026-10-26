# HOWTO: Set up n1mm_view for a CQ Zone contest (CQ WW DX)

This guide sets up the dashboard for CQ WW DX (SSB or CW). The same steps
work for other contests whose multipliers are CQ zones, optionally plus DXCC
countries.

CQ WW scores **zones (1-40) + DXCC countries, each counted once per band**.
n1mm_view shows:

| Slide | Setting |
|---|---|
| CQ zone map, shaded by QSO count | `MULTS = CQZONES` |
| Zones Progress (worked/40) and Zones Remaining | `SHOW_MULT_PROGRESS`, `SHOW_MULT_REMAINING` |
| Countries Worked list, grouped by continent | `SHOW_COUNTRIES` |
| Countries Worked map | `SHOW_COUNTRY_MAP` |
| Multipliers by Band table (QSOs, zones, countries per band, with totals) | `SHOW_MULTS_BY_BAND` |
| New-multiplier alerts (crawl, Vestaboard, etc.) | `SHOW_MULT_ALERT`, `[HOOKS]` |

All settings go in your live ini, normally `~/.config/n1mm_view.ini`. See
`n1mm_view.ini.sample` for the full list with comments.

## 1. Back up the ini and start a new database

Back up the ini before editing it, using a timestamped name so older backups
are kept:

```bash
cp ~/.config/n1mm_view.ini ~/.config/n1mm_view.ini.$(date +%Y%m%d-%H%M%S).bak
```

Use a **new database file for each contest weekend**. CQ WW SSB and CQ WW CW
are separate weekends, so give each its own file. The collector creates the
file on its first QSO.

## 2. Edit the ini

```ini
[GLOBAL]
DATABASE_FILENAME = n1mm_view.2026CQWWSSB.db
MULTS = CQZONES
; Single-mode weekend: show only the mode in play in the score table
CONTEST_MODES = PHONE

[EVENT INFO]
NAME = CQ WW DX SSB 2026
START_TIME = 2026-10-24 00:00:00
END_TIME = 2026-10-25 23:59:59
QTH_LATITUDE = 27.98
QTH_LONGITUDE = -82.75

[FEATURES]
SHOW_MULT_PROGRESS = True
SHOW_MULT_REMAINING = True
SHOW_MULT_ALERT = True
SHOW_COUNTRIES = True
SHOW_COUNTRY_MAP = True
SHOW_MULTS_BY_BAND = True
; Charts that don't apply to CQ WW
SHOW_QSOS_BY_MODE = False
SHOW_QSOS_BY_CLASS = False
SHOW_QSOS_BY_CATEGORY = False
; Set False too if you run a single station
;SHOW_QSOS_BY_STATION = False

[HOOKS]
NEW_MULTIPLIER_SCRIPT = /home/pi/n1mm_view/examples/vesta_hook.sh
; CQ WW counts mults once per band, so alert on a zone or country that is
; new on this band, not only on its first appearance in the contest
MULT_PER_BAND = true
```

For the CW weekend, use `CONTEST_MODES = CW` and a new `DATABASE_FILENAME`.

Note that a section header such as `[FEATURES]` or `[HOOKS]` must not be
commented out. If it is, every key under it is silently ignored.

## 3. Where the data comes from

n1mm_view does **not** look up zones or countries itself. It stores what the
logger sends in each contact UDP packet:

| UDP field | Used for |
|---|---|
| `<zone>` | CQ zone (stored as the CQ zone because `MULTS = CQZONES`) |
| `<countryprefix>` | DXCC country, e.g. `K`, `VP2M`, `*IT9` (`*` = WAE-only entity) |
| `<continent>` | Continent grouping on the Countries Worked list |

TR4W and N1MM+ resolve these from the logger's country file (AD1C CTY.DAT),
including exact-callsign exceptions such as `=TO1O` for St. Martin (FS). These
values are treated as authoritative, so keep your logger's country file up to
date before the contest.

## 4. Restart the services

```bash
sudo systemctl restart n1mm_view_collector n1mm_view_headless n1mm_view_webserver
```

Check the headless log for the `Feature toggles` line to confirm your
settings were read (needs `LOG_LEVEL = INFO` or lower):

```bash
sudo journalctl -u n1mm_view_headless -b | grep "Feature toggles" | tail -1
```

## 5. Test before the contest

1. Log a few test QSOs, or have the logger resend its QSOs over UDP.
2. Open the dashboard (`http://<pi-address>:8080/`) and check the zone map,
   the Countries Worked list and map, and the Multipliers by Band table.
3. Compare the totals on the Multipliers by Band table with your logger's
   multiplier count. They should agree.
4. **Start a fresh database for the contest itself.** Either delete the test
   DB or point `DATABASE_FILENAME` at a new name, then restart the collector.

If you set `[DEBUG] SKIP_TIMESTAMP_CHECK = True` while testing, set it back to
`False` before the contest.

## 6. Alerts

With `[HOOKS] NEW_MULTIPLIER_SCRIPT` set, one `new_multiplier` event fires per
QSO that brings in a new zone, a new country, or both. The script receives:

- `N1MMV_NEW_MULTIPLIER`: the new zone (empty if only the country is new)
- `N1MMV_NEW_COUNTRY`: the new country (empty if only the zone is new;
  requires `SHOW_COUNTRIES = True`)
- `N1MMV_BAND`, `N1MMV_QSO_COUNT`, plus the other `N1MMV_*` variables
  documented in `n1mm_view.ini.sample`

`examples/vesta_hook.sh` posts these to a Vestaboard, e.g.
`New Zone 5 20M Country VP2M QSOs:53`.

## Known limitations

- The Zones Progress and Remaining slides count each zone once (worked/40), not
  once per band. Per-band counts are on the Multipliers by Band table.
- If a DXCC entity has no outline in the country map data, it is left
  unshaded on the map. It still appears on the Countries Worked list.
