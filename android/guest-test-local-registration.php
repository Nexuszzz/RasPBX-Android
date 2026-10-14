<?php
// Verify the phone's own SIP address without requiring an external softphone.
$accounts=json_decode(file_get_contents('/opt/raspbx-android/extensions.json'),true);
$account=null;foreach($accounts as $a){if((string)$a['extension']==='203')$account=$a;}
if(!$account)throw new Exception('Missing caller account');
$sock=stream_socket_client('udp://127.0.0.1:15060',$errno,$error,5);
if(!$sock)throw new Exception('UDP connection failed');
stream_set_timeout($sock,5);
$local=stream_socket_get_name($sock,false);$port=substr($local,strrpos($local,':')+1);
$cseq=0;$callid=bin2hex(openssl_random_pseudo_bytes(12));$uri='sip:127.0.0.1:15060';$tag=substr($callid,0,8);
function request($expires,$authorization=''){
 global $sock,$cseq,$callid,$uri,$tag,$port;
 $cseq++;
 $msg='REGISTER '.$uri." SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:".$port.';branch=z9hG4bK'.bin2hex(openssl_random_pseudo_bytes(8)).";rport\r\n";
 $msg.='From: <sip:203@127.0.0.1:15060>;tag='.$tag."\r\nTo: <sip:203@127.0.0.1:15060>\r\nCall-ID: ".$callid."\r\nCSeq: ".$cseq." REGISTER\r\n";
 $msg.='Contact: <sip:203@127.0.0.1:'.$port.">\r\nExpires: ".$expires."\r\nMax-Forwards: 70\r\nUser-Agent: RasPBX-Phone-Loopback-Test\r\n";
 if($authorization)$msg.='Authorization: '.$authorization."\r\n";
 $msg.="Content-Length: 0\r\n\r\n";
 fwrite($sock,$msg);
 for($i=0;$i<8;$i++){
  $response=fread($sock,65535);
  if(!$response)throw new Exception('SIP response timeout');
  if(strpos($response,'SIP/2.0 ')===0 && preg_match('/CSeq:\s*'.$cseq.' REGISTER/i',$response))return $response;
 }
 throw new Exception('No matching SIP response');
}
$results=array();
foreach(array(120,0) as $expires){
 $response=request($expires);
 if(strpos($response,'SIP/2.0 401')===0){
  preg_match('/WWW-Authenticate:\s*Digest ([^\r\n]+)/i',$response,$m);
  preg_match_all('/(\w+)="([^"]*)"/',$m[1],$pairs,PREG_SET_ORDER);$fields=array();
  foreach($pairs as $p)$fields[$p[1]]=$p[2];
  $ha1=md5('203:'.$fields['realm'].':'.$account['password']);$ha2=md5('REGISTER:'.$uri);
  $auth='Digest username="203", realm="'.$fields['realm'].'", nonce="'.$fields['nonce'].'", uri="'.$uri.'"';
  if(isset($fields['qop']) && in_array('auth',explode(',',$fields['qop']))){
   $cn=bin2hex(openssl_random_pseudo_bytes(8));$digest=md5($ha1.':'.$fields['nonce'].':00000001:'.$cn.':auth:'.$ha2);
   $auth.=', qop=auth, nc=00000001, cnonce="'.$cn.'"';
  }else $digest=md5($ha1.':'.$fields['nonce'].':'.$ha2);
  $auth.=', response="'.$digest.'", algorithm=MD5';
  $response=request($expires,$auth);
 }
 $status=strtok($response,"\r\n");
 if($status!=='SIP/2.0 200 OK')throw new Exception('Local registration rejected: '.$status);
 $results[]=array('action'=>$expires?'REGISTER':'UNREGISTER','extension'=>'203','server'=>'127.0.0.1:15060','response'=>$status);
}
fclose($sock);
echo json_encode($results,JSON_PRETTY_PRINT).PHP_EOL;
