#!/usr/bin/python3
"""
check_callsigns.py  --  READ-ONLY callsign sanity check for qso_log.

Validates every worked callsign in `qso_log.callsign` against an ITU
prefix-allocation regex (a valid allocated prefix, then a digit, then up to
three alphanumerics, then a trailing letter) and reports any that do not
conform. Typical hits:

  - O-for-0 typos:  KBOMQX (should be KB0MQX), NOJG (N0JG), WOERH (W0ERH) --
    the letter O sits where the call's digit belongs, so there is no digit
    after the prefix and the match fails.
  - Portable / slashed calls:  KT4Q/KL7, WB2GDZ/8 -- these are legitimate but
    the regex has no '/', so they are flagged for a human to eyeball.

By default this is identification ONLY. With --fix it rewrites the *unambiguous*
O-for-0 typos (where exactly one O->0 swap yields a valid call) in
qso_log.callsign, backing up the database first. Ambiguous or non-O typos are
never auto-changed -- they are listed for manual review.

NOTE: --fix only touches this dashboard DB. Still fix the same calls in TR4W
(the logger / Cabrillo source of record), then re-sync.

Usage:
    python3 check_callsigns.py                 # report only, INI database
    python3 check_callsigns.py some_event.db   # report only, specific database
    python3 check_callsigns.py --fix           # apply unambiguous O->0 fixes
    python3 check_callsigns.py --fix --no-backup
"""

import argparse
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone

import constants
from config import Config

