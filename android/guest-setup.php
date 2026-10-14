<?php
include '/etc/freepbx.conf';
$pbx=FreePBX::create();
$pbx->Config->set_conf_values(array('ASTSIPDRIVER'=>'both'),true,true);
$path='/opt/raspbx-android/extensions.json';
if (file_exists($path)) {
    $accounts=json_decode(file_get_contents($path),true);
} else {
    $accounts=array();
    foreach (array('101','102') as $id) {
        $accounts[]=array('extension'=>$id,'password'=>'Android'.$id.'-'.bin2hex(openssl_random_pseudo_bytes(4)));
    }
    file_put_contents($path,json_encode($accounts,JSON_PRETTY_PRINT));
    chmod($path,0600);
}
foreach ($accounts as $account) {
    $id=(string)$account['extension'];
    $name='Android Lab '.$id;
    $existing=$pbx->Core->getDevice($id);
    if ($existing && $existing['description']!==$name) {
        throw new Exception('Existing extension '.$id.' belongs to another configuration');
    }
    if (!$existing) {
        if (!$pbx->Core->getUser($id)) {
            $pbx->Core->addUser($id,$pbx->Core->generateDefaultUserSettings($id,$name));
        }
        $flag=2;
        $settings=$pbx->Core->generateDefaultDeviceSettings('pjsip',$id,$name,$flag);
        foreach (array('secret'=>$account['password'],'disallow'=>'all','allow'=>'ulaw&alaw',
            'dtmfmode'=>'rfc4733','rtp_symmetric'=>'yes','rewrite_contact'=>'yes','force_rport'=>'yes',
            'max_contacts'=>'1','qualifyfreq'=>'30','transport'=>'0.0.0.0-udp') as $key=>$value) {
            $settings[$key]=array('value'=>$value,'flag'=>$flag++);
        }
        $pbx->Core->addDevice($id,'pjsip',$settings);
    }
}
$sip=$pbx->Sipsettings;
$sip->setConfig('rtpstart','20000');
$sip->setConfig('rtpend','20031');
$wifi=getenv('RASPBX_WIFI_IP');
if(!$wifi && file_exists('/opt/raspbx-android/link-profile.json')){
    $profile=json_decode(file_get_contents('/opt/raspbx-android/link-profile.json'),true);
    $wifi=isset($profile['phone_ip'])?$profile['phone_ip']:'';
}
if($wifi && !filter_var($wifi,FILTER_VALIDATE_IP,FILTER_FLAG_IPV4))throw new Exception('Invalid Wi-Fi address');
$sip->setConfig('externip',$wifi?$wifi:'');
$sip->setConfig('localnets',array(array('net'=>'127.0.0.1','mask'=>'255.255.255.255')));
$sip->setConfig('binds',array('udp'=>array('0.0.0.0'=>'on')));
$sip->setConfig('udpport-0.0.0.0','15060');
$custom='/etc/asterisk/pjsip.endpoint_custom_post.conf';
$contents=file_get_contents($custom);
if (strpos($contents,'; BEGIN ANDROID LAB')===false) {
    $block="\n; BEGIN ANDROID LAB\n";
    foreach($accounts as $account){$block.='['.$account['extension']."](+)\ndirect_media=no\n";}
    file_put_contents($custom,$contents.$block."; END ANDROID LAB\n");
}
needreload();
echo "Android lab extensions saved; SIP UDP 15060 configured\n";
