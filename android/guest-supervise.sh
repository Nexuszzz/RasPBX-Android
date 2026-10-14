#!/bin/bash
set -euo pipefail
umask 022
taskDir=/opt/raspbx-android
mkdir -p /run/mysqld /run/asterisk /run/apache2 /run/lock/apache2 /var/log/asterisk /var/log/apache2
echo 'Menyiapkan layanan...' > "$taskDir/startup-state"
if [ -S /run/asterisk/asterisk.ctl ] && asterisk -rx 'core show uptime' >/dev/null 2>&1; then
    echo 'RasPBX is already running'; exit 0
fi
printf 'Listen 0.0.0.0:8088\n' > /etc/apache2/ports.conf
sed -i -e 's@<VirtualHost \*:80>@<VirtualHost *:8088>@' -e 's@<VirtualHost 127.0.0.1:8088>@<VirtualHost *:8088>@' /etc/apache2/sites-enabled/000-default.conf
cat > /etc/mysql/mariadb.conf.d/99-android.cnf <<'MYSQL'
[mysqld]
skip-networking
socket=/run/mysqld/mysqld.sock
pid-file=/run/mysqld/mysqld.pid
innodb_buffer_pool_size=32M
max_connections=15
innodb_use_native_aio=0
MYSQL
chmod 644 /etc/mysql/mariadb.conf.d/99-android.cnf
cat > /etc/apache2/conf-enabled/android-pbx.conf <<'APACHE'
ServerName localhost
Mutex fcntl:/run/lock/apache2 default
<IfModule mpm_prefork_module>
StartServers 1
MinSpareServers 1
MaxSpareServers 2
MaxRequestWorkers 4
MaxConnectionsPerChild 200
</IfModule>
APACHE
if [ ! -f "$taskDir/manager-secret" ]; then
    openssl rand -hex 24 > "$taskDir/manager-secret"
    chmod 600 "$taskDir/manager-secret"
fi
taskSecret=$(cat "$taskDir/manager-secret")
cat > /etc/asterisk/manager_custom.conf <<AMI
[codex_android]
secret = $taskSecret
deny = 0.0.0.0/0.0.0.0
permit = 127.0.0.1/255.255.255.255
read = system,call,reporting
write = system,reporting
AMI
chmod 640 /etc/asterisk/manager_custom.conf
# Android does not expose network hardware addresses to this application.
if [ ! -f "$taskDir/entity-id" ]; then
    php -r '$bytes=openssl_random_pseudo_bytes(6); $bytes[0]=chr((ord($bytes[0])|2)&254); echo implode(":",str_split(bin2hex($bytes),2)),"\n";' > "$taskDir/entity-id"
fi
sed -i '/^entityid[[:space:]]*=/d' /etc/asterisk/asterisk.conf
sed -i "/^\[options\]/a entityid=$(cat "$taskDir/entity-id")" /etc/asterisk/asterisk.conf
function wait_asterisk() {
    for taskWait in $(seq 1 90); do
        if asterisk -rx 'core show help core' 2>/dev/null | grep -q '^core waitfullybooted'; then
            timeout 90 asterisk -rx 'core waitfullybooted'
            return $?
        fi
        sleep 1
    done
    echo 'Asterisk gagal menyelesaikan startup' >&2
    return 1
}
function cleanup() {
    taskResult=$?
    if [ "$taskResult" -ne 0 ]; then
        echo "Gagal memulai layanan (kode $taskResult). Buka Log." > "$taskDir/startup-state"
    fi
    /bin/bash "$taskDir/guest-stop.sh" || true
}
trap cleanup EXIT
trap 'exit 0' TERM INT
echo 'Memulai database...' > "$taskDir/startup-state"
rmdir /run/mysqld/android-shutdown-lock 2>/dev/null || true
mysqld --user=mysql >> "$taskDir/mysql.log" 2>&1 &
for taskWait in $(seq 1 60); do
    mysqladmin --socket=/run/mysqld/mysqld.sock ping >/dev/null 2>&1 && break
    sleep 1
done
mysqladmin --socket=/run/mysqld/mysqld.sock ping >/dev/null 2>&1
echo 'Database siap'
echo 'Database aktif. Memulai Asterisk...' > "$taskDir/startup-state"
asterisk -f -U asterisk -G asterisk >> "$taskDir/asterisk-console.log" 2>&1 &
taskAsterisk=$!
wait_asterisk
echo 'Memuat konfigurasi extension...' > "$taskDir/startup-state"
php "$taskDir/guest-setup.php"
# fwconsole on this release can return success after a retrieve_conf failure.
timeout 180 /var/lib/asterisk/bin/retrieve_conf --json
for taskExtension in $(php -r '$a=json_decode(file_get_contents("/opt/raspbx-android/extensions.json"),true);foreach($a as $e){if(!preg_match("/^[0-9]+$/",$e["extension"]))exit(1);echo $e["extension"]," ";}'); do
    grep -q "^\[$taskExtension\]" /etc/asterisk/pjsip.endpoint.conf
done
# PJSIP transport changes require an Asterisk restart.
asterisk -rx 'core stop gracefully'
for taskWait in $(seq 1 60); do
    ! kill -0 "$taskAsterisk" 2>/dev/null && break
    sleep 1
done
if kill -0 "$taskAsterisk" 2>/dev/null; then echo 'Asterisk tidak selesai dihentikan' >&2; exit 1; fi
asterisk -f -U asterisk -G asterisk >> "$taskDir/asterisk-console.log" 2>&1 &
wait_asterisk
chmod 755 /var/www/html/admin/modules/dashboard/scheduler.php /var/www/html/admin/modules/dashboard/netmon.php
asterisk -rx 'core show uptime'
mysqladmin --socket=/run/mysqld/mysqld.sock ping >/dev/null 2>&1
echo 'Memulai tampilan FreePBX...' > "$taskDir/startup-state"
apache2ctl -D FOREGROUND >> "$taskDir/apache.log" 2>&1 &
taskApache=$!
sleep 2
kill -0 "$taskApache"
echo READY > "$taskDir/startup-state"
echo 'PBX_READY: Android FreePBX http://127.0.0.1:8088/admin/; SIP UDP 15060; RTP UDP 20000-20031'
while asterisk -rx 'core show uptime' >/dev/null 2>&1; do
    kill -0 "$taskApache"
    php "$taskDir/guest-collect.php" >> "$taskDir/collector.log" 2>&1 || true
    sleep 30
done
echo 'Asterisk stopped; shutting down remaining services'
