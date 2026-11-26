"""Session cutoffs, cancellation and short-lived duplicate detection. No TTS dependency."""
import re, time, threading, hashlib
from pathlib import Path
TICKS_EPOCH=621355968000000000
class Cancelled(Exception): pass
class BadAudio(Exception): pass

def event_time(path):
    head=path.name.split('-',1)[0]
    if len(head)==19 and head.isdigit():
        return (int(head)-TICKS_EPOCH)/10000000
    return path.stat().st_mtime

def marker_state(path):
    session,generation,ticks=path.read_text(encoding='utf-8-sig').splitlines()[:3]
    return session,int(generation),(int(ticks)-TICKS_EPOCH)/10000000

class SessionGuard:
    def __init__(self, path, cutoff, max_age=20, dedup_seconds=2.0, box_max_age=None):
        self.path=path; self.max_age=max_age; self.box_max_age=box_max_age; self.dedup_seconds=dedup_seconds; self.state=marker_state(path) if path else ('manual',0,cutoff)
        self.lock=threading.Lock(); self.token=None; self.stop=threading.Event(); self.recent={}
        self.worker=threading.Thread(target=self._watch,daemon=True); self.worker.start()
    def refresh(self):
        if not self.path: return
        try: new=marker_state(self.path)
        except (OSError,ValueError,IndexError): return
        with self.lock:
            if new!=self.state:
                self.state=new; self.recent.clear()
                if self.token is not None: self.token.set()
                print(f'CENA alterada | sessao={new[0][:8]} geracao={new[1]} | audio anterior cancelado',flush=True)
    def _watch(self):
        while not self.stop.wait(.08): self.refresh()
    def close(self):
        self.stop.set(); self.worker.join(timeout=1)
    def age_limit(self, kind):
        return self.box_max_age if kind=='box' and self.box_max_age is not None else self.max_age
    def eligible(self,stamp,kind='default'):
        self.refresh()
        with self.lock:
            if stamp < self.state[2]: return 'sessao/cena anterior'
        if time.time()-stamp>self.age_limit(kind): return 'evento expirado'
        return ''
    def begin(self, stamp, kind='default'):
        self.refresh()
        with self.lock:
            token=threading.Event()
            if stamp<self.state[2] or time.time()-stamp>self.age_limit(kind): token.set()
            self.token=token
            return token
    def duplicate(self,actor,text,kind='default',record=True,token=None):
        now=time.monotonic(); norm=' '.join(re.findall(r'\w+',text.casefold()))
        key=hashlib.sha256(((('box\0') if kind=='box' else '')+actor+'\0'+norm).encode()).digest()
        with self.lock:
            self.recent={k:v for k,v in self.recent.items() if now-v<self.dedup_seconds}
            if key in self.recent: return True
            if record and (token is None or not token.is_set()): self.recent[key]=now
        return False

def check_cancel(token):
    if token is not None and token.is_set(): raise Cancelled('mudanca de cena / sessao')

def usable_text(text):
    words=re.findall(r'[^\W_]+',text,flags=re.UNICODE)
    if not words: return False
    if re.fullmatch(r'\(?\s*(?:NPC Name|NPC Subtitle Line|Loading|Carregando|Please wait|Aguarde|undefined|null)\s*\)?[.!…]*',text,re.I): return False
    # Discard inputs consisting entirely of repeated letters or repeated short fragments.
    if all(re.fullmatch(r'(.)\1{2,}',w,re.I) for w in words): return False
    if len(words)>=4 and len(set(w.casefold() for w in words))==1: return False
    # Reject mixed one-letter and stretched versions of the same letter (a,a,aaaa).
    if len(words)>=3 and all(re.fullmatch(r'(.)\1*',w,re.I) for w in words) and len({w[0].casefold() for w in words})==1: return False
    return True

def audio_limit(text):
    words=len(re.findall(r'\w+',text))
    return min(60,max(7, 3+words*.85+len(text)*.075))
