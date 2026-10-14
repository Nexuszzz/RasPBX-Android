"""Install the user's second song and a persistent FreePBX ACD queue on the phone."""
import argparse
import shutil
import hashlib
import json
import subprocess
from pathlib import Path
from android_app_shell import guest,push_asset

BASE=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('music',type=Path,help='Path to your MP3/WAV file')
args=parser.parse_args()
SOURCE=args.music.resolve()
FFMPEG=Path(shutil.which('ffmpeg') or 'ffmpeg.exe')
(BASE/'analysis').mkdir(parents=True,exist_ok=True)
OUTPUT=BASE/'output/audio';OUTPUT.mkdir(parents=True,exist_ok=True)
wav=OUTPUT/'acd-menungso.wav';ulaw=OUTPUT/'acd-menungso.ulaw'
subprocess.run([str(FFMPEG),'-nostdin','-hide_banner','-loglevel','error','-y','-i',str(SOURCE),'-map','0:a:0','-vn','-map_metadata','-1','-ac','1','-ar','8000','-c:a','pcm_s16le',str(wav)],check=True,timeout=60)
subprocess.run([str(FFMPEG),'-nostdin','-hide_banner','-loglevel','error','-y','-i',str(wav),'-c:a','pcm_mulaw','-f','mulaw',str(ulaw)],check=True,timeout=60)
for path in [wav,ulaw,BASE/'android/guest-configure-acd.php']:push_asset(path)
raw=guest('php /opt/raspbx-android/guest-configure-acd.php apply',timeout=100)
print(raw,flush=True)
configuration=json.loads(raw)
print(guest('timeout 180 /var/lib/asterisk/bin/retrieve_conf --json && asterisk -rx "core reload"',timeout=200),flush=True)
manifest={'source':str(SOURCE),'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'wav_sha256':hashlib.sha256(wav.read_bytes()).hexdigest(),'configuration':configuration,'microphone_speaker_tested':False}
(BASE/'analysis/android-acd-install.json').write_text(json.dumps(manifest,indent=2))
print(guest('asterisk -rx "queue show 259"; asterisk -rx "dialplan show 259@ext-queues"; asterisk -rx "moh show classes"',timeout=35),flush=True)
