#!/bin/sh
# Isolated test desktop: a private X server (Xvfb :99) with its OWN D-Bus
# session AND its own XDG_RUNTIME_DIR.
#
# The XDG_RUNTIME_DIR override is NOT optional. at-spi-bus-launcher puts its
# socket at $XDG_RUNTIME_DIR/at-spi/bus_0 — a fixed per-user path that does NOT
# vary with DBUS_SESSION_BUS_ADDRESS. Without the override, a private launcher
# shares that path with the real desktop session and tearing the test env down
# DELETES THE REAL SESSION'S a11y socket, breaking accessibility for every
# already-running app until it is restarted. (Learned the hard way.)
#
#   . test/env.sh start     # bring it up, exports DISPLAY + DBUS_SESSION_BUS_ADDRESS
#   . test/env.sh stop      # tear it down
#
# Must be SOURCED (it exports env vars), not executed.

LU_DISPLAY=":99"
LU_RUN="/tmp/linux-use-testenv"
LU_XDG="$LU_RUN/xdg"

lu_env_start() {
	mkdir -p "$LU_RUN" "$LU_XDG"
	chmod 700 "$LU_XDG"
	XDG_RUNTIME_DIR="$LU_XDG"
	export XDG_RUNTIME_DIR
	if [ ! -f "$LU_RUN/xvfb.pid" ] || ! kill -0 "$(cat "$LU_RUN/xvfb.pid" 2>/dev/null)" 2>/dev/null; then
		Xvfb "$LU_DISPLAY" -screen 0 1280x900x24 -nolisten tcp >"$LU_RUN/xvfb.log" 2>&1 &
		echo $! > "$LU_RUN/xvfb.pid"
		sleep 1
	fi
	if [ ! -f "$LU_RUN/dbus.addr" ] || ! kill -0 "$(cat "$LU_RUN/dbus.pid" 2>/dev/null)" 2>/dev/null; then
		dbus-daemon --session --fork --print-address=3 --print-pid=4 \
			3>"$LU_RUN/dbus.addr" 4>"$LU_RUN/dbus.pid"
		sleep 1
	fi
	DISPLAY="$LU_DISPLAY"
	DBUS_SESSION_BUS_ADDRESS="$(cat "$LU_RUN/dbus.addr")"
	XDG_RUNTIME_DIR="$LU_XDG"
	export XDG_RUNTIME_DIR
	unset WAYLAND_DISPLAY
	export DISPLAY DBUS_SESSION_BUS_ADDRESS
	echo "test desktop up: DISPLAY=$DISPLAY"
	echo "                 DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS"
	echo "                 XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR (private a11y socket)"
}

lu_env_stop() {
	for f in "$LU_RUN"/*.pid; do
		[ -f "$f" ] || continue
		kill "$(cat "$f")" 2>/dev/null
		rm -f "$f"
	done
	# Kill only launchers whose socket lives under OUR private runtime dir.
	for pid in $(pgrep -f "libexec/at-spi" 2>/dev/null); do
		if tr '\0' ' ' < "/proc/$pid/environ" 2>/dev/null | grep -q "XDG_RUNTIME_DIR=$LU_XDG"; then
			kill "$pid" 2>/dev/null
		fi
	done
	rm -f "$LU_RUN/dbus.addr"
	echo "test desktop down"
}

case "$1" in
	start) lu_env_start ;;
	stop)  lu_env_stop ;;
	*)     echo "usage: . test/env.sh start|stop" ;;
esac
