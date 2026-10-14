"""Verify that actual RTP carries the supplied music, using an isolated test account."""
import argparse
import concurrent.futures
import hashlib
import json
import secrets
import select
import shlex
import time
from pathlib import Path
import sip_test_client as sip
from android_app_shell import guest,push_asset

BASE=Path(__file__).resolve().parents[1]
(BASE/'analysis').mkdir(parents=True,exist_ok=True)
(BASE/'runtime/private/android').mkdir(parents=True,exist_ok=True)
parser=argparse.ArgumentParser()
parser.add_argument('--host',required=True)
parser.add_argument('--bind',required=True)
args=parser.parse_args()
account={'extension':'289','password':secrets.token_hex(16)}
profile=BASE/'runtime/private/android/music-test-account.json'
profile.write_text(json.dumps(account))
push_asset(profile)

class MusicClient(sip.UA):
    def receive(self):
        raw,address=self.sip.recvfrom(65536)
        packet=sip.parse(raw)
        first,headers,body=packet
        if first.startswith('SIP/2.0'):return packet
        method=first.split(' ',1)[0]
        if method=='INVITE':
            self.rtp_destination=sip.media_address(body)
            self.reply(packet,address,'100 Trying')
            self.reply(packet,address,'180 Ringing')
            self.reply(packet,address,'200 OK',self.sdp())
            remote=sip.one(headers,'contact').split('<',1)[-1].split('>',1)[0]
            self.dialog=(sip.one(headers,'call-id'),sip.one(headers,'from'),remote)
            self.incoming=True
        elif method=='BYE':
            self.reply(packet,address,'200 OK');self.dialog=None;self.incoming=False
        elif method=='OPTIONS':self.reply(packet,address,'200 OK')
        elif method=='CANCEL':self.reply(packet,address,'200 OK')
        return None

created=False
client=None
try:
    print(guest('php /opt/raspbx-android/guest-configure-hold-music.php test-add',timeout=45),flush=True)
    created=True
    print(guest('timeout 180 /var/lib/asterisk/bin/retrieve_conf --json && asterisk -rx "core reload"',timeout=200),flush=True)
    client=MusicClient(account,(args.host,15060),args.bind,500)
    sip.clients=[client]
    client.register(120)
    data=(BASE/'output/audio/dj-praktikum.ulaw').read_bytes()
    expected={data[i:i+160] for i in range(0,len(data)-159,160)}
    received=matched=varied=0
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        command='channel originate PJSIP/289 application MusicOnHold praktikum_dj,8'
        future=executor.submit(guest,'asterisk -rx '+shlex.quote(command),timeout=25)
        deadline=time.monotonic()+7
        while time.monotonic()<deadline:
            ready,_,_=select.select([client.sip,client.rtp],[],[],.05)
            for sock in ready:
                if sock is client.sip:client.receive();continue
                raw,_=client.rtp.recvfrom(4096)
                if len(raw)>=12 and raw[0]>>6==2 and raw[1]&127==0:
                    received+=1
                    payload=raw[12+(raw[0]&15)*4:]
                    if payload in expected:
                        matched+=1
                        if len(set(payload))>8:varied+=1
            if varied>=100:break
        print(future.result(timeout=25),flush=True)
    if varied<20:raise AssertionError('RTP did not match the supplied DJ audio')
    result={'class':'praktikum_dj','test_extension':'289','rtp_pcmu_packets':received,'exact_source_payload_matches':matched,'nonconstant_source_payload_matches':varied,'ulaw_sha256':hashlib.sha256(data).hexdigest(),'human_softphones_touched':False,'microphone_speaker_tested':False}
    (BASE/'analysis/android-hold-music-rtp-test.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2),flush=True)
finally:
    if client:
        try:client.hangup()
        except Exception as error:print('Cleanup hangup:',type(error).__name__)
        try:client.register(0)
        except Exception as error:print('Cleanup unregister:',type(error).__name__)
        client.close()
    if created:
        print(guest('php /opt/raspbx-android/guest-configure-hold-music.php test-delete && timeout 180 /var/lib/asterisk/bin/retrieve_conf --json && asterisk -rx "core reload"',timeout=200),flush=True)
