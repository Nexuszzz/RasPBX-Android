"""Package official Termux PRoot libraries for a standalone Android APK."""
import hashlib
import gzip
import io
import json
import lzma
import re
import struct
import tarfile
import urllib.request
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
DEST=BASE/'runtime/android/native'
DEST.mkdir(parents=True,exist_ok=True)
REPO='https://packages.termux.dev/apt/termux-main/'
def fetch(url):
    with urllib.request.urlopen(url,timeout=60) as response:
        return response.read()
provenance=DEST/'provenance.json'
if not provenance.is_file():
    raise SystemExit('Missing runtime/android/native/provenance.json')
records=json.loads(provenance.read_text(encoding='utf-8'))
packages={}
for record in records:
    if not record['url'].startswith(REPO):raise ValueError('Unexpected native package repository')
    packages[record['package']]={'Package':record['package'],'Version':record['version'],
        'Filename':record['url'][len(REPO):],'SHA256':record['sha256'],'Depends':record.get('depends')}

def deb_data(raw):
    at=8
    if raw[:8]!=b'!<arch>\n': raise ValueError('Invalid Debian archive')
    while at+60<=len(raw):
        header=raw[at:at+60]; size=int(header[48:58].strip()); name=header[:16].decode().strip().rstrip('/')
        data=raw[at+60:at+60+size]
        if name.startswith('data.tar'):
            if name.endswith('.zst'):
                import backports.zstd
                data=backports.zstd.decompress(data)
            return tarfile.open(fileobj=io.BytesIO(data),mode='r:*')
        at+=60+size+(size%2)
    raise ValueError('Missing data archive')

metadata=[]
native_files={}
for name in ('proot','libtalloc','libandroid-shmem'):
    info=packages[name]
    data=fetch(REPO+info['Filename'])
    digest=hashlib.sha256(data).hexdigest()
    if digest!=info['SHA256']:raise RuntimeError('Repository SHA256 mismatch: '+name)
    (DEST/(name+'.deb')).write_bytes(data)
    with deb_data(data) as archive:
        for item in archive:
            if item.isfile() and ('/bin/proot' in item.name or '/libexec/proot/' in item.name or re.search(r'/lib/lib(?:talloc|android-shmem)\.so',item.name)):
                payload=archive.extractfile(item).read()
                native_files[Path(item.name).name]=payload
    metadata.append(dict(package=name,version=info['Version'],url=REPO+info['Filename'],sha256=digest,depends=info.get('Depends')))
print('Official native files:',[(n,len(data)) for n,data in native_files.items()],flush=True)
renames={}
for name in native_files:
    if name=='proot':out='libproot.so'
    elif name=='loader':out='libproot-loader.so'
    elif name=='loader32':out='libproot-loader32.so'
    elif name.startswith('libtalloc.so'):out='libtalloc.so'
    else:out=name if name.endswith('.so') else name.split('.so')[0]+'.so'
    renames[name]=out
for name,data in native_files.items():
    data=data.replace(b'libtalloc.so.2\0',b'libtalloc.so\0\0\0')
    # Android extracts JNI filenames lib*.so. Keep ELF offsets intact while
    # replacing the longer versioned library basename in its string table.
    for original,target in renames.items():
        if original!=target and original.startswith('lib'):
            old=original.encode()+b'\0';new=target.encode()+b'\0'
            if len(new)<=len(old):data=data.replace(old,new+b'\0'*(len(old)-len(new)))
    (DEST/renames[name]).write_bytes(data)
(DEST/'provenance.json').write_text(json.dumps(metadata,indent=2))
print('APK filenames:',sorted(set(renames.values())),flush=True)
