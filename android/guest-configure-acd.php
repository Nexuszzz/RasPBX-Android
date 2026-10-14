<?php
// Configure a real Asterisk queue using the installed FreePBX 14 queue APIs.
include '/etc/freepbx.conf';
$pbx=FreePBX::create();
$category='acd_dj';
$action=isset($argv[1])?$argv[1]:'apply';
function addAcdQueue($number,$name,$agents){
 global $pbx,$category;
 $_REQUEST=array('maxlen'=>'0','joinempty'=>'yes','leavewhenempty'=>'no','strategy'=>'rrmemory','timeout'=>'20','retry'=>'3','wrapuptime'=>'2','announcefreq'=>'0','min-announce'=>'15','announceholdtime'=>'no','announceposition'=>'no','pannouncefreq'=>'0','recording'=>'dontcare','weight'=>'0','autofill'=>'yes','music'=>$category,'reportholdtime'=>'no','autopause'=>'no','autopausedelay'=>'0','autopausebusy'=>'no','autopauseunavail'=>'no','servicelevel'=>'60','memberdelay'=>'0','timeoutrestart'=>'no','skip_joinannounce'=>'','answered_elsewhere'=>'1','timeoutpriority'=>'app','penaltymemberslimit'=>'0','rvolume'=>'','rvol_mode'=>'dontcare','rtone'=>'0','announcemenu'=>'none','cron_schedule'=>'never');
 $members=array();foreach($agents as $agent)$members[]='Local/'.$agent.'@from-queue/n,0';
 if(!queues_add($number,$name,'','','app-blackhole,hangup,1','',$members,'','180','','2','','0','0',array(),'no','0','0','0','','','0','0','1'))throw new Exception('Failed to add ACD queue');
}
function ensureQueueNumberFree($number){
 global $pbx;
 $usage=framework_check_extension_usage($number);
 if(!empty($usage))throw new Exception('Requested queue number is already used: '.$number);
}

if($action==='test-add' || $action==='test-delete'){
 $profile=json_decode(file_get_contents('/opt/raspbx-android/acd-test-accounts.json'),true);
 $queue=(string)$profile['queue'];$queueName='Codex ACD validation';
 $q=$pbx->Database->prepare('SELECT descr FROM queues_config WHERE extension=?');$q->execute(array($queue));$existingName=$q->fetchColumn();
 if($existingName!==false && $existingName!==$queueName)throw new Exception('Test queue collision');
 foreach($profile['accounts'] as $a){
  $id=(string)$a['extension'];$d=$pbx->Core->getDevice($id);
  if($d && $d['description']!=='Codex ACD validation '.$id)throw new Exception('Test account collision');
  if($action==='test-add' && ($d || $pbx->Core->getUser($id)))throw new Exception('Test account already exists');
 }
 $custom='/etc/asterisk/pjsip.endpoint_custom_post.conf';
 $text=preg_replace('/\n?; BEGIN ANDROID ACD TEST\n.*?; END ANDROID ACD TEST\n?/s','',file_get_contents($custom));
 if($action==='test-add'){
  ensureQueueNumberFree($queue);$agents=array();$post="\n; BEGIN ANDROID ACD TEST\n";
  foreach($profile['accounts'] as $a){
   $id=(string)$a['extension'];$name='Codex ACD validation '.$id;
   $pbx->Core->addUser($id,$pbx->Core->generateDefaultUserSettings($id,$name));
   $flag=2;$settings=$pbx->Core->generateDefaultDeviceSettings('pjsip',$id,$name,$flag);
   foreach(array('secret'=>$a['password'],'disallow'=>'all','allow'=>'ulaw','rtp_symmetric'=>'yes','rewrite_contact'=>'yes','force_rport'=>'yes','transport'=>'0.0.0.0-udp','max_contacts'=>'1','qualifyfreq'=>'30') as $key=>$value)$settings[$key]=array('value'=>$value,'flag'=>$flag++);
   $pbx->Core->addDevice($id,'pjsip',$settings);$post.='['.$id."](+)\ndirect_media=no\n";
  }
  file_put_contents($custom,rtrim($text).$post."; END ANDROID ACD TEST\n");
  addAcdQueue($queue,$queueName,array($profile['accounts'][0]['extension'],$profile['accounts'][1]['extension']));
 }else{
  if($existingName!==false)queues_del($queue);
  foreach($profile['accounts'] as $a){$id=(string)$a['extension'];if($pbx->Core->getDevice($id)){$pbx->Core->delDevice($id);$pbx->Core->delUser($id);}}
  file_put_contents($custom,rtrim($text)."\n");
 }
 needreload();echo $action.' complete'.PHP_EOL;exit;
}
if($action!=='apply')throw new Exception('Unknown action');
ensureQueueNumberFree('259');
foreach(array('201','202') as $id){if(!$pbx->Core->getDevice($id))throw new Exception('Missing real agent '.$id);}
foreach(array('wav','ulaw') as $format){if(!is_file('/opt/raspbx-android/acd-menungso.'.$format) || filesize('/opt/raspbx-android/acd-menungso.'.$format)<1000)throw new Exception('Missing converted music');}
if($pbx->Music->getCategoryByName($category))throw new Exception('Music category already exists');

