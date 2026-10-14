<?php
// Install the user's hold music through this phone's FreePBX module APIs.
include '/etc/freepbx.conf';
$pbx=FreePBX::create();
$category='praktikum_dj';
$action=isset($argv[1])?$argv[1]:'apply';

if($action==='test-add' || $action==='test-delete'){
 $profile=json_decode(file_get_contents('/opt/raspbx-android/music-test-account.json'),true);
 $id=(string)$profile['extension'];$name='Codex MoH validation '.$id;
 $device=$pbx->Core->getDevice($id);
 if($device && $device['description']!==$name)throw new Exception('Test extension collision');
 if($action==='test-add'){
  if($device || $pbx->Core->getUser($id))throw new Exception('Test number is already in use');
  $pbx->Core->addUser($id,$pbx->Core->generateDefaultUserSettings($id,$name));
  $flag=2;$settings=$pbx->Core->generateDefaultDeviceSettings('pjsip',$id,$name,$flag);
  foreach(array('secret'=>$profile['password'],'disallow'=>'all','allow'=>'ulaw','rtp_symmetric'=>'yes','rewrite_contact'=>'yes','force_rport'=>'yes','transport'=>'0.0.0.0-udp','max_contacts'=>'1','qualifyfreq'=>'30') as $key=>$value)$settings[$key]=array('value'=>$value,'flag'=>$flag++);
  $pbx->Core->addDevice($id,'pjsip',$settings);
 }elseif($device){$pbx->Core->delDevice($id);$pbx->Core->delUser($id);}
 needreload();echo $action.' complete'.PHP_EOL;exit;
}
if($action!=='apply')throw new Exception('Unknown action');
$groups=array();
foreach(array('257','258') as $num){
 $g=ringgroups_get($num);
 if(!$g || $g['grplist']!=='201-202')throw new Exception('Unexpected existing ring group '.$num);
 $groups[]=$g;
}
foreach(array('wav','ulaw') as $format){
 $input='/opt/raspbx-android/dj-praktikum.'.$format;
 if(!is_file($input)||filesize($input)<1000)throw new Exception('Missing prepared audio '.$format);
}
$existing=$pbx->Music->getCategoryByName($category);
if($existing)throw new Exception('Music category already exists; review before replacing');

$backup='/opt/raspbx-android/music-backups/'.date('Ymd-His');
mkdir($backup,0700,true);
function cnfValue($value){return '"'.str_replace(array('\\','"',"\n","\r"),array('\\\\','\\"','\\n','\\r'),$value).'"';}
$auth=$backup.'/db-auth.cnf';
file_put_contents($auth,"[client]\nuser=".cnfValue($amp_conf['AMPDBUSER'])."\npassword=".cnfValue($amp_conf['AMPDBPASS'])."\nsocket=/run/mysqld/mysqld.sock\n");chmod($auth,0600);
exec('mysqldump --defaults-extra-file='.escapeshellarg($auth).' --single-transaction --skip-lock-tables '.escapeshellarg($amp_conf['AMPDBNAME']).' > '.escapeshellarg($backup.'/asterisk.sql').' 2> '.escapeshellarg($backup.'/dump-error.log'),$unused,$result);
unlink($auth);
if($result!==0)throw new Exception('Database backup failed; music settings not changed');
exec('tar -czf '.escapeshellarg($backup.'/asterisk-config.tar.gz').' -C /etc asterisk',$unused,$result);
if($result!==0)throw new Exception('Configuration backup failed');
file_put_contents($backup.'/ringgroups.json',json_encode($groups,JSON_PRETTY_PRINT));

$pbx->Music->addCategory($category,'files');
$created=$pbx->Music->getCategoryByName($category);
if(!$created)throw new Exception('Failed to create music category');
$pbx->Music->updateCategoryByID($created['id'],'files',false,'','');
$directory=$pbx->Config->get('ASTVARLIBDIR').'/'.$pbx->Config->get('MOHDIR').'/'.$category;
chmod($directory,0755);
foreach(array('wav','ulaw') as $format){
 $src='/opt/raspbx-android/dj-praktikum.'.$format;$dest=$directory.'/dj-praktikum.'.$format;
 if(!copy($src,$dest))throw new Exception('Failed to install audio');
 chmod($dest,0644);
 if(hash_file('sha256',$src)!==hash_file('sha256',$dest))throw new Exception('Installed audio checksum mismatch');
}
foreach($groups as $g){
 ringgroups_del((string)$g['grpnum']);
 $ok=$pbx->Ringgroups->add((string)$g['grpnum'],$g['strategy'],$g['grptime'],$g['grplist'],$g['postdest'],$g['description'],$g['grppre'],$g['annmsg_id'],$g['alertinfo'],$g['needsconf'],$g['remotealert_id'],$g['toolate_id'],$category,$g['cwignore'],$g['cfignore'],$g['changecid'],$g['fixedcid'],$g['cpickup'],$g['recording'],$g['progress'],$g['elsewhere'],$g['rvolume']);
 if(!$ok)throw new Exception('Failed to update group music');
}
needreload();
echo json_encode(array('category'=>$category,'groups'=>array('257','258'),'directory'=>$directory,'backup'=>$backup,'wav_sha256'=>hash_file('sha256',$directory.'/dj-praktikum.wav'),'ulaw_sha256'=>hash_file('sha256',$directory.'/dj-praktikum.ulaw')),JSON_PRETTY_PRINT).PHP_EOL;
