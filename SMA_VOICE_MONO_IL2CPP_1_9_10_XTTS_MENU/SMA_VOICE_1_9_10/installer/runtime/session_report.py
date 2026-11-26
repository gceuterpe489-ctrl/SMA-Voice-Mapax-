"""Session diagnostics; the C# listener and Python serialize writes using a named mutex."""
import os, sys, threading, time, datetime, ctypes
from pathlib import Path

class SessionWriter:
    encoding = 'utf-8'
    def __init__(self,path):
        self.path=Path(path); self.lock=threading.RLock(); self.pending={}; self.handle=None
        if os.name=='nt':
            from ctypes import wintypes
            self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            self.kernel.CreateMutexW.argtypes=(ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR)
            self.kernel.CreateMutexW.restype=wintypes.HANDLE
            self.kernel.WaitForSingleObject.argtypes=(wintypes.HANDLE,wintypes.DWORD)
            self.kernel.WaitForSingleObject.restype=wintypes.DWORD
            self.kernel.ReleaseMutex.argtypes=(wintypes.HANDLE,); self.kernel.ReleaseMutex.restype=wintypes.BOOL
            self.kernel.CloseHandle.argtypes=(wintypes.HANDLE,)
            self.handle=self.kernel.CreateMutexW(None,False,'Local\\SMA_VOICE_'+self.path.stem)
            if not self.handle: raise OSError(ctypes.get_last_error(),'CreateMutexW')
    def _append(self,line):
        acquired=False
        try:
            if self.handle:
                acquired=self.kernel.WaitForSingleObject(self.handle,1000) in (0,0x80)
                if not acquired: return
            stamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
            with self.path.open('a',encoding='utf-8') as f: f.write(f'{stamp} [PYTHON] {line}\n')
        except OSError: pass # diagnostics never stop synthesis
        finally:
            if acquired: self.kernel.ReleaseMutex(self.handle)
    def write(self,text):
        with self.lock:
            tid=threading.get_ident(); lines=(self.pending.pop(tid,'')+str(text)).split('\n')
            self.pending[tid]=lines.pop()
            for line in lines:
                if line.strip(): self._append(line.rstrip('\r'))
        return len(text)
    def flush(self):
        with self.lock:
            tid=threading.get_ident(); text=self.pending.pop(tid,'')
            if text.strip(): self._append(text.rstrip('\r'))
    def close(self):
        with self.lock:
            for text in self.pending.values():
                if text.strip(): self._append(text.rstrip('\r'))
            self.pending.clear()
            if self.handle: self.kernel.CloseHandle(self.handle); self.handle=None
    def isatty(self): return False

_status_lock=threading.Lock()
def status(stage, detail=''):
    path=os.environ.get('SMA_VOICE_STATUS_FILE')
    if not path: return
    with _status_lock:
        p=Path(path); tmp=p.with_suffix(p.suffix+'.tmp')
        try:
            tmp.write_text(f'{stage} | {detail} | UTC={datetime.datetime.now(datetime.timezone.utc).isoformat()}\n',encoding='utf-8')
            for i in range(3):
                try: tmp.replace(p); break
                except PermissionError:
                    if i==2: raise
                    time.sleep(.01)
        except OSError: pass
        finally:
            try: tmp.unlink(missing_ok=True)
            except OSError: pass
