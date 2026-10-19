#!/bin/sh
set -eu
(setsid sh -c '
  while :; do
    for name in a b; do
      if [ -f "/work/inbox/$name.txt" ] && [ ! -f "/work/output/$name.txt" ]; then
        cp "/work/inbox/$name.txt" "/work/output/$name.txt"
      fi
    done
    sleep 0.2
  done
' </dev/null >/tmp/window-oracle.out 2>/tmp/window-oracle.err &)
