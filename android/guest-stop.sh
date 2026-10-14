#!/bin/bash
mkdir -p /run/mysqld
# The UI and supervisor may request shutdown at the same time. Serialize them
# so MariaDB does not receive a second SIGTERM while flushing its buffer pool.
exec 9>/run/mysqld/android-stop.lock
flock -x -w 90 9 || exit 1
asterisk -rx 'core stop gracefully' 2>/dev/null || true
apache2ctl -k graceful-stop 2>/dev/null || true
mysqladmin --socket=/run/mysqld/mysqld.sock shutdown 2>/dev/null || true
# Android's real UID cannot authenticate as OS root with MariaDB unix_socket.
# SIGTERM is MariaDB's normal, clean shutdown path when mysqladmin cannot log in.
if [ -f /run/mysqld/mysqld.pid ]; then
    taskMysql=$(cat /run/mysqld/mysqld.pid)
    case "$taskMysql" in ''|*[!0-9]*) exit 1;; esac
    if [ -r "/proc/$taskMysql/cmdline" ] && tr '\000' ' ' < "/proc/$taskMysql/cmdline" | grep -Eq '(^|[ /])mysqld([ ]|$)'; then
        if mkdir /run/mysqld/android-shutdown-lock 2>/dev/null; then
            kill -TERM "$taskMysql" 2>/dev/null || true
        fi
        for taskWait in $(seq 1 60); do
            kill -0 "$taskMysql" 2>/dev/null || break
            sleep 1
        done
        kill -0 "$taskMysql" 2>/dev/null || rmdir /run/mysqld/android-shutdown-lock 2>/dev/null || true
    fi
fi
