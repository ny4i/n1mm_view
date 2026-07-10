#!/bin/bash
#
# n1mm_view -> Vestaboard hook.
#
# Wire the SAME script to both events in n1mm_view.ini:
#   [HOOKS]
#   OPERATOR_CHANGE_SCRIPT = /home/pi/n1mm_view/examples/vesta_hook.sh
#   NEW_MULTIPLIER_SCRIPT  = /home/pi/n1mm_view/examples/vesta_hook.sh
#
# Then make it executable:
#   chmod +x /home/pi/n1mm_view/examples/vesta_hook.sh
#
# The collector runs this WITHOUT a shell and passes the event name as $1,
# with all event data in N1MMV_* environment variables. Variables are quoted
# below so an odd operator/mult value stays a single argument to vesta.

set -uo pipefail

VESTA=/home/pi/vesta/vesta
EVENT="${1:-${N1MMV_EVENT:-}}"

# Running QSO total for the spare third line. It's passed as a single
# "QSOs:NNN" token (no space) on purpose: the board greedy-wraps and centers
# on whitespace, and keeping the colon+number as one word makes it drop to its
# own line rather than splitting "QSOs:" from the number.
QSOS="QSOs:${N1MMV_QSO_COUNT}"

case "$EVENT" in
  operator_change)
    "$VESTA" New Operator "$N1MMV_CURRENT_OPERATOR" "$QSOS"
    ;;
  new_multiplier)
    "$VESTA" New Multiplier Zone "$N1MMV_NEW_MULTIPLIER" "$QSOS"
    ;;
  *)
    # Not an event we post to the board; ignore quietly.
    ;;
esac
