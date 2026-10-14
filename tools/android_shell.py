"""ADB transport for the developer-selected debug Android device."""
import os
import shutil
import subprocess
import sys
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')
sdk=os.environ.get('ANDROID_SDK_ROOT') or os.environ.get('ANDROID_HOME')
if not sdk:sdk=str(Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'Android/Sdk')
candidate=Path(sdk)/'platform-tools/adb.exe'
ADB=Path(os.environ.get('ADB_PATH') or (str(candidate) if candidate.is_file() else shutil.which('adb') or 'adb'))
SERIAL=os.environ.get('ANDROID_SERIAL','')
def _command(*args):return [str(ADB)]+(['-s',SERIAL] if SERIAL else [])+list(args)
def adb(*args,timeout=180):
    result=subprocess.run(_command(*args),capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
    if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    return result.stdout+result.stderr
