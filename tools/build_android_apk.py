"""Build the standalone RasPBX Android APK with the installed Windows SDK."""
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
sdk_value=os.environ.get('ANDROID_SDK_ROOT') or os.environ.get('ANDROID_HOME')
if not sdk_value:
    sdk_value=str(Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'Android/Sdk')
SDK=Path(sdk_value)
java_value=os.environ.get('JAVA_HOME')
if java_value:
    JAVA=Path(java_value)/'bin'
elif shutil.which('javac'):
    JAVA=Path(shutil.which('javac')).parent
else:
    candidate=Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Android/Android Studio/jbr/bin'
    if not (candidate/'javac.exe').is_file():
        raise SystemExit('Set JAVA_HOME to a JDK installation (JDK 17 or newer).')
    JAVA=candidate
BT=SDK/'build-tools/35.0.1'
ANDROID=SDK/'platforms/android-35/android.jar'
required=[ANDROID,BT/'aapt2.exe',BT/'lib/d8.jar',JAVA/'javac.exe',
    BASE/'runtime/android/raspbx-android-armhf.tar.gz']
required += [BASE/'runtime/android/native'/name for name in
    ['libproot.so','libproot-loader.so','libproot-loader32.so','libtalloc.so','libandroid-shmem.so']]
missing=[str(path) for path in required if not path.is_file()]
if missing:raise SystemExit('Missing build inputs; see README.md:\n'+'\n'.join(missing))
BUILD=BASE/'runtime/android/apk-build'
OUT=BASE/'output/android'
OUT.mkdir(parents=True,exist_ok=True)
BUILD.mkdir(parents=True,exist_ok=True)
classes=BUILD/'classes';classes.mkdir(exist_ok=True)
dex=BUILD/'dex';dex.mkdir(exist_ok=True)
def run(args):
    result=subprocess.run([str(a) for a in args],capture_output=True,text=True,encoding='utf-8',errors='replace')
    if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    if result.stderr:print(result.stderr[-1000:],flush=True)

sources=list((BASE/'android/app/src').rglob('*.java'))
run([JAVA/'javac.exe','-encoding','UTF-8','-source','8','-target','8','-classpath',ANDROID,'-d',classes,*sources])
run([JAVA/'java.exe','-cp',BT/'lib/d8.jar','com.android.tools.r8.D8','--min-api','26','--lib',ANDROID,'--output',dex,*classes.rglob('*.class')])
base_apk=BUILD/'base.apk'
run([BT/'aapt2.exe','link','-I',ANDROID,'--manifest',BASE/'android/app/AndroidManifest.xml','--min-sdk-version','26','--target-sdk-version','28','-o',base_apk])
unsigned=BUILD/'unsigned.apk'
shutil.copyfile(base_apk,unsigned)
with zipfile.ZipFile(unsigned,'a',allowZip64=True) as archive:
    archive.write(dex/'classes.dex','classes.dex',compress_type=zipfile.ZIP_DEFLATED)
    archive.write(BASE/'runtime/android/raspbx-android-armhf.tar.gz','assets/raspbx-android-armhf.tar.gz',compress_type=zipfile.ZIP_STORED)
    for file in (BASE/'android').glob('guest-*'):
        archive.write(file,'assets/'+file.name,compress_type=zipfile.ZIP_DEFLATED)
    for file in (BASE/'runtime/android/native').glob('*.so'):
        archive.write(file,'lib/arm64-v8a/'+file.name,compress_type=zipfile.ZIP_STORED)
    archive.write(BASE/'runtime/android/rootfs-manifest.json','assets/rootfs-manifest.json')
    archive.write(BASE/'runtime/android/native/provenance.json','assets/native-provenance.json')
    archive.write(BASE/'android/SOURCES.txt','assets/SOURCES.txt')
aligned=BUILD/'aligned.apk'
run([BT/'zipalign.exe','-f','-p','4',unsigned,aligned])
private=BASE/'runtime/private'
private.mkdir(parents=True,exist_ok=True)
key=private/'android-pbx-keystore.p12';password=private/'android-pbx-keystore-password.txt'
if not key.exists():
    password.write_text(secrets.token_hex(24))
    run([JAVA/'keytool.exe','-genkeypair','-keystore',key,'-storetype','PKCS12','-storepass:file',password,
        '-alias','raspbx-android','-keyalg','RSA','-keysize','3072','-validity','3650','-dname','CN=RasPBX Android Local Lab'])
final=OUT/'RasPBX-Android-Lab.apk'
run([BT/'apksigner.bat','sign','--ks',key,'--ks-key-alias','raspbx-android','--ks-pass','file:'+str(password),'--out',final,aligned])
run([BT/'apksigner.bat','verify','--verbose',final])
run([BT/'zipalign.exe','-c','4',final])
with final.open('rb') as handle:digest=hashlib.file_digest(handle,'sha256').hexdigest()
metadata=dict(apk=str(final),sha256=digest,bytes=final.stat().st_size,package='com.naufal.raspbx',
    abi='arm64-v8a host with ARM32 hardware support',min_sdk=26,target_sdk=28,
    includes=['original FreePBX 14','Asterisk 13.20.0','MariaDB 10.1.23','PHP 5.6.33','PRoot Android runtime'],
    requires_root=False,requires_termux=False,requires_qemu=False,
    validation='signature, alignment and Java compilation passed; see analysis/android-validation.json for actual device results')
manifest=ET.parse(BASE/'android/app/AndroidManifest.xml').getroot()
metadata['version_name']=manifest.get('{http://schemas.android.com/apk/res/android}versionName')
metadata['version_code']=int(manifest.get('{http://schemas.android.com/apk/res/android}versionCode'))
(OUT/'build-manifest.json').write_text(json.dumps(metadata,indent=2))
print(json.dumps(metadata,indent=2),flush=True)
