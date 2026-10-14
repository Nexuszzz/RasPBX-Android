from pathlib import Path
from android_app_shell import guest,push_asset
BASE=Path(__file__).resolve().parents[1]
push_asset(BASE/'android/guest-create-lab-agents.php')
print(guest('php /opt/raspbx-android/guest-create-lab-agents.php',timeout=45))
print(guest('timeout 180 /var/lib/asterisk/bin/retrieve_conf --json && asterisk -rx "core reload"',timeout=200))
