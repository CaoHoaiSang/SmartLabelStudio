#!/usr/bin/env bash
# Run inside a dedicated xvfb-run display, never the operator's desktop.
set -euo pipefail

: "${DISPLAY:?Run this script through xvfb-run}"
openbox --sm-disable &
ci_wm_pid=$!
trap 'kill "$ci_wm_pid" 2>/dev/null || true; wait "$ci_wm_pid" 2>/dev/null || true' EXIT

# Xvfb provides a screen but does not implement transient-window stacking.
# Wait for EWMH registration rather than racing GUI tests against WM startup.
ci_wm_ready=false
for ((attempt=0; attempt<50; attempt++)); do
    if ! kill -0 "$ci_wm_pid" 2>/dev/null; then
        echo "Window manager exited before tests could start." >&2
        exit 1
    fi
    if xprop -root _NET_SUPPORTING_WM_CHECK | grep -Eq 'window id # 0x[1-9a-fA-F][0-9a-fA-F]*'; then
        ci_wm_ready=true
        break
    fi
    sleep 0.1
done
if [[ "$ci_wm_ready" != true ]]; then
    echo "Window manager did not register within 5 seconds; GUI tests cannot be trusted." >&2
    exit 1
fi

python -m unittest discover -s tests -v