# ITU prefix-allocation callsign pattern: <allocated prefix><digit><0-3
# alnum><letter>. Matched with re.fullmatch (anchored both ends). Anything that
# is not a structurally valid call for an allocated prefix is reported.
CALLSIGN_PATTERN = (
    r"(2A[A-Z]?|2B[A-Z]?|2C[A-Z]?|2D[A-Z]?|2E[A-Z]?|2F[A-Z]?|2G[A-Z]?|2H[A-Z]?|2I[A-Z]?|2J[A-Z]?|2K[A-Z]?|2L[A-Z]?|2M[A-Z]?|2N[A-Z]?|2O[A-Z]?|2P[A-Z]?|2Q[A-Z]?|2R[A-Z]?|2S[A-Z]?|2T[A-Z]?|2U[A-Z]?|2V[A-Z]?|2W[A-Z]?|2X[A-Z]?|2Y[A-Z]?|2Z[A-Z]?"
    r"|3A[A-Z]?|3B[A-Z]?|3C[A-Z]?|3D[A-M]|3D[N-Z]|3E[A-Z]?|3F[A-Z]?|3G[A-Z]?|3H[A-Z]?|3I[A-Z]?|3J[A-Z]?|3K[A-Z]?|3L[A-Z]?|3M[A-Z]?|3N[A-Z]?|3O[A-Z]?|3P[A-Z]?|3Q[A-Z]?|3R[A-Z]?|3S[A-Z]?|3T[A-Z]?|3U[A-Z]?|3V[A-Z]?|3W[A-Z]?|3X[A-Z]?|3Y[A-Z]?|3Z[A-Z]?"
    r"|4A[A-Z]?|4B[A-Z]?|4C[A-Z]?|4D[A-Z]?|4E[A-Z]?|4F[A-Z]?|4G[A-Z]?|4H[A-Z]?|4I[A-Z]?|4J[A-Z]?|4K[A-Z]?|4L[A-Z]?|4M[A-Z]?|4O[A-Z]?|4P[A-Z]?|4Q[A-Z]?|4R[A-Z]?|4S[A-Z]?|4T[A-Z]?|4U[A-Z]?|4V[A-Z]?|4W[A-Z]?|4X[A-Z]?|4Y[A-Z]?|4Z[A-Z]?"
    r"|5A[A-Z]?|5B[A-Z]?|5C[A-Z]?|5D[A-Z]?|5E[A-Z]?|5F[A-Z]?|5G[A-Z]?|5H[A-Z]?|5I[A-Z]?|5J[A-Z]?|5K[A-Z]?|5L[A-Z]?|5M[A-Z]?|5N[A-Z]?|5O[A-Z]?|5P[A-Z]?|5Q[A-Z]?|5R[A-Z]?|5S[A-Z]?|5T[A-Z]?|5U[A-Z]?|5V[A-Z]?|5W[A-Z]?|5X[A-Z]?|5Y[A-Z]?|5Z[A-Z]?"
    r"|6A[A-Z]?|6B[A-Z]?|6C[A-Z]?|6D[A-Z]?|6E[A-Z]?|6F[A-Z]?|6G[A-Z]?|6H[A-Z]?|6I[A-Z]?|6J[A-Z]?|6K[A-Z]?|6L[A-Z]?|6M[A-Z]?|6N[A-Z]?|6O[A-Z]?|6P[A-Z]?|6Q[A-Z]?|6R[A-Z]?|6S[A-Z]?|6T[A-Z]?|6U[A-Z]?|6V[A-Z]?|6W[A-Z]?|6X[A-Z]?|6Y[A-Z]?|6Z[A-Z]?"
    r"|7A[A-Z]?|7B[A-Z]?|7C[A-Z]?|7D[A-Z]?|7E[A-Z]?|7F[A-Z]?|7G[A-Z]?|7H[A-Z]?|7I[A-Z]?|7J[A-Z]?|7K[A-Z]?|7L[A-Z]?|7M[A-Z]?|7N[A-Z]?|7O[A-Z]?|7P[A-Z]?|7Q[A-Z]?|7R[A-Z]?|7S[A-Z]?|7T[A-Z]?|7U[A-Z]?|7V[A-Z]?|7W[A-Z]?|7X[A-Z]?|7Y[A-Z]?|7Z[A-Z]?"
    r"|8A[A-Z]?|8B[A-Z]?|8C[A-Z]?|8D[A-Z]?|8E[A-Z]?|8F[A-Z]?|8G[A-Z]?|8H[A-Z]?|8I[A-Z]?|8J[A-Z]?|8K[A-Z]?|8L[A-Z]?|8M[A-Z]?|8N[A-Z]?|8O[A-Z]?|8P[A-Z]?|8Q[A-Z]?|8R[A-Z]?|8S[A-Z]?|8T[A-Z]?|8U[A-Z]?|8V[A-Z]?|8W[A-Z]?|8X[A-Z]?|8Y[A-Z]?|8Z[A-Z]?"
    r"|9A[A-Z]?|9B[A-Z]?|9C[A-Z]?|9D[A-Z]?|9E[A-Z]?|9F[A-Z]?|9G[A-Z]?|9H[A-Z]?|9I[A-Z]?|9J[A-Z]?|9K[A-Z]?|9L[A-Z]?|9M[A-Z]?|9N[A-Z]?|9O[A-Z]?|9P[A-Z]?|9Q[A-Z]?|9R[A-Z]?|9S[A-Z]?|9T[A-Z]?|9U[A-Z]?|9V[A-Z]?|9W[A-Z]?|9X[A-Z]?|9Y[A-Z]?|9Z[A-Z]?"
    r"|A2[A-Z]?|A3[A-Z]?|A4[A-Z]?|A5[A-Z]?|A6[A-Z]?|A7[A-Z]?|A8[A-Z]?|A9[A-Z]?|AA[A-Z]?|AB[A-Z]?|AC[A-Z]?|AD[A-Z]?|AE[A-Z]?|AF[A-Z]?|AG[A-Z]?|AH[A-Z]?|AI[A-Z]?|AJ[A-Z]?|AK[A-Z]?|AL[A-Z]?|AM[A-Z]?|AN[A-Z]?|AO[A-Z]?|AP[A-Z]?|AQ[A-Z]?|AR[A-Z]?|AS[A-Z]?|AT[A-Z]?|AU[A-Z]?|AV[A-Z]?|AW[A-Z]?|AX[A-Z]?|AY[A-Z]?|AZ[A-Z]?"
    r"|B[A-Z]{0,2}"
    r"|C2[A-Z]?|C3[A-Z]?|C4[A-Z]?|C5[A-Z]?|C6[A-Z]?|C7[A-Z]?|C8[A-Z]?|C9[A-Z]?|CA[A-Z]?|CB[A-Z]?|CC[A-Z]?|CD[A-Z]?|CE[A-Z]?|CF[A-Z]?|CG[A-Z]?|CH[A-Z]?|CI[A-Z]?|CJ[A-Z]?|CK[A-Z]?|CL[A-Z]?|CM[A-Z]?|CN[A-Z]?|CO[A-Z]?|CP[A-Z]?|CQ[A-Z]?|CR[A-Z]?|CS[A-Z]?|CT[A-Z]?|CU[A-Z]?|CV[A-Z]?|CW[A-Z]?|CX[A-Z]?|CY[A-Z]?|CZ[A-Z]?"
    r"|D2[A-Z]?|D3[A-Z]?|D4[A-Z]?|D5[A-Z]?|D6[A-Z]?|D7[A-Z]?|D8[A-Z]?|D9[A-Z]?|DA[A-Z]?|DB[A-Z]?|DC[A-Z]?|DD[A-Z]?|DE[A-Z]?|DF[A-Z]?|DG[A-Z]?|DH[A-Z]?|DI[A-Z]?|DJ[A-Z]?|DK[A-Z]?|DL[A-Z]?|DM[A-Z]?|DN[A-Z]?|DO[A-Z]?|DP[A-Z]?|DQ[A-Z]?|DR[A-Z]?|DS[A-Z]?|DT[A-Z]?|DU[A-Z]?|DV[A-Z]?|DW[A-Z]?|DX[A-Z]?|DY[A-Z]?|DZ[A-Z]?"
    r"|E2[A-Z]?|E3[A-Z]?|E4[A-Z]?|E5[A-Z]?|E6[A-Z]?|E7[A-Z]?|EA[A-Z]?|EB[A-Z]?|EC[A-Z]?|ED[A-Z]?|EE[A-Z]?|EF[A-Z]?|EG[A-Z]?|EH[A-Z]?|EI[A-Z]?|EJ[A-Z]?|EK[A-Z]?|EL[A-Z]?|EM[A-Z]?|EN[A-Z]?|EO[A-Z]?|EP[A-Z]?|EQ[A-Z]?|ER[A-Z]?|ES[A-Z]?|ET[A-Z]?|EU[A-Z]?|EV[A-Z]?|EW[A-Z]?|EX[A-Z]?|EY[A-Z]?|EZ[A-Z]?"
    r"|F[A-Z]{0,2}|G[A-Z]{0,2}"
    r"|H2[A-Z]?|H3[A-Z]?|H4[A-Z]?|H6[A-Z]?|H7[A-Z]?|H8[A-Z]?|H9[A-Z]?|HA[A-Z]?|HB[A-Z]?|HC[A-Z]?|HD[A-Z]?|HE[A-Z]?|HF[A-Z]?|HG[A-Z]?|HH[A-Z]?|HI[A-Z]?|HJ[A-Z]?|HK[A-Z]?|HL[A-Z]?|HM[A-Z]?|HN[A-Z]?|HO[A-Z]?|HP[A-Z]?|HQ[A-Z]?|HR[A-Z]?|HS[A-Z]?|HT[A-Z]?|HU[A-Z]?|HV[A-Z]?|HW[A-Z]?|HX[A-Z]?|HY[A-Z]?|HZ[A-Z]?"
    r"|I[A-Z]{0,2}"
    r"|J2[A-Z]?|J3[A-Z]?|J4[A-Z]?|J5[A-Z]?|J6[A-Z]?|J7[A-Z]?|J8[A-Z]?|JA[A-Z]?|JB[A-Z]?|JC[A-Z]?|JD[A-Z]?|JE[A-Z]?|JF[A-Z]?|JG[A-Z]?|JH[A-Z]?|JI[A-Z]?|JJ[A-Z]?|JK[A-Z]?|JL[A-Z]?|JM[A-Z]?|JN[A-Z]?|JO[A-Z]?|JP[A-Z]?|JQ[A-Z]?|JR[A-Z]?|JS[A-Z]?|JT[A-Z]?|JU[A-Z]?|JV[A-Z]?|JW[A-Z]?|JX[A-Z]?|JY[A-Z]?|JZ[A-Z]?"
    r"|K[A-Z]{0,2}"
    r"|L2[A-Z]?|L3[A-Z]?|L4[A-Z]?|L5[A-Z]?|L6[A-Z]?|L7[A-Z]?|L8[A-Z]?|L9[A-Z]?|LA[A-Z]?|LB[A-Z]?|LC[A-Z]?|LD[A-Z]?|LE[A-Z]?|LF[A-Z]?|LG[A-Z]?|LH[A-Z]?|LI[A-Z]?|LJ[A-Z]?|LK[A-Z]?|LL[A-Z]?|LM[A-Z]?|LN[A-Z]?|LO[A-Z]?|LP[A-Z]?|LQ[A-Z]?|LR[A-Z]?|LS[A-Z]?|LT[A-Z]?|LU[A-Z]?|LV[A-Z]?|LW[A-Z]?|LX[A-Z]?|LY[A-Z]?|LZ[A-Z]?"
    r"|M[A-Z]{0,2}|N[A-Z]{0,2}"
    r"|OA[A-Z]?|OB[A-Z]?|OC[A-Z]?|OD[A-Z]?|OE[A-Z]?|OF[A-Z]?|OG[A-Z]?|OH[A-Z]?|OI[A-Z]?|OJ[A-Z]?|OK[A-Z]?|OL[A-Z]?|OM[A-Z]?|ON[A-Z]?|OO[A-Z]?|OP[A-Z]?|OQ[A-Z]?|OR[A-Z]?|OS[A-Z]?|OT[A-Z]?|OU[A-Z]?|OV[A-Z]?|OW[A-Z]?|OX[A-Z]?|OY[A-Z]?|OZ[A-Z]?"
    r"|P2[A-Z]?|P3[A-Z]?|P4[A-Z]?|P5[A-Z]?|P6[A-Z]?|P7[A-Z]?|P8[A-Z]?|P9[A-Z]?|PA[A-Z]?|PB[A-Z]?|PC[A-Z]?|PD[A-Z]?|PE[A-Z]?|PF[A-Z]?|PG[A-Z]?|PH[A-Z]?|PI[A-Z]?|PJ[A-Z]?|PK[A-Z]?|PL[A-Z]?|PM[A-Z]?|PN[A-Z]?|PO[A-Z]?|PP[A-Z]?|PQ[A-Z]?|PR[A-Z]?|PS[A-Z]?|PT[A-Z]?|PU[A-Z]?|PV[A-Z]?|PW[A-Z]?|PX[A-Z]?|PY[A-Z]?|PZ[A-Z]?"
    r"|R[A-Z]{0,2}"
    r"|S2[A-Z]?|S3[A-Z]?|S5[A-Z]?|S6[A-Z]?|S7[A-Z]?|S8[A-Z]?|S9[A-Z]?|SA[A-Z]?|SB[A-Z]?|SC[A-Z]?|SD[A-Z]?|SE[A-Z]?|SF[A-Z]?|SG[A-Z]?|SH[A-Z]?|SI[A-Z]?|SJ[A-Z]?|SK[A-Z]?|SL[A-Z]?|SM[A-Z]?|SN[A-Z]?|SO[A-Z]?|SP[A-Z]?|SQ[A-Z]?|SR[A-Z]?|SS[A-M]|SS[N-Z]|ST[A-Z]?|SU[A-Z]?|SV[A-Z]?|SW[A-Z]?|SX[A-Z]?|SY[A-Z]?|SZ[A-Z]?"
    r"|T2[A-Z]?|T3[A-Z]?|T4[A-Z]?|T5[A-Z]?|T6[A-Z]?|T7[A-Z]?|T8[A-Z]?|TA[A-Z]?|TB[A-Z]?|TC[A-Z]?|TD[A-Z]?|TE[A-Z]?|TF[A-Z]?|TG[A-Z]?|TH[A-Z]?|TI[A-Z]?|TJ[A-Z]?|TK[A-Z]?|TL[A-Z]?|TM[A-Z]?|TN[A-Z]?|TO[A-Z]?|TP[A-Z]?|TQ[A-Z]?|TR[A-Z]?|TS[A-Z]?|TT[A-Z]?|TU[A-Z]?|TV[A-Z]?|TW[A-Z]?|TX[A-Z]?|TY[A-Z]?|TZ[A-Z]?"
    r"|UA[A-Z]?|UB[A-Z]?|UC[A-Z]?|UD[A-Z]?|UE[A-Z]?|UF[A-Z]?|UG[A-Z]?|UH[A-Z]?|UI[A-Z]?|UJ[A-Z]?|UK[A-Z]?|UL[A-Z]?|UM[A-Z]?|UN[A-Z]?|UO[A-Z]?|UP[A-Z]?|UQ[A-Z]?|UR[A-Z]?|US[A-Z]?|UT[A-Z]?|UU[A-Z]?|UV[A-Z]?|UW[A-Z]?|UX[A-Z]?|UY[A-Z]?|UZ[A-Z]?"
    r"|V2[A-Z]?|V3[A-Z]?|V4[A-Z]?|V5[A-Z]?|V6[A-Z]?|V7[A-Z]?|V8[A-Z]?|VA[A-Z]?|VB[A-Z]?|VC[A-Z]?|VD[A-Z]?|VE[A-Z]?|VF[A-Z]?|VG[A-Z]?|VH[A-Z]?|VI[A-Z]?|VJ[A-Z]?|VK[A-Z]?|VL[A-Z]?|VM[A-Z]?|VN[A-Z]?|VO[A-Z]?|VP[A-Z]?|VQ[A-Z]?|VR[A-Z]?|VS[A-Z]?|VT[A-Z]?|VU[A-Z]?|VV[A-Z]?|VW[A-Z]?|VX[A-Z]?|VY[A-Z]?|VZ[A-Z]?"
    r"|W[A-Z]{0,2}"
    r"|XA[A-Z]?|XB[A-Z]?|XC[A-Z]?|XD[A-Z]?|XE[A-Z]?|XF[A-Z]?|XG[A-Z]?|XH[A-Z]?|XI[A-Z]?|XJ[A-Z]?|XK[A-Z]?|XL[A-Z]?|XM[A-Z]?|XN[A-Z]?|XO[A-Z]?|XP[A-Z]?|XQ[A-Z]?|XR[A-Z]?|XS[A-Z]?|XT[A-Z]?|XU[A-Z]?|XV[A-Z]?|XW[A-Z]?|XX[A-Z]?|XY[A-Z]?|XZ[A-Z]?"
    r"|Y2[A-Z]?|Y3[A-Z]?|Y4[A-Z]?|Y5[A-Z]?|Y6[A-Z]?|Y7[A-Z]?|Y8[A-Z]?|Y9[A-Z]?|YA[A-Z]?|YB[A-Z]?|YC[A-Z]?|YD[A-Z]?|YE[A-Z]?|YF[A-Z]?|YG[A-Z]?|YH[A-Z]?|YI[A-Z]?|YJ[A-Z]?|YK[A-Z]?|YL[A-Z]?|YM[A-Z]?|YN[A-Z]?|YO[A-Z]?|YP[A-Z]?|YQ[A-Z]?|YR[A-Z]?|YS[A-Z]?|YT[A-Z]?|YU[A-Z]?|YV[A-Z]?|YW[A-Z]?|YX[A-Z]?|YY[A-Z]?"
    r"|Z2[A-Z]?|Z3[A-Z]?|Z8[A-Z]?|ZA[A-Z]?|ZB[A-Z]?|ZC[A-Z]?|ZD[A-Z]?|ZE[A-Z]?|ZF[A-Z]?|ZG[A-Z]?|ZH[A-Z]?|ZI[A-Z]?|ZJ[A-Z]?|ZK[A-Z]?|ZL[A-Z]?|ZM[A-Z]?|ZN[A-Z]?|ZO[A-Z]?|ZP[A-Z]?|ZQ[A-Z]?|ZR[A-Z]?|ZS[A-Z]?|ZT[A-Z]?|ZU[A-Z]?|ZV[A-Z]?|ZW[A-Z]?|ZX[A-Z]?|ZY[A-Z]?|ZZ[A-Z]?"
    r")[0-9][0-9A-Z]{0,3}[A-Z]"
)
CALLSIGN_RE = re.compile(CALLSIGN_PATTERN)


