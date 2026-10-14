"""Verify real queue waiting, song RTP, round-robin dispatch and conversation RTP."""
import argparse
import hashlib
import json
import secrets
import select
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
profile={'queue':'299','accounts':[{'extension':u,'password':secrets.token_hex(16)} for u in ['291','292','293']]}
profile_file=BASE/'runtime/private/android/acd-test-accounts.json'
profile_file.write_text(json.dumps(profile))
push_asset(profile_file)
source=(BASE/'output/audio/acd-menungso.ulaw').read_bytes()
expected={source[i:i+160] for i in range(0,len(source)-159,160)}
events=[]
waiting=False
music_packets=music_matches=music_varied=0

class Client(sip.UA):
    def __init__(self,account,frequency):
        super().__init__(account,(args.host,15060),args.bind,frequency)
        self.pending=None;self.answered=False;self.answer_at=None
        self.last_answer_callid=None

    def receive(self):
        raw,address=self.sip.recvfrom(65536)
        packet=sip.parse(raw);first,headers,body=packet
        if first.startswith('SIP/2.0'):
            if first.startswith('SIP/2.0 183') and body:self.rtp_destination=sip.media_address(body)
            return packet
        method=first.split(' ',1)[0]
        if method=='INVITE':
            callid=sip.one(headers,'call-id')
            # A queue can renegotiate the caller's established media session.
            # This is a re-INVITE, not a newly ringing agent.
            if self.dialog and callid==self.dialog[0]:
                if body:self.rtp_destination=sip.media_address(body)
                self.reply(packet,address,'200 OK',self.sdp())
                return None
            if self.pending and sip.one(self.pending[0][1],'call-id')==callid:
                self.reply(packet,address,'200 OK' if self.answered else '180 Ringing',self.sdp() if self.answered else '')
                return None
            if body:self.rtp_destination=sip.media_address(body)
            self.pending=(packet,address);self.answered=False;self.answer_at=time.monotonic()+.6
            self.incoming=True
            events.append({'extension':self.user,'event':'ring','time':time.monotonic(),'callid':callid})
            self.reply(packet,address,'100 Trying');self.reply(packet,address,'180 Ringing')
        elif method=='BYE':
            self.reply(packet,address,'200 OK');self.pending=None;self.answered=False;self.answer_at=None;self.incoming=False
        elif method=='CANCEL':
            self.reply(packet,address,'200 OK')
            if self.pending and not self.answered:self.reply(self.pending[0],self.pending[1],'487 Request Terminated')
            self.pending=None;self.answer_at=None;self.answered=False
        elif method=='OPTIONS':self.reply(packet,address,'200 OK')
        return None

    def exchange(self,method,uri,callid,to,body='',extra=None,timeout=50):
        cseq,data=self.request(method,uri,callid,to,body,extra)
        deadline=time.monotonic()+timeout;retry=time.monotonic()+.6
        while time.monotonic()<deadline:
            for client,packet in pump():
                if client is self and packet:
                    first,headers,_=packet
                    if sip.one(headers,'call-id')==callid and sip.one(headers,'cseq')==f'{cseq} {method}' and int(first.split(' ')[1])>=200:return packet,cseq
            if time.monotonic()>=retry:self.sip.sendto(data,self.server);retry=time.monotonic()+1
        raise TimeoutError(f'{self.user} {method} timed out')

def pump():
    global music_packets,music_matches,music_varied
    for client in clients:
        if client.pending and not client.answered and client.answer_at is not None and time.monotonic()>=client.answer_at:
            client.reply(client.pending[0],client.pending[1],'200 OK',client.sdp());client.answered=True
            client.last_answer_callid=sip.one(client.pending[0][1],'call-id')
            events.append({'extension':client.user,'event':'answer','time':time.monotonic(),'callid':client.last_answer_callid})
    ready,_,_=select.select([sock for client in clients for sock in [client.sip,client.rtp]],[],[],.025)
    packets=[]
    for sock in ready:
        client=next(c for c in clients if sock in [c.sip,c.rtp])
        if sock is client.sip:packets.append((client,client.receive()));continue
        raw,_=client.rtp.recvfrom(4096)
        if waiting and client.user=='293' and len(raw)>=12 and raw[0]>>6==2 and raw[1]&127==0:
            music_packets+=1;payload=raw[12+(raw[0]&15)*4:]
            if payload in expected:
                music_matches+=1
                if len(set(payload))>8:music_varied+=1
    return packets

def pump_for(seconds):
    end=time.monotonic()+seconds
    while time.monotonic()<end:pump()

def wait_answer(since):
    end=time.monotonic()+15
    while time.monotonic()<end:
        pump()
        answers=[event for event in events[since:] if event['event']=='answer' and event['extension'] in ['291','292']]
        if answers:return next(c for c in clients if c.user==answers[-1]['extension'])
    raise AssertionError('Queue did not dispatch after an agent became available')

created=False
clients=[]
try:
    print(guest('php /opt/raspbx-android/guest-configure-acd.php test-add',timeout=60),flush=True)
    created=True
    print(guest('timeout 180 /var/lib/asterisk/bin/retrieve_conf --json && asterisk -rx "core reload"',timeout=200),flush=True)
    clients=[Client(a,f) for a,f in zip(profile['accounts'],[500,1000,1500])]
    sip.clients=clients
    for client in clients:client.register(180)
    caller=clients[2]
    clients[0].invite('292')
    print('Both isolated agents are in a conversation.',flush=True)
    busy_snapshot=guest('asterisk -rx "queue show 299"',timeout=15)
    print(busy_snapshot,flush=True)
    start=len(events);waiting=True;queue_start=time.monotonic()
    caller.invite('299')
    pump_for(4)
    busy_wait_seconds=time.monotonic()-queue_start
    if any(e['event']=='ring' for e in events[start:]):raise AssertionError('Queue rang an agent who was already in a call')
    if music_varied<20:raise AssertionError('Queue waiting RTP did not match the supplied ACD song')
    music={'rtp_packets':music_packets,'source_payload_matches':music_matches,'nonconstant_source_payload_matches':music_varied}
    clients[0].hangup()
    first=wait_answer(start);waiting=False
    sip.clients=[caller,first];media1=sip.run_media(caller,first,4);sip.clients=clients
    caller.hangup();pump_for(2.2)
    start2=len(events);waiting=True
    caller.invite('299')
    second=wait_answer(start2);waiting=False
    if second is first:raise AssertionError('rrmemory did not rotate to the other available agent')
    sip.clients=[caller,second];media2=sip.run_media(caller,second,4);sip.clients=clients
    caller.hangup();pump_for(.5)
    result={'configured_queue':'259','isolated_test_queue':'299','strategy':'rrmemory','both_busy_wait_seconds':round(busy_wait_seconds,3),'no_busy_agent_rung':True,'music':music,'successive_agents':[first.user,second.user],'conversation_rtp':[media1,media2],'source_ulaw_sha256':hashlib.sha256(source).hexdigest(),'human_softphones_touched':False,'microphone_speaker_tested':False}
    (BASE/'analysis/android-acd-test.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2),flush=True)
finally:
    waiting=False;sip.clients=clients
    for client in clients:
        try:client.hangup()
        except Exception as error:print('Cleanup hangup:',type(error).__name__)
    for client in clients:
        try:client.register(0)
        except Exception as error:print('Cleanup unregister:',type(error).__name__)
    for client in clients:client.close()
    if created:print(guest('php /opt/raspbx-android/guest-configure-acd.php test-delete && timeout 180 /var/lib/asterisk/bin/retrieve_conf --json && asterisk -rx "core reload"',timeout=200),flush=True)
