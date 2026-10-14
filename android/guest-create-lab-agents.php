<?php
include '/etc/freepbx.conf';
$pbx=FreePBX::create();$path='/opt/raspbx-android/extensions.json';
$accounts=json_decode(file_get_contents($path),true);
if(!is_array($accounts))throw new Exception('Start the APK before creating lab accounts');
foreach(array('201','202') as $id){
 $device=$pbx->Core->getDevice($id);$name='Android Lab '.$id;
 if($device){if($device['description']!==$name)throw new Exception('Account collision');continue;}
 $secret='Android'.$id.'-'.bin2hex(openssl_random_pseudo_bytes(8));
 $pbx->Core->addUser($id,$pbx->Core->generateDefaultUserSettings($id,$name));
 $flag=2;$settings=$pbx->Core->generateDefaultDeviceSettings('pjsip',$id,$name,$flag);
 foreach(array('secret'=>$secret,'disallow'=>'all','allow'=>'ulaw&alaw','dtmfmode'=>'rfc4733','rtp_symmetric'=>'yes','rewrite_contact'=>'yes','force_rport'=>'yes','transport'=>'0.0.0.0-udp','max_contacts'=>'1','qualifyfreq'=>'30') as $key=>$value)$settings[$key]=array('value'=>$value,'flag'=>$flag++);
 $pbx->Core->addDevice($id,'pjsip',$settings);$accounts[]=array('extension'=>$id,'password'=>$secret);
}
file_put_contents($path,json_encode($accounts,JSON_PRETTY_PRINT));chmod($path,0600);
needreload();echo 'Lab agents 201/202 ready; passwords remain private'.PHP_EOL;
