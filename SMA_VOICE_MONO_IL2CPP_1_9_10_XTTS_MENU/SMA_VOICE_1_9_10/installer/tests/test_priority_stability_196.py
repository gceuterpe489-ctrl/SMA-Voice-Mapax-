import sys, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'runtime')]
from session_guard import SessionGuard, Cancelled, event_time, TICKS_EPOCH
from speech_priority import PriorityToken, next_event
from sma_voice_stream import Voice, AudioBuffer, parse_event
from enviar_evento import enqueue
from voice_settings import read_settings

class StabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.directory=Path(self.tmp.name)
        self.g=SessionGuard(None,time.time()-100,20,2,45); self.addCleanup(self.g.close)
    def event(self, age, box):
        p=enqueue(self.directory,'a39ba87c-5b0a-4e4a-bdae-4ef1a12f8e10','Name','Testing a line',True)
        if box: p.write_text(p.read_text().rstrip()+'\nbox')
        dest=p.with_name(f'{int((time.time()-age)*1e7)+TICKS_EPOCH:019d}-'+p.stem.split('-',1)[1]+'.evt')
        p.rename(dest); return dest
    def test_fixed_keeps_longer_validity_in_selection_and_begin(self):
        bark=self.event(30,False); box=self.event(29,True)
        self.assertEqual(self.g.eligible(event_time(bark)),'evento expirado')
        self.assertEqual(self.g.eligible(event_time(box),'box'),'')
        self.assertEqual(next_event(self.directory,self.g,parse_event),box)
        self.assertFalse(self.g.begin(event_time(box),'box').is_set())
    def test_fixed_expired_and_old_scene_not_resurrected(self):
        box=self.event(46,True); bark=self.event(1,False)
        self.assertEqual(next_event(self.directory,self.g,parse_event),box) # oldest cleanup, not valid priority
        self.assertTrue(self.g.begin(event_time(box),'box').is_set())
        box.unlink(); box=self.event(10,True)
        with self.g.lock: self.g.state=('manual',1,time.time()-5)
        self.assertEqual(self.g.eligible(event_time(box),'box'),'sessao/cena anterior')
        self.assertTrue(self.g.begin(event_time(box),'box').is_set())
    def token(self):
        t=PriorityToken(self.g.begin(time.time()),self.directory,self.g,parse_event,.01); self.addCleanup(t.close)
        return t
    def test_late_priority_after_natural_drain_does_not_retry(self):
        t=self.token(); v=Voice.__new__(Voice); v.buffer=AudioBuffer(np,100,100); v.output=Mock()
        v.buffer.reset(t); v.buffer.push(np.ones(10,dtype=np.float32)); v.buffer.finish()
        v.buffer.callback(np.zeros((10,1),dtype=np.float32),10,None,None)
        self.assertTrue(v.buffer.drained)
        t.preempted.set(); v.wait_audio(.1,t)
        self.assertTrue(t.completed.is_set()); self.assertFalse(t.should_retry(time.time())); self.assertFalse(t.is_set())
        t.scene.set(); self.assertTrue(t.is_set())
    def test_priority_mid_audio_still_interrupts_and_requeues(self):
        t=self.token(); v=Voice.__new__(Voice); v.buffer=AudioBuffer(np,100,100); v.output=Mock()
        v.buffer.reset(t); v.buffer.push(np.ones(20,dtype=np.float32)); v.buffer.finish()
        out=np.zeros((10,1),dtype=np.float32); v.buffer.callback(out,10,None,None)
        t.preempted.set(); v.buffer.callback(out,10,None,None)
        self.assertFalse(out.any()); self.assertFalse(v.buffer.drained)
        with self.assertRaises(Cancelled): v.wait_audio(.2,t)
        self.assertTrue(t.should_retry(time.time()))
    def test_cache_write_failure_is_not_a_playback_failure(self):
        v=Voice.__new__(Voice); v.rate=100; v.cache=self.directory; v.buffer=AudioBuffer(np,100,100); v.np=np
        v.args=SimpleNamespace(safe_audio=True,mode='stable',box_segment_start=True,box_buffer_ms=100,
            language='pt',source_language='en',model='test',no_translate=False,no_cache=False,
            chunk_size=20,quality='original',speed=1.,sentence_pause_ms=120,voice='a')
        v.speakers={'a':None}; v.set_speaker=lambda name:setattr(v,'speaker_name',name)
        v.stream_chunks=lambda *a,**k: iter([np.ones(100,dtype=np.float32)*.1])
        v.wait_audio=lambda *a: None
        with patch('sma_voice_stream.wave.open',side_effect=PermissionError('cache read-only')):
            self.assertTrue(v.play('Ola, tudo bem?',True,kind='box'))
    def test_new_setting_default_and_custom(self):
        self.assertEqual(read_settings()['IDADE_MAX_CAIXA_FIXA_S'],45)
        p=self.directory/'cfg.txt'; p.write_text('IDADE_MAX_CAIXA_FIXA_S=35\n')
        self.assertEqual(read_settings(p)['IDADE_MAX_CAIXA_FIXA_S'],35)

if __name__=='__main__': unittest.main()
