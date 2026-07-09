# Post-Field-Day To-Do (2026 ARRL FD)

Things to take care of after Field Day wraps up.

## 1. Fold this year's operators into the prior-operators database

Add the 2026 ARRL FD operator table into `prior_operators.db` so next year's
"new operator" feature and the new-ops-per-year (YOY) chart count correctly.

The script already exists — `utils/import_prior_operators.py`. It deliberately skips
the current live event (`DATABASE_FILENAME`), so this year's DB must be passed
explicitly (or it will get auto-discovered automatically once the config rolls
to next year's event).

```bash
cd /home/pi/n1mm_view
# Preview first:
python3 utils/import_prior_operators.py --dry-run n1mm_view.2026ARRLFD.db
# Then commit:
python3 utils/import_prior_operators.py n1mm_view.2026ARRLFD.db
```

- Idempotent: existing rows are preserved; only new (operator, event) pairs are
  inserted. Safe to re-run.
- Use `--reset` only to wipe and rebuild `prior_operators.db` from scratch.

## 2. Duplicate QSO handling (flag, don't delete)

> **Status 2026-06-29: COMPLETED on the live DB.** Ran `utils/find_dupes.py --apply`
> against `n1mm_view.2026ARRLFD.db`: 36 dupes flagged, **1360 net** QSOs (was
> 1396). Backup saved as `n1mm_view.2026ARRLFD.db.20260629-132912.bak`.
> Had to **restart `n1mm_view_headless.service`** so the long-running process
> reloaded the new `dataaccess.py` filtering code (otherwise it kept serving the
> old 1396 counts from memory). Charts regenerated and rsynced to uparc/sparc/
> ny4i.com; verified N4GRC dropped 102 -> 99 on the remote sites.
>
> **This is now a recurring annual post-FD step** -- run the flagging each year
> after the contest (see "How to run" below), then restart headless if it is
> running.

There is currently **no Field Day dupe checking**. The only uniqueness enforced
is the `qso_id` PRIMARY KEY (the logger's QSO GUID), which stops the *same* record
from being inserted twice but does nothing about working the same station twice
on the same band/mode -- those are separate `qso_id`s and both currently count.

A read-only finder already exists: **`utils/find_dupes.py`** (run it any time; it does
not modify the DB). As of 2026-06-29 the live `n1mm_view.2026ARRLFD.db` has
**30 dupe sets / 36 dupe QSOs**.

### Important: the dupe key is callsign + band + SIMPLE mode group

The FD dupe rule is per **CW / PHONE / DATA** group, NOT per exact submode.
FT8 and FT4 on one band are the same DATA contact. Keying on exact `mode_id`
misses these -- it found only 32 dupes vs. the correct 36. Use
`constants.Modes.MODE_TO_SIMPLE_MODE` (already in the codebase) for the grouping.

### Approach: flag, do not delete

Non-destructive and reversible, and it mirrors how the logger itself keeps dupes
in the log scored at zero.

1. **DONE** -- column `duplicate INTEGER NOT NULL DEFAULT 0` added to `qso_log`
   via the migration in `dataaccess.create_tables()` (next to the `state`
   migration), with index `qso_log_duplicate`. Inert until counts use it.
2. **DONE** -- `utils/find_dupes.py --apply` flags all but the **earliest** QSO (by
   timestamp) in each `(callsign, band_id, simple-mode-group)` set. Backs up the
   DB first (`*.db.<timestamp>.bak`); idempotent (clears + recomputes each run);
   `--no-backup` to skip the backup. Verified on a copy: 36 flagged, 1360 net.
3. **DONE** -- `duplicate = 1` is now excluded from every count/chart/score
   query in `dataaccess.py` via the `_dupe_clause(cursor)` helper, which emits
   `WHERE/AND duplicate = 0` only when the column exists (so old archives read by
   `one_chart.py` / `utils/generate_comparison_charts.py` still work). Filtered:
   get_qso_count, get_operators_by_qsos, get_station_qsos,
   get_qsos_per_hour_per_operator, get_qso_band_modes, get_qso_classes,
   get_qso_categories, get_qsos_per_hour_per_band, get_qsos_by_section,
   get_qsos_by_state. Verified: flagged DB -> 1360, unflagged -> 1396, full test
   suite (144) green.
   - Intentionally NOT filtered: `get_operator_first_qsos` (new-op participation
     -- a QSO flagged because another op worked that call first is still that
     operator's real first contact), `get_last_qso` and `get_last_N_qsos`
     (display of actual recent contacts).
   - Charts only refresh dupes out **after** running `utils/find_dupes.py --apply` on
     the live DB; flagging changes the qso_count signature, triggering one
     headless regen.

### How to run the flagging (after FD, against the real DB)

```bash
cd /home/pi/n1mm_view
python3 utils/find_dupes.py                 # report only (read-only)
python3 utils/find_dupes.py --apply         # flag dupes, backs up the DB first
```

**Resolved (2026):** GOTA was not active, so grouping stays
`(callsign, band, simple-mode-group)` without `mycall`. Revisit only if a future
year runs GOTA or otherwise logs under a second callsign.

**Backup first** before any write pass: copy to `*.db.<timestamp>.bak`.

## 3. Check for site operators worked as stations (own-effort rule)

Field Day rule: a person who operated from our site may not also be *worked* by
our site as a separate station. **`utils/check_operator_worked.py`** cross-references
the `operator` table against `qso_log.callsign` and reports any overlap, with
each offending QSO's time/band/mode/who-logged-it and its `qso_id`. Read-only.

```bash
cd /home/pi/n1mm_view
python3 utils/check_operator_worked.py            # uses DATABASE_FILENAME from the INI
python3 utils/check_operator_worked.py some.db    # or a specific database
```

**Findings 2026-06-29** -- 3 offending QSOs:
- `K4OB`   20M CW  2026-06-27 18:14 (logged by K4OB -- looks like a self/test entry)
- `KG4PIE` 20M USB 2026-06-28 10:51 (logged by N0OAC)
- `N4GRC`  10M FT8 2026-06-28 17:22 (logged by KQ4JJY)

**Action:** delete these in **TR4W** (the logger / system of record for the
Cabrillo submission), not just the dashboard DB, then re-sync. This is an annual
post-FD check.

## 4. Validate worked callsigns (O-for-0 typos, malformed calls)

**`utils/check_callsigns.py`** (read-only) validates every `qso_log.callsign` against
an ITU prefix-allocation regex and reports any that don't conform. The common
hit is **O typed for 0** (the call then has no digit after the prefix); the
script prints the suggested correction (it swaps each `O` for `0` one at a time
and only suggests the swap that makes the call valid). Portable/slashed calls
(`WB2GDZ/8`, `KT4Q/KL7`) are handled by a second check -- accepted if any
`/`-separated segment is itself a valid call -- so they are NOT flagged.

```bash
cd /home/pi/n1mm_view
python3 utils/check_callsigns.py             # uses DATABASE_FILENAME from the INI
python3 utils/check_callsigns.py some.db     # or a specific database
```

**Findings 2026-06-29** -- 5 O-for-0 typos (all 20M USB):
- `KBOMQX` -> KB0MQX   (logged by N4GRC)
- `KOAZW`  -> K0AZW    (logged by KB8ESY)
- `NOJG`   -> N0JG     (logged by K2BHS)
- `NOSZ`   -> N0SZ     (logged by KB8ESY)
- `WOERH`  -> W0ERH    (logged by KB8ESY)

**Action:** fix the O->0 in **TR4W** and in this dashboard DB
(`qso_log.callsign`), then re-sync. Identification only -- no auto-fix (could add
a `--fix` to apply the unambiguous O->0 swaps to the dashboard DB if wanted).
