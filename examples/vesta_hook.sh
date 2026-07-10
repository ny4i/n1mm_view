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

# Third-line QSO tally, passed as a single "QSOs:NNN" token (no space) on
# purpose: the board greedy-wraps/centers on whitespace, so keeping the
# colon+number as one word makes it drop to its own line instead of splitting
# "QSOs:" from the number. Operator change shows THAT operator's own total;
# a new multiplier shows the site-wide total.
case "$EVENT" in
  operator_change)
    "$VESTA" New Operator "$N1MMV_CURRENT_OPERATOR" "QSOs:${N1MMV_OPERATOR_QSO_COUNT}"
    ;;
  new_multiplier)
    "$VESTA" New Multiplier Zone "$N1MMV_NEW_MULTIPLIER" "QSOs:${N1MMV_QSO_COUNT}"
    ;;
  *)
    # Not an event we post to the board; ignore quietly.
    ;;
esac
