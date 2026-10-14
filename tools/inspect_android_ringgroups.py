"""Read the installed FreePBX module and current lab state without changing it."""
import json
from pathlib import Path
from android_shell import adb
from android_app_shell import guest, push_asset, TASK, PACKAGE

BASE = Path(__file__).resolve().parents[1]
source = BASE / 'runtime/freepbx-api-source/ringgroups'
source.mkdir(parents=True, exist_ok=True)
for name in ['Ringgroups.class.php', 'functions.inc.php', 'views/simple_form.php', 'views/advanced_form.php']:
    text = adb('shell', f'run-as {PACKAGE} cat {TASK}/rootfs/var/www/html/admin/modules/ringgroups/{name}')
    dest = source / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding='utf-8')

php = BASE / 'runtime/private/android/inspect-ringgroups.php'
php.parent.mkdir(parents=True,exist_ok=True)
php.write_text('''<?php
include '/etc/freepbx.conf';
$pbx=FreePBX::create();
$devices=array();
foreach(array('201','202','203','257','258') as $id){
 $d=$pbx->Core->getDevice($id);
 $devices[$id]=$d?array('id'=>$d['id'],'description'=>$d['description'],'tech'=>$d['tech']):null;
}
$q=$pbx->Database->query('SELECT grpnum,strategy,grptime,grplist,ringing,postdest,description FROM ringgroups');
echo json_encode(array('devices'=>$devices,'ringgroups'=>$q->fetchAll(PDO::FETCH_ASSOC)),JSON_PRETTY_PRINT).PHP_EOL;
''', encoding='utf-8')
push_asset(php)
print(guest('php /opt/raspbx-android/inspect-ringgroups.php', timeout=40))
