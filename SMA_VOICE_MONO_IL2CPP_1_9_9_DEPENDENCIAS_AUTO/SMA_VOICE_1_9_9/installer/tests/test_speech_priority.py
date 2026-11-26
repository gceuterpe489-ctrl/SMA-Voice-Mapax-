import sys, tempfile, time, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
from session_guard import SessionGuard, event_time, TICKS_EPOCH, Cancelled, check_cancel
from speech_priority import next_event, PriorityToken, restore_event
from sma_voice_stream import parse_event
from enviar_evento import enqueue
from voice_settings import read_settings

class PriorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir=Path(self.tmp.name)
        self.guard=SessionGuard(None,time.time()-10,20,2); self.addCleanup(self.guard.close)
    def event(self, box=False, text='Testing the dialogue'):
        p=enqueue(self.dir,'a39ba87c-5b0a-4e4a-bdae-4ef1a12f8e10','Name',text,True)
        if box: p.write_text(p.read_text().rstrip()+'\nbox')
        return p
    def select(self, enabled=True): return next_event(self.dir,self.guard,parse_event,enabled)
    def test_box_overtakes_old_bark_and_preserves_fifo(self):
        a=self.event(); b=self.event(True,'First fixed'); c=self.event(True,'Second fixed')
        self.assertEqual(self.select(),b); self.assertEqual(self.select(False),a)
        b.unlink(); self.assertEqual(self.select(),c); c.unlink(); self.assertEqual(self.select(),a)
    def test_new_box_preempts_bark_and_restores_exact_event(self):
        a=self.event(); stamp=event_time(a); data=a.read_bytes(); a.unlink()
        t=PriorityToken(self.guard.begin(stamp),self.dir,self.guard,parse_event,.01); self.addCleanup(t.close)
        b=self.event(True); self.assertTrue(t.wait(.5))
        with self.assertRaises(Cancelled): check_cancel(t)
        t.close(); self.assertTrue(t.should_retry(stamp)); restore_event(a,data)
        self.assertEqual(a.read_bytes(),data); self.assertEqual(event_time(a),stamp)
        self.assertEqual(self.select(),b); b.unlink(); self.assertEqual(self.select(),a)
        self.assertFalse(self.guard.duplicate('a39ba87c-5b0a-4e4a-bdae-4ef1a12f8e10','Testing the dialogue',record=False))
    def test_bark_never_preempts_other_bark(self):
        a=self.event(); t=PriorityToken(self.guard.begin(event_time(a)),self.dir,self.guard,parse_event,.01); self.addCleanup(t.close)
        self.event(); self.assertFalse(t.wait(.06))
    def test_scene_change_wins_over_priority(self):
        a=self.event(); stamp=event_time(a); scene=self.guard.begin(stamp)
        t=PriorityToken(scene,self.dir,self.guard,parse_event,.01); self.addCleanup(t.close)
        self.event(True); self.assertTrue(t.wait(.5)); scene.set()
        self.assertFalse(t.should_retry(stamp))
    def test_expired_invalid_and_duplicate_box_do_not_preempt(self):
        a=self.event(); b=self.event(True); b.rename(b.with_name(f'{int((time.time()-100)*1e7)+TICKS_EPOCH:019d}-expired.evt'))
        self.event(True,'...'); d=self.event(True,'Repeated fixed'); self.guard.duplicate('a39ba87c-5b0a-4e4a-bdae-4ef1a12f8e10','Repeated fixed',kind='box')
        t=PriorityToken(self.guard.begin(event_time(a)),self.dir,self.guard,parse_event,.01); self.addCleanup(t.close)
        self.assertFalse(t.wait(.08))
    def test_expired_interrupted_bark_not_requeued(self):
        a=self.event(); stamp=event_time(a); t=PriorityToken(self.guard.begin(stamp),self.dir,self.guard,parse_event,.01); self.addCleanup(t.close)
        self.event(True); self.assertTrue(t.wait(.5)); self.guard.max_age=-1
        self.assertFalse(t.should_retry(stamp))
    def test_config_optout_and_late_translation_binding(self):
        self.assertTrue(read_settings()['PRIORIDADE_CAIXA_FIXA'])
        p=self.dir/'cfg.txt'; p.write_text('PRIORIDADE_CAIXA_FIXA=false\n'); self.assertFalse(read_settings(p)['PRIORIDADE_CAIXA_FIXA'])
        src=(ROOT/'src/SMAVoiceCapture.cs').read_text()
        for snippet in ('line.ToolkitPointer != native.Pointer','!SameBoxText(original,line.Original)','PublishBoxTranslation(line);','identity.Alias,true,line','line.ToolkitPointer = bodyNative.Pointer'):
            self.assertIn(snippet,src)

if __name__=='__main__': unittest.main()
