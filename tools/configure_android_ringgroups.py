"""Back up and add the user's phone Ring Group practicum, preserving other PBX data."""
import json
from pathlib import Path
from android_shell import adb
from android_app_shell import guest, push_asset, TASK, PACKAGE

BASE=Path(__file__).resolve().parents[1]
push_asset(BASE/'android/guest-configure-ringgroups.php')
print(guest('php /opt/raspbx-android/guest-configure-ringgroups.php',timeout=100),flush=True)
print(guest('timeout 180 /var/lib/asterisk/bin/retrieve_conf --json && asterisk -rx "core reload"',timeout=200),flush=True)
raw=adb('shell',f'run-as {PACKAGE} cat {TASK}/rootfs/opt/raspbx-android/extensions.json')
accounts=json.loads(raw)
(BASE/'runtime/private/android').mkdir(parents=True,exist_ok=True)
(BASE/'runtime/private/android/extensions.json').write_text(json.dumps(accounts,indent=2))
print('Private local account file synchronized; passwords omitted from console.',flush=True)
print(guest('asterisk -rx "pjsip show endpoint 203"; asterisk -rx "dialplan show 257@ext-group"; asterisk -rx "dialplan show 258@ext-group"; asterisk -rx "moh show classes"',timeout=40),flush=True)