$backup='/opt/raspbx-android/acd-backups/'.date('Ymd-His');mkdir($backup,0700,true);
function cnfValue($value){return '"'.str_replace(array('\\','"',"\n","\r"),array('\\\\','\\"','\\n','\\r'),$value).'"';}
$auth=$backup.'/db-auth.cnf';
file_put_contents($auth,"[client]\nuser=".cnfValue($amp_conf['AMPDBUSER'])."\npassword=".cnfValue($amp_conf['AMPDBPASS'])."\nsocket=/run/mysqld/mysqld.sock\n");chmod($auth,0600);
exec('mysqldump --defaults-extra-file='.escapeshellarg($auth).' --single-transaction --skip-lock-tables '.escapeshellarg($amp_conf['AMPDBNAME']).' > '.escapeshellarg($backup.'/asterisk.sql').' 2> '.escapeshellarg($backup.'/dump-error.log'),$unused,$result);unlink($auth);
if($result!==0)throw new Exception('Database backup failed; ACD not changed');
exec('tar -czf '.escapeshellarg($backup.'/asterisk-config.tar.gz').' -C /etc asterisk',$unused,$result);
if($result!==0)throw new Exception('Configuration backup failed');
$pbx->Music->addCategory($category,'files');$created=$pbx->Music->getCategoryByName($category);
if(!$created)throw new Exception('Failed to add queue music');
$pbx->Music->updateCategoryByID($created['id'],'files',false,'','');
$directory=$pbx->Config->get('ASTVARLIBDIR').'/'.$pbx->Config->get('MOHDIR').'/'.$category;
chmod($directory,0755);
foreach(array('wav','ulaw') as $format){
 $src='/opt/raspbx-android/acd-menungso.'.$format;$dest=$directory.'/acd-menungso.'.$format;
 if(!copy($src,$dest))throw new Exception('Failed to install queue audio');chmod($dest,0644);
 if(hash_file('sha256',$src)!==hash_file('sha256',$dest))throw new Exception('Queue audio checksum mismatch');
}
addAcdQueue('259','ACD CS Praktikum',array('201','202'));
needreload();
echo json_encode(array('queue'=>'259','name'=>'ACD CS Praktikum','strategy'=>'rrmemory','agents'=>array('201','202'),'music'=>$category,'agent_timeout'=>20,'retry'=>3,'max_wait'=>180,'ringinuse'=>'no','backup'=>$backup,'ulaw_sha256'=>hash_file('sha256',$directory.'/acd-menungso.ulaw')),JSON_PRETTY_PRINT).PHP_EOL;
