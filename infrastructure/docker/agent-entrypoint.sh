#!/bin/sh
# Starts a virtual display (so pairing can open a *headed* browser) and, if
# enabled, a password-protected noVNC viewer, then runs the agent.
set -eu

Xvfb :99 -screen 0 1366x900x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &

# Wait for the display socket: a headed Chromium (pairing) started before Xvfb
# is ready fails with "Missing X server or $DISPLAY".
i=0
while [ ! -S /tmp/.X11-unix/X99 ]; do
  i=$((i + 1))
  if [ "$i" -gt 50 ]; then
    echo "Xvfb did not start:" >&2; cat /tmp/xvfb.log >&2; exit 1
  fi
  sleep 0.2
done

if [ "${PAIRING_VNC_ENABLED:-false}" = "true" ]; then
  if [ -z "${PAIRING_VNC_PASSWORD:-}" ]; then
    echo "PAIRING_VNC_ENABLED=true requires PAIRING_VNC_PASSWORD" >&2
    exit 1
  fi
  mkdir -p "$HOME/.vnc"
  x11vnc -storepasswd "$PAIRING_VNC_PASSWORD" "$HOME/.vnc/passwd" >/dev/null
  x11vnc -display :99 -forever -shared -rfbauth "$HOME/.vnc/passwd" -rfbport 5900 -localhost -quiet >/tmp/x11vnc.log 2>&1 &
  websockify --web /usr/share/novnc 6080 localhost:5900 >/tmp/novnc.log 2>&1 &
  echo "noVNC viewer on :6080 (vnc.html) for manual pairing" >&2
fi

exec python -m agent "$@"
