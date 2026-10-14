"""SIP Digest, SDP and PCMU RTP client used by the Android-only tests."""
import hashlib
import json
import math
import re
import select
import socket
import struct
import time
import uuid
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]

def parse(raw):
    text=raw.decode('utf-8','replace');head,_,body=text.partition('\r\n\r\n')
    lines=head.split('\r\n');headers={}
    for line in lines[1:]:
        if ':' in line:
            key,value=line.split(':',1);headers.setdefault(key.lower(),[]).append(value.strip())
    return lines[0],headers,body

def one(headers,key):return headers.get(key.lower(),[''])[0]

def digest(challenge,method,uri,user,password):
    fields=dict(re.findall(r'(\w+)="([^"]*)"',challenge))
    md5=lambda text:hashlib.md5(text.encode()).hexdigest()
    ha1=md5(f"{user}:{fields['realm']}:{password}");ha2=md5(method+':'+uri)
    result=f'Digest username="{user}", realm="{fields["realm"]}", nonce="{fields["nonce"]}", uri="{uri}"'
    if 'auth' in fields.get('qop','').split(','):
        cnonce=uuid.uuid4().hex;answer=md5(f"{ha1}:{fields['nonce']}:00000001:{cnonce}:auth:{ha2}")
        result+=f', qop=auth, nc=00000001, cnonce="{cnonce}"'
    else:answer=md5(f"{ha1}:{fields['nonce']}:{ha2}")
    if 'opaque' in fields:result+=f', opaque="{fields["opaque"]}"'
    return result+f', response="{answer}", algorithm=MD5'

def media_address(sdp):
    ip=re.search(r'^c=IN IP4 ([^\r\n]+)',sdp,re.M)
    port=re.search(r'^m=audio (\d+) RTP/AVP',sdp,re.M)
    if not ip or not port:raise ValueError('Missing IPv4 RTP audio in SDP')
    return ip.group(1).strip(),int(port.group(1))

def pcmu_tone(frequency):
    payload=[]
    for index in range(160):
        sample=int(5000*math.sin(2*math.pi*frequency*index/8000))
        sign=0x80 if sample<0 else 0
        sample=min(abs(sample),32635)+0x84
        exponent=max(0,min(7,sample.bit_length()-8))
        mantissa=(sample>>(exponent+3))&15
        payload.append((~(sign|(exponent<<4)|mantissa))&255)
    return bytes(payload)

