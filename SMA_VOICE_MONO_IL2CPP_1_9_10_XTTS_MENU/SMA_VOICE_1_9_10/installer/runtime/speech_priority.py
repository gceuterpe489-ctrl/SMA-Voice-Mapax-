"""Single-reader priority policy. No file I/O in the sounddevice callback."""
import threading
from session_guard import event_time, usable_text


def is_pending_box(path, guard, parse):
    try:
        actor,text,ready,name,alias,kind,live = parse(path, True, True)
        if kind != 'box' or guard.eligible(event_time(path),kind): return False
        return usable_text(text) and not guard.duplicate(actor,text,kind='box',record=False)
    except (OSError, ValueError, UnicodeError):
        return False


def next_event(directory, guard, parse, enabled=True):
    paths=sorted(directory.glob('*.evt'))
    if enabled:
        for path in paths:
            if is_pending_box(path,guard,parse): return path
    return paths[0] if paths else None


class PriorityToken:
    """A floating line may yield to a valid queued fixed line; scene cancellation wins."""
    def __init__(self, scene, directory, guard, parse, interval=.05):
        self.scene=scene; self.preempted=threading.Event(); self.stop=threading.Event()
        self.directory=directory; self.guard=guard; self.parse=parse; self.interval=interval
        self.completed=threading.Event()
        self.worker=threading.Thread(target=self._watch,daemon=True,name='speech-priority')
        self.worker.start()
    def _watch(self):
        while not self.stop.is_set() and not self.scene.is_set():
            if any(is_pending_box(p,self.guard,self.parse) for p in self.directory.glob('*.evt')):
                self.preempted.set(); return
            if self.stop.wait(self.interval): return
    def is_set(self): return self.scene.is_set() or (self.preempted.is_set() and not self.completed.is_set())
    def complete(self):
        """All PCM was handed to the device; late priority cannot replay it."""
        self.completed.set(); self.stop.set()
    def wait(self, timeout):
        # Wait outside the audio callback; short polling preserves both cancellation paths.
        import time
        deadline=time.monotonic()+timeout
        while not self.is_set():
            remaining=deadline-time.monotonic()
            if remaining<=0: break
            if self.completed.is_set(): self.scene.wait(min(.02,remaining))
            else: self.preempted.wait(min(.02,remaining))
        return self.is_set()
    def close(self):
        self.stop.set(); self.worker.join(timeout=1)
    def should_retry(self, stamp):
        return self.preempted.is_set() and not self.completed.is_set() and not self.scene.is_set() and not self.guard.eligible(stamp)


def restore_event(path, payload):
    """Restore exact identity and age atomically, never expose a partial event."""
    tmp=path.with_suffix('.retry.tmp')
    try:
        tmp.write_bytes(payload)
        tmp.replace(path)
    finally:
        try: tmp.unlink(missing_ok=True)
        except OSError: pass
