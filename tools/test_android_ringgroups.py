"""Exercise actual phone ringall/hunt calls, early music and bidirectional RTP."""
import argparse
import json
import select
import socket
import time
from pathlib import Path
import sip_test_client as sip

BASE=Path(__file__).resolve().parents[1]
(BASE/'analysis').mkdir(parents=True,exist_ok=True)
(BASE/'runtime/private/android').mkdir(parents=True,exist_ok=True)
parser=argparse.ArgumentParser()
parser.add_argument('--host',required=True)
parser.add_argument('--bind',required=True)
args=parser.parse_args()
accounts=json.loads((BASE/'runtime/private/android/extensions.json').read_text())
events=[]
call_start=0

class Client(sip.UA):
    def __init__(self,account,frequency):
        super().__init__(account,(args.host,15060),args.bind,frequency)
        self.pending=None
        self.answer_delay=None
        self.answer_at=None
        self.answered=False
        self.ring_at=None
        self.cancelled=False
        self.music_packets=0
        self.music_varied=0

    def receive(self):
        raw,address=self.sip.recvfrom(65536)
        packet=sip.parse(raw)
        first,headers,body=packet
        if first.startswith('SIP/2.0'):
            if first.startswith('SIP/2.0 183') and body:
                self.rtp_destination=sip.media_address(body)
            return packet
        method=first.split(' ',1)[0]
        if method=='OPTIONS':self.reply(packet,address,'200 OK')
        elif method=='INVITE':
            if self.pending and sip.one(self.pending[0][1],'call-id')==sip.one(headers,'call-id'):
                self.reply(packet,address,'200 OK' if self.answered else '180 Ringing',self.sdp() if self.answered else '')
                return None
            self.rtp_destination=sip.media_address(body)
            self.pending=(packet,address)
            self.incoming=True
            self.ring_at=time.monotonic()
            self.answer_at=self.ring_at+self.answer_delay if self.answer_delay is not None else None
            events.append({'extension':self.user,'event':'ring','seconds':round(self.ring_at-call_start,3)})
            self.reply(packet,address,'100 Trying')
            self.reply(packet,address,'180 Ringing')
        elif method=='CANCEL':
            self.reply(packet,address,'200 OK')
            if self.pending and not self.answered:
                self.reply(self.pending[0],self.pending[1],'487 Request Terminated')
                self.cancelled=True
                events.append({'extension':self.user,'event':'cancel','seconds':round(time.monotonic()-call_start,3)})
                self.pending=None
                self.answer_at=None
        elif method=='BYE':
            self.reply(packet,address,'200 OK')
            self.incoming=False
            self.pending=None
        elif method not in ['ACK']:
            self.reply(packet,address,'501 Not Implemented')
        return None

    def exchange(self,method,uri,callid,to,body='',extra=None,timeout=50):
        cseq,data=self.request(method,uri,callid,to,body,extra)
        deadline=time.monotonic()+timeout
        retry=time.monotonic()+.6
        while time.monotonic()<deadline:
            for client,packet in pump():
                if client is self and packet:
                    first,headers,_=packet
                    if sip.one(headers,'call-id')==callid and sip.one(headers,'cseq')==f'{cseq} {method}' and int(first.split(' ')[1])>=200:
                        return packet,cseq
            if time.monotonic()>=retry:
                self.sip.sendto(data,self.server)
                retry=time.monotonic()+1
        raise TimeoutError(f'{self.user} {method} timed out')

def pump():
    for client in clients:
        if client.pending and not client.answered and client.answer_at is not None and time.monotonic()>=client.answer_at:
            client.reply(client.pending[0],client.pending[1],'200 OK',client.sdp())
            client.answered=True
            events.append({'extension':client.user,'event':'answer','seconds':round(time.monotonic()-call_start,3)})
    ready,_,_=select.select([sock for client in clients for sock in [client.sip,client.rtp]],[],[],.025)
    packets=[]
    for sock in ready:
        client=next(client for client in clients if sock in [client.sip,client.rtp])
        if sock is client.sip:
            packets.append((client,client.receive()))
        else:
            raw,_=client.rtp.recvfrom(4096)
            if client.user=='203' and client.dialog is None and len(raw)>=12 and raw[0]>>6==2 and raw[1]&127==0:
                client.music_packets+=1
                payload=raw[12+(raw[0]&15)*4:]
                if len(set(payload))>8:client.music_varied+=1
    return packets

clients=[Client(next(a for a in accounts if a['extension']==user),frequency) for user,frequency in [('201',500),('202',1000),('203',1500)]]
sip.clients=clients
caller=clients[2]
results=[]
try:
    for client in clients:client.register(180)
    for group,selected in [('257',clients[0]),('258',clients[1])]:
        events.clear()
        for client in clients:
            client.pending=None;client.answer_at=None;client.answered=False;client.ring_at=None;client.cancelled=False
            client.answer_delay=1.5 if client is selected else None
            client.music_packets=client.music_varied=0
            client.rtp_destination=None
        call_start=time.monotonic()
        caller.invite(group)
        end=time.monotonic()+4
        while time.monotonic()<end and (not selected.answered or not next(c for c in clients[:2] if c is not selected).cancelled):
            pump()
        music={'packets':caller.music_packets,'nonconstant_pcmu_packets':caller.music_varied}
        rings=[event for event in events if event['event']=='ring']
        if len(rings)!=2 or not selected.answered:raise AssertionError('Both agents must ring, with the selected agent answering')
        gap=rings[1]['seconds']-rings[0]['seconds']
        if group=='257':
            if gap>2 or not clients[1].cancelled:raise AssertionError('ringall did not ring both agents together and cancel the other')
        elif not (18<=gap<=25) or not clients[0].cancelled:
            raise AssertionError('hunt did not advance after its 20-second iteration')
        if music['nonconstant_pcmu_packets']<5:raise AssertionError('No verified early music RTP received')
        sip.clients=[caller,selected]
        media=sip.run_media(caller,selected,duration=4)
        sip.clients=clients
        caller.hangup()
        for _ in range(10):pump()
        result={'group':group,'strategy':'ringall' if group=='257' else 'hunt','events':list(events),'ring_gap_seconds':round(gap,3),'early_music_rtp':music,'media':media}
        results.append(result)
        print(json.dumps(result),flush=True)
    (BASE/'analysis/android-ringgroups-test.json').write_text(json.dumps({'results':results,'microphone_speaker_tested':False},indent=2))
finally:
    sip.clients=clients
    for client in clients:
        try:client.hangup()
        except Exception as error:print('Cleanup hangup:',type(error).__name__)
    for client in clients:
        try:client.register(0)
        except Exception as error:print('Cleanup unregister:',type(error).__name__)
    for client in clients:client.close()