class UA:
    def __init__(self,account,server,bind,frequency):
        self.user=account['extension'];self.password=account['password'];self.server=server;self.bind=bind
        self.sip=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);self.sip.bind((bind,0))
        self.rtp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);self.rtp.bind((bind,0))
        self.tag=uuid.uuid4().hex[:12];self.regid=uuid.uuid4().hex;self.cseq=0
        self.contact=f'<sip:{self.user}@{bind}:{self.sip.getsockname()[1]}>'
        self.from_header=f'<sip:{self.user}@{server[0]}:{server[1]}>;tag={self.tag}'
        self.rtp_destination=None;self.dialog=None;self.incoming=False;self.received=0;self.matched=0
        self.payload=pcmu_tone(frequency);self.sequence=0;self.timestamp=0;self.ssrc=int(uuid.uuid4().hex[:8],16)
    def sdp(self):
        return f'v=0\r\no=- 123456 123456 IN IP4 {self.bind}\r\ns=Local PBX routing test\r\nc=IN IP4 {self.bind}\r\nt=0 0\r\nm=audio {self.rtp.getsockname()[1]} RTP/AVP 0 101\r\na=rtpmap:0 PCMU/8000\r\na=rtpmap:101 telephone-event/8000\r\na=fmtp:101 0-16\r\na=sendrecv\r\na=ptime:20\r\n'
    def request(self,method,uri,callid,to,body='',extra=None,cseq=None,branch=None):
        if cseq is None:self.cseq+=1;cseq=self.cseq
        branch=branch or 'z9hG4bK'+uuid.uuid4().hex
        headers={'Via':f'SIP/2.0/UDP {self.bind}:{self.sip.getsockname()[1]};branch={branch};rport',
            'From':self.from_header,'To':to,'Call-ID':callid,'CSeq':f'{cseq} {method}',
            'Contact':self.contact,'Max-Forwards':'70','User-Agent':'RasPBX-Two-Server-Validation'}
        if body:headers['Content-Type']='application/sdp'
        headers.update(extra or {});headers['Content-Length']=str(len(body.encode()))
        data=(f'{method} {uri} SIP/2.0\r\n'+'\r\n'.join(f'{key}: {value}' for key,value in headers.items())+'\r\n\r\n'+body).encode()
        self.sip.sendto(data,self.server)
        return cseq,data
    def reply(self,packet,address,status,body=''):
        first,headers,_=packet
        to=one(headers,'to')
        if ';tag=' not in to:to+=';tag='+self.tag
        lines=[f'SIP/2.0 {status}']
        for value in headers.get('via',[]):lines.append('Via: '+value)
        for key in ['from','call-id','cseq']:lines.append(key.title()+': '+one(headers,key))
        lines.extend(['To: '+to,'Contact: '+self.contact])
        if body:lines.append('Content-Type: application/sdp')
        lines.append('Content-Length: '+str(len(body.encode())))
        self.sip.sendto(('\r\n'.join(lines)+'\r\n\r\n'+body).encode(),address)
        if 'INVITE' in one(headers,'cseq') and status=='200 OK':print(self.user,'answered INVITE to',address,'CSeq',one(headers,'cseq'),flush=True)
    def receive(self):
        raw,address=self.sip.recvfrom(65536);packet=parse(raw);first,headers,body=packet
        if not first.startswith('SIP/2.0'):
            method=first.split(' ',1)[0]
            if method=='OPTIONS':self.reply(packet,address,'200 OK')
            elif method=='INVITE':
                if body:
                    try:self.rtp_destination=media_address(body)
                    except ValueError:self.reply(packet,address,'488 Not Acceptable Here');return None
                self.incoming=True
                self.reply(packet,address,'100 Trying');self.reply(packet,address,'180 Ringing');self.reply(packet,address,'200 OK',self.sdp())
                print(self.user,'incoming RTP destination',self.rtp_destination,flush=True)
            elif method=='BYE':self.reply(packet,address,'200 OK');self.incoming=False
            elif method=='CANCEL':self.reply(packet,address,'200 OK')
            return None
        return packet
    def exchange(self,method,uri,callid,to,body='',extra=None,timeout=45):
        cseq,data=self.request(method,uri,callid,to,body,extra)
        deadline=time.monotonic()+timeout;retry=time.monotonic()+.6
        while time.monotonic()<deadline:
            ready,_,_=select.select([client.sip for client in clients],[],[],.05)
            for sock in ready:
                client=next(item for item in clients if item.sip is sock)
                packet=client.receive()
                if client is not self or not packet:continue
                first,headers,_=packet
                if 'INVITE' in one(headers,'cseq'):print(self.user,'received',first,'CSeq',one(headers,'cseq'),flush=True)
                if one(headers,'call-id')==callid and one(headers,'cseq')==f'{cseq} {method}':
                    code=int(first.split(' ')[1])
                    if code>=200:return packet,cseq
            if time.monotonic()>=retry:self.sip.sendto(data,self.server);retry=time.monotonic()+1
        raise TimeoutError(f'{self.user} {method} timed out')
    def register(self,expires):
        uri=f'sip:{self.server[0]}:{self.server[1]}'
        to=f'<sip:{self.user}@{self.server[0]}:{self.server[1]}>'
        packet,_=self.exchange('REGISTER',uri,self.regid,to,extra={'Expires':str(expires)})
        if packet[0].startswith('SIP/2.0 401'):
            auth=digest(one(packet[1],'www-authenticate'),'REGISTER',uri,self.user,self.password)
            packet,_=self.exchange('REGISTER',uri,self.regid,to,extra={'Expires':str(expires),'Authorization':auth})
        if packet[0]!='SIP/2.0 200 OK':raise RuntimeError(f'{self.user} registration failed: '+packet[0])
        print(self.user, 'REGISTER' if expires else 'UNREGISTER',packet[0],flush=True)
    def invite(self,target):
        callid=uuid.uuid4().hex;uri=f'sip:{target}@{self.server[0]}:{self.server[1]}';to='<'+uri+'>'
        packet,cseq=self.exchange('INVITE',uri,callid,to,self.sdp())
        if packet[0].startswith('SIP/2.0 401'):
            branch=re.search(r'branch=([^;\s]+)',one(packet[1],'via')).group(1)
            self.request('ACK',uri,callid,one(packet[1],'to'),cseq=cseq,branch=branch)
            auth=digest(one(packet[1],'www-authenticate'),'INVITE',uri,self.user,self.password)
            packet,cseq=self.exchange('INVITE',uri,callid,to,self.sdp(),extra={'Authorization':auth})
        if packet[0]!='SIP/2.0 200 OK':raise RuntimeError('Call failed: '+packet[0])
        self.rtp_destination=media_address(packet[2])
        contact=re.search(r'<([^>]+)>',one(packet[1],'contact')).group(1)
        self.dialog=(callid,one(packet[1],'to'),contact)
        self.request('ACK',contact,callid,self.dialog[1],cseq=cseq)
        print(self.user,'called',target,'200 OK; RTP',self.rtp_destination,flush=True)
    def hangup(self):
        if self.dialog:
            callid,to,uri=self.dialog
            packet,_=self.exchange('BYE',uri,callid,to)
            if packet[0]!='SIP/2.0 200 OK':raise RuntimeError('BYE failed')
            self.dialog=None
    def close(self):self.sip.close();self.rtp.close()

def run_media(caller,callee,duration=6):
    for client in clients:
        client.received=client.matched=0
        client.rtp.setblocking(False)
        try:
            while True:client.rtp.recv(4096)
        except BlockingIOError:pass
        finally:client.rtp.setblocking(True)
    deadline=time.monotonic()+duration;next_send=time.monotonic()
    while time.monotonic()<deadline:
        if time.monotonic()>=next_send:
            for client in clients:
                if client.rtp_destination:
                    header=struct.pack('!BBHII',0x80,0,client.sequence,client.timestamp,client.ssrc)
                    client.rtp.sendto(header+client.payload,client.rtp_destination)
                    client.sequence=(client.sequence+1)&65535;client.timestamp+=160
            next_send+=.02
        ready,_,_=select.select([sock for client in clients for sock in [client.sip,client.rtp]],[],[],.005)
        for sock in ready:
            client=next(item for item in clients if sock in [item.sip,item.rtp])
            if sock is client.sip:client.receive();continue
            raw,address=client.rtp.recvfrom(4096)
            if len(raw)>=12 and raw[0]>>6==2 and raw[1]&127==0:
                client.received+=1
                other=callee if client is caller else caller
                offset=12+(raw[0]&15)*4
                if raw[offset:]==other.payload:client.matched+=1
    result={'direction':caller.user+' -> '+callee.user,'answered':True,'seconds':duration,
            'rtp_received':{client.user:client.received for client in clients},
            'pcmu_tone_payload_matches':{client.user:client.matched for client in clients}}
    print(json.dumps(result),flush=True)
    if any(client.matched<20 for client in clients):raise RuntimeError('Bidirectional PCMU RTP verification failed')
    return result

clients=[]
