"""Convert the supplied song and install it as both phone ring groups' hold music."""
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
FFPROBE=FFMPEG.with_name('ffprobe.exe')
(BASE/'analysis').mkdir(parents=True,exist_ok=True)
OUTPUT=BASE/'output/audio'
OUTPUT.mkdir(parents=True,exist_ok=True)
wav=OUTPUT/'dj-praktikum.wav'
ulaw=OUTPUT/'dj-praktikum.ulaw'
subprocess.run([str(FFMPEG),'-nostdin','-hide_banner','-loglevel','error','-y','-i',str(SOURCE),'-map','0:a:0','-vn','-map_metadata','-1','-ac','1','-ar','8000','-c:a','pcm_s16le',str(wav)],check=True,timeout=60)
subprocess.run([str(FFMPEG),'-nostdin','-hide_banner','-loglevel','error','-y','-i',str(wav),'-c:a','pcm_mulaw','-f','mulaw',str(ulaw)],check=True,timeout=60)
probe=json.loads(subprocess.check_output([str(FFPROBE),'-v','error','-show_entries','format=duration:stream=codec_name,sample_rate,channels','-of','json',str(wav)],text=True))
assert probe['streams'][0]['sample_rate']=='8000' and probe['streams'][0]['channels']==1
for path in [wav,ulaw,BASE/'android/guest-configure-hold-music.php']:push_asset(path)
result=guest('php /opt/raspbx-android/guest-configure-hold-music.php apply',timeout=100)
print(result,flush=True)
configuration=json.loads(result)
print(guest('timeout 180 /var/lib/asterisk/bin/retrieve_conf --json && asterisk -rx "core reload"',timeout=200),flush=True)
manifest={'source':str(SOURCE),'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'audio':probe,'configuration':configuration,'microphone_speaker_tested':False}
(BASE/'analysis/android-hold-music-install.json').write_text(json.dumps(manifest,indent=2))
print(guest('asterisk -rx "moh show classes"; asterisk -rx "moh show files"',timeout=30),flush=True)