def is_conforming(call):
    """True if the worked call is structurally valid.

    The base regex has no '/', so portable/slashed calls are post-processed here
    (the "second check"): a slashed call is accepted when any '/'-separated
    segment is itself a full valid call -- e.g. WB2GDZ/8, KT4Q/KL7, W1AW/4. A
    genuine typo (no segment validates) is still rejected.
    """
    if not call:
        return False
    if CALLSIGN_RE.fullmatch(call):
        return True
    if '/' in call:
        return any(CALLSIGN_RE.fullmatch(seg) for seg in call.split('/') if seg)
    return False


def suggest_o_to_zero(call):
    """For an O-for-0 typo, return the corrected call(s).

    Replaces each 'O' one at a time (not all at once -- a legit O in the suffix
    must survive) and keeps only the candidates that then conform. Returns a
    sorted list of valid corrections (usually exactly one), or [] if no single
    O->0 swap fixes it.
    """
    candidates = set()
    for i, ch in enumerate(call):
        if ch == 'O':
            cand = call[:i] + '0' + call[i + 1:]
            if is_conforming(cand):
                candidates.add(cand)
    return sorted(candidates)


def backup_database(db_path):
    """Copy db_path to db_path.<YYYYMMDD-HHMMSS>.bak and return the backup path."""
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_path = '%s.%s.bak' % (db_path, stamp)
    shutil.copy2(db_path, backup_path)
    return backup_path


