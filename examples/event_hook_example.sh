#!/bin/bash
#
# Example n1mm_view event hook.
#
# Wire it up in n1mm_view.ini:
#   [HOOKS]
#   NEW_MULTIPLIER_SCRIPT = /home/pi/n1mm_view/examples/event_hook_example.sh
#   OPERATOR_CHANGE_SCRIPT = /home/pi/n1mm_view/examples/event_hook_example.sh
#   BAND_CHANGE_SCRIPT = /home/pi/n1mm_view/examples/event_hook_example.sh
#
# Make it executable first:
#   chmod +x /home/pi/n1mm_view/examples/event_hook_example.sh
#
# The collector runs this WITHOUT a shell, so every field arrives as an
# N1MMV_* environment variable (never interpolated into a command line). The
# event name is also passed as $1. Always quote your variables and never eval
# them -- treat them as untrusted text.
#
# See the [HOOKS] section of n1mm_view.ini.sample for the full variable list.

set -euo pipefail

EVENT="${1:-${N1MMV_EVENT:-unknown}}"
LOG="${HOME}/n1mm_view_hooks.log"

# Build a human-readable message per event type.
case "$EVENT" in
  new_multiplier)
    MSG="NEW MULT: ${N1MMV_MULT_NAME} ${N1MMV_NEW_MULTIPLIER} on ${N1MMV_BAND} (${N1MMV_NEW_CALL}) -- ${N1MMV_MULT_COUNT} total, op ${N1MMV_CURRENT_OPERATOR}"
    ;;
  operator_change)
    MSG="OP CHANGE at ${N1MMV_STATION}: ${N1MMV_PREVIOUS_OPERATOR} -> ${N1MMV_CURRENT_OPERATOR}"
    ;;
  band_change)
    MSG="BAND CHANGE at ${N1MMV_STATION} (${N1MMV_CURRENT_OPERATOR}): ${N1MMV_PREVIOUS_BAND} -> ${N1MMV_BAND}"
    ;;
  *)
    MSG="Unhandled event: ${EVENT}"
    ;;
esac

# 1) Log it (handy for testing that the hook fires).
printf '%s  %s\n' "$(date -u '+%Y-%m-%d %H:%M:%SZ')" "$MSG" >> "$LOG"

# 2) Do something with it. Replace this with your VersaBoard call, e.g.:
#      "${HOME}/projects/versa/send.py" --message "$MSG"
# The message is already assembled from the (untrusted-but-inert) env values.
#
# Example placeholder -- only acts on the new-multiplier event:
# if [ "$EVENT" = "new_multiplier" ]; then
#     "${HOME}/projects/versa/send.py" --message "$MSG"
# fi

exit 0
