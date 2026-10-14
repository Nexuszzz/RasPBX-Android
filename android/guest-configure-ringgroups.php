<?php
// Configure the practicum through the FreePBX 14 APIs installed on this phone.
include '/etc/freepbx.conf';
$pbx=FreePBX::create();
$core=$pbx->Core;
$path='/opt/raspbx-android/extensions.json';
$accounts=json_decode(file_get_contents($path),true);
if(!is_array($accounts))throw new Exception('Missing existing lab accounts');
$id='203';$name='Android Lab 203';$secret=null;
foreach($accounts as $a){if((string)$a['extension']===$id)$secret=$a['password'];}
if(!$secret)$secret='Lab203-'.bin2hex(openssl_random_pseudo_bytes(8));
foreach(array('201','202') as $member){if(!$core->getDevice($member))throw new Exception('Missing group member '.$member);}
$existing=$core->getDevice($id);
if($existing && $existing['description']!==$name)throw new Exception('Extension 203 already belongs to another configuration');
$groups=array('257'=>array('ringall','CS Bersamaan'),'258'=>array('hunt','CS Bergiliran'));
foreach($groups as $num=>$data){
 if($core->getDevice((string)$num))throw new Exception('Group number already used by an extension');
 $stmt=$pbx->Database->prepare('SELECT description FROM ringgroups WHERE grpnum=?');$stmt->execute(array((string)$num));
 $description=$stmt->fetchColumn();
 if($description!==false && $description!==$data[1])throw new Exception('Group '.$num.' already belongs to another configuration');
}

$backup='/opt/raspbx-android/ringgroup-backups/'.date('Ymd-His');
if(!mkdir($backup,0700,true))throw new Exception('Cannot create backup');
function cnfValue($value){return '"'.str_replace(array('\\','"',"\n","\r"),array('\\\\','\\"','\\n','\\r'),$value).'"';}
$auth=$backup.'/db-auth.cnf';
file_put_contents($auth,"[client]\nuser=".cnfValue($amp_conf['AMPDBUSER'])."\npassword=".cnfValue($amp_conf['AMPDBPASS'])."\nsocket=/run/mysqld/mysqld.sock\n");chmod($auth,0600);
exec('mysqldump --defaults-extra-file='.escapeshellarg($auth).' --single-transaction --skip-lock-tables '.escapeshellarg($amp_conf['AMPDBNAME']).' > '.escapeshellarg($backup.'/asterisk.sql').' 2> '.escapeshellarg($backup.'/dump-error.log'),$unused,$result);
unlink($auth);
if($result!==0)throw new Exception('Database backup failed; no configuration changed');
exec('tar -czf '.escapeshellarg($backup.'/asterisk-config.tar.gz').' -C /etc asterisk',$unused,$result);
if($result!==0)throw new Exception('Configuration backup failed');
copy($path,$backup.'/extensions.json');chmod($backup.'/extensions.json',0600);

if(!$existing){
 if(!$core->getUser($id))$core->addUser($id,$core->generateDefaultUserSettings($id,$name));
 $flag=2;$settings=$core->generateDefaultDeviceSettings('pjsip',$id,$name,$flag);
 foreach(array('secret'=>$secret,'disallow'=>'all','allow'=>'ulaw&alaw','dtmfmode'=>'rfc4733','rtp_symmetric'=>'yes','rewrite_contact'=>'yes','force_rport'=>'yes','max_contacts'=>'1','qualifyfreq'=>'30','transport'=>'0.0.0.0-udp','direct_media'=>'no') as $key=>$value){$settings[$key]=array('value'=>$value,'flag'=>$flag++);}
 $core->addDevice($id,'pjsip',$settings);
}
$inList=false;
foreach($accounts as $account){if((string)$account['extension']===$id){$inList=true;if($account['password']!==$secret)throw new Exception('Existing account 203 has a different secret');}}
if(!$inList)$accounts[]=array('extension'=>$id,'password'=>$secret);
file_put_contents($path,json_encode($accounts,JSON_PRETTY_PRINT));chmod($path,0600);
$custom='/etc/asterisk/pjsip.endpoint_custom_post.conf';
$content=file_get_contents($custom);
$content=preg_replace('/\n?; BEGIN ANDROID RINGGROUP LAB\n.*?; END ANDROID RINGGROUP LAB\n?/s','',$content);
file_put_contents($custom,rtrim($content)."\n; BEGIN ANDROID RINGGROUP LAB\n[203](+)\ndirect_media=no\n; END ANDROID RINGGROUP LAB\n");

foreach($groups as $num=>$data){
 $stmt=$pbx->Database->prepare('SELECT COUNT(*) FROM ringgroups WHERE grpnum=?');$stmt->execute(array((string)$num));
 if($stmt->fetchColumn())ringgroups_del((string)$num);
 $ok=$pbx->Ringgroups->add((string)$num,$data[0],'20','201-202','app-blackhole,hangup,1',$data[1],'','0','','','0','0','default','CHECKED','CHECKED','default','','','dontcare','yes','yes','');
 if(!$ok)throw new Exception('Failed to create group '.$num);
}
needreload();
echo 'Ring-group practicum saved; backup: '.$backup.PHP_EOL;
echo 'Extension 203; group 257=ringall, 258=hunt; members 201/202; 20 seconds per iteration; music=default'.PHP_EOL;
