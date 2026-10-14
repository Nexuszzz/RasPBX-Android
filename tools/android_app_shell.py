"""Maintenance commands scoped to our debug APK on the authorized Redmi."""
import argparse
import base64
import hashlib
import shlex
import subprocess
from pathlib import Path
from android_shell import adb, ADB, SERIAL, _command

PACKAGE = 'com.naufal.raspbx'
TASK = '/data/user/0/' + PACKAGE + '/files/raspbx'

def guest(command, timeout=120, detached=False):
    apk = adb('shell', 'pm path ' + PACKAGE).strip().removeprefix('package:')
    native = str(Path(apk).parent).replace('\\', '/') + '/lib/arm64'
    env = {'LD_LIBRARY_PATH': native, 'PROOT_TMP_DIR': TASK+'/proot-tmp',
           'PROOT_LOADER': native+'/libproot-loader.so',
           'PROOT_LOADER_32': native+'/libproot-loader32.so', 'PROOT_NO_SECCOMP': '1'}
    argv = [native+'/libproot.so', '--link2symlink', '--kill-on-exit', '--sysvipc', '-0',
            '-r', TASK+'/rootfs', '-b', '/dev', '-b', '/proc', '-b', '/sys',
            '-b', TASK+'/shm:/dev/shm', '-b', TASK+'/tmp:/tmp', '-w', '/root',
            '/usr/bin/env', '-i', 'HOME=/root',
            'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
            'TERM=xterm', 'LANG=C', '/bin/bash', '-c', command]
    assignments = ' '.join(key+'='+shlex.quote(value) for key,value in env.items())
    if detached:
        inner = assignments+' nohup '+shlex.join(argv)+' > '+shlex.quote(TASK+'/maintenance.log')+' 2>&1 < /dev/null & echo APK_MAINTENANCE_STARTED'
    else:
        inner = assignments+' exec '+shlex.join(argv)
    return adb('shell', shlex.join(['run-as', PACKAGE, 'sh', '-c', inner]), timeout=timeout)

def push_asset(path):
    source = Path(path)
    destination = TASK+'/rootfs/opt/raspbx-android/'+source.name
    command = shlex.join(['run-as', PACKAGE, 'sh', '-c', 'base64 -d > '+shlex.quote(destination)])
    # Encode stdin because this Windows adb build truncates raw input at Ctrl-Z.
    # Decode inside the application's private directory, then check the checksum.
    data = source.read_bytes()
    result = subprocess.run(_command('shell', '-T', command),
                            input=base64.b64encode(data), capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace'))
    remote_hash=adb('shell',shlex.join(['run-as',PACKAGE,'sha256sum',destination])).split()[0]
    if remote_hash!=hashlib.sha256(data).hexdigest():
        raise RuntimeError('Uploaded asset checksum mismatch: '+source.name)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command')
    parser.add_argument('--timeout', type=int, default=120)
    parser.add_argument('--push', action='store_true')
    parser.add_argument('--detach', action='store_true')
    args = parser.parse_args()
    if args.push:
        push_asset(args.command)
        print('Updated APK guest asset: '+Path(args.command).name)
    else:
        print(guest(args.command, args.timeout, args.detach))