def apply_fixes(db_path, fixes, make_backup):
    """Rewrite qso_log.callsign for the given fixes.

    fixes is a list of (qso_id, old_call, new_call). Each row is updated by its
    qso_id, so only the exact offending QSOs change. Idempotent: re-running after
    a fix finds nothing left to do (or re-fixes if TR4W re-synced the typo).
    """
    if make_backup:
        print('Backup   : %s' % backup_database(db_path))
    else:
        print('Backup   : SKIPPED (--no-backup)')

    db = sqlite3.connect(db_path)
    try:
        cursor = db.cursor()
        cursor.executemany('UPDATE qso_log SET callsign = ? WHERE qso_id = ?;',
                           [(new, qid) for (qid, _old, new) in fixes])
        db.commit()
    finally:
        db.close()
    print('Applied  : rewrote %d QSO(s) (O -> 0).' % len(fixes))


def band_name(band_id):
    titles = constants.Bands.BANDS_TITLE
    return titles[band_id] if 0 <= band_id < len(titles) else '?%d' % band_id


def mode_name(mode_id):
    modes = constants.Modes.MODES_LIST
    return modes[mode_id] if 0 <= mode_id < len(modes) else '?%d' % mode_id


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('database', nargs='?', default=None,
                        help='SQLite DB to inspect (default: DATABASE_FILENAME from INI)')
    parser.add_argument('--fix', action='store_true',
                        help='Rewrite unambiguous O-for-0 typos in this DB (backs up first)')
    parser.add_argument('--no-backup', action='store_true',
                        help='With --fix, skip making a timestamped backup')
    args = parser.parse_args()

    db_path = args.database or Config().DATABASE_FILENAME
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    cursor = db.cursor()
    cursor.execute(
        'SELECT q.timestamp, q.callsign, q.band_id, q.mode_id, '
        '       log_op.name AS logged_by, q.qso_id '
        'FROM qso_log q '
        'LEFT JOIN operator log_op ON log_op.id = q.operator_id '
        'ORDER BY UPPER(q.callsign), q.timestamp;')
    all_rows = cursor.fetchall()
    db.close()

    distinct_calls = {(r['callsign'] or '').upper() for r in all_rows}
    offenders = {}  # call -> list of rows
    for r in all_rows:
        call = (r['callsign'] or '').upper()
        if not is_conforming(call):
            offenders.setdefault(call, []).append(r)

    print('Database     : %s' % db_path)
    print('Worked QSOs  : %d   distinct calls: %d' % (len(all_rows), len(distinct_calls)))
    print('Rule         : callsign must match the ITU prefix-allocation pattern')
    print('-' * 70)

    if not offenders:
        print('OK -- every worked callsign conforms.')
        return 0

    def when(ts):
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    total_qsos = 0
    fixable = []      # (qso_id, old_call, new_call) for unambiguous O->0 swaps
    ambiguous = 0     # offending calls with no single conforming O->0 swap
    for call in sorted(offenders):
        hits = offenders[call]
        total_qsos += len(hits)
        fixes = suggest_o_to_zero(call)
        if len(fixes) == 1:
            note = '  -> likely O-for-0 typo, change to: %s' % fixes[0]
            for r in hits:
                fixable.append((r['qso_id'], call, fixes[0]))
        elif len(fixes) > 1:
            note = '  -> ambiguous O->0 (could be %s) -- manual' % ', '.join(fixes)
            ambiguous += 1
        else:
            note = '  (no O->0 fix conforms -- inspect manually)'
            ambiguous += 1
        label = call if call else '<empty>'
        print('\n!! %-12s %d QSO(s)%s' % (label, len(hits), note))
        for r in hits:
            print('     %s  %-4s %-5s  logged by %s'
                  % (when(r['timestamp']), band_name(r['band_id']),
                     mode_name(r['mode_id']), r['logged_by'] or '?'))
            print('       qso_id=%s' % r['qso_id'])

    print('-' * 70)
    print('Found %d non-conforming callsign(s) across %d QSO(s).'
          % (len(offenders), total_qsos))

    if args.fix:
        if fixable:
            apply_fixes(db_path, fixable, make_backup=not args.no_backup)
        else:
            print('Nothing to auto-fix (no unambiguous O->0 swaps).')
        if ambiguous:
            print('%d call(s) left unchanged for manual review.' % ambiguous)
        print('Remember to make the same fixes in TR4W (the Cabrillo source).')
    else:
        print('Fix the O-for-0 typos in TR4W and in this DB, then re-sync.')
        print('Or run with --fix to rewrite the unambiguous O->0 typos in this DB.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
