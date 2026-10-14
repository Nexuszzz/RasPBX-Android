"""Export the untouched RasPBX filesystem to a no-root Android prototype tarball."""
import hashlib
import io
import json
import stat
import tarfile
import time
from pathlib import Path
from image_reader import open_image

BASE=Path(__file__).resolve().parents[1]
dest=BASE/'runtime/android'
dest.mkdir(parents=True,exist_ok=True)
archive_path=dest/'raspbx-android-armhf.tar.gz'
source=BASE/'raspbx-04-04-2018.img'
excluded=('/boot/','/dev/','/proc/','/sys/','/run/','/tmp/','/root/',
    '/lib/modules/','/lib/firmware/','/usr/src/','/usr/include/',
    '/var/cache/apt/','/var/log/','/etc/ssh/ssh_host_')
patches={'/etc/ld.so.preload':b'# Raspberry Pi libarmmem disabled on Android\n',
    '/etc/fstab':b'# Android PRoot uses host filesystem bindings; no block mounts\n',
    '/etc/hostname':b'raspbx-android\n',
    '/etc/resolv.conf':b'nameserver 1.1.1.1\n'}
count=0
logical=0
started=time.monotonic()
disk,boot,root=open_image(source)
try:
    with tarfile.open(archive_path,'w:gz',compresslevel=3,format=tarfile.PAX_FORMAT) as archive:
        for name,item in root.walk():
            if any(name.startswith(prefix) for prefix in excluded):
                continue
            mode=item['mode']
            entry=tarfile.TarInfo(name.lstrip('/'))
            entry.uid=0; entry.gid=0; entry.mode=mode & 0o777; entry.mtime=item['mtime']
            if stat.S_ISDIR(mode):
                entry.type=tarfile.DIRTYPE
                archive.addfile(entry)
            elif stat.S_ISLNK(mode):
                entry.type=tarfile.SYMTYPE
                entry.linkname=root.contents(item['inode']).decode('utf-8','surrogateescape')
                archive.addfile(entry)
            elif stat.S_ISREG(mode):
                data=patches.get(name)
                if data is None:
                    data=root.contents(item['inode'],max_bytes=256*1024*1024)
                entry.size=len(data)
                archive.addfile(entry,io.BytesIO(data))
                logical+=len(data)
            else:
                continue
            count+=1
            if count % 10000==0:
                print('Exported',count,'paths;',round(logical/1024/1024),'MiB',flush=True)
        for name in ('dev','proc','sys','run','tmp','root','var/log','var/log/asterisk','opt/raspbx-android'):
            entry=tarfile.TarInfo(name)
            entry.type=tarfile.DIRTYPE; entry.mode=0o777 if name=='tmp' else 0o755
            archive.addfile(entry)
finally:
    disk.close()
with archive_path.open('rb') as handle:
    digest=hashlib.file_digest(handle,'sha256').hexdigest()
result=dict(source_image=source.name,source_sha256='72b9ceb816f6572b5bde107858f67a68d6a4c269469cdfa89de30a12b40efcff',
    archive=archive_path.name,sha256=digest,archive_bytes=archive_path.stat().st_size,
    entries=count,logical_bytes=logical,seconds=round(time.monotonic()-started,1),
    architecture='armhf',status='prototype; hardware validation required',excluded=list(excluded),
    patched_paths=list(patches))
(dest/'rootfs-manifest.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2),flush=True)
