import base64, sys, tempfile, threading, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'runtime')]
from sma_voice_stream import resolve_live_box, parse_event, read_box_translation, purge_box_updates, _box_fallback_slot, TranslationUnavailable
from session_guard import Cancelled
from enviar_evento import enqueue

class LiveBoxTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'line.boxtr'
        self.args=SimpleNamespace(no_translate=False,language='es',source_language='en',model='test',translation_timeout=.8,sma_language_sync=True)
    def write(self,text):
        temp=self.path.with_suffix('.tmp'); temp.write_text(base64.b64encode(text.encode()).decode()); temp.replace(self.path)
    def test_native_available_no_ollama(self):
        self.write('Hola, ¿cómo estás?'); t=Mock(side_effect=AssertionError('unnecessary'))
        self.assertEqual(resolve_live_box('Hello',self.args,self.path,translator=t),'Hola, ¿cómo estás?'); t.assert_not_called()
    def test_native_arrives_during_local_request(self):
        started=threading.Event(); release=threading.Event()
        def translator(*args):
            started.set(); release.wait(1); return 'Traducción local'
        def writer():
            if started.wait(.5): self.write('Traducción del juego')
        thread=threading.Thread(target=writer); thread.start()
        try:
            self.assertEqual(resolve_live_box('Hello',self.args,self.path,translator=translator,grace=0),'Traducción del juego')
            self.assertTrue(started.is_set())
        finally:
            release.set(); thread.join(); self.assertTrue(_box_fallback_slot.acquire(timeout=1)); _box_fallback_slot.release()
    def test_local_can_win_when_native_missing(self):
        t=Mock(return_value='Hola')
        self.assertEqual(resolve_live_box('Hello',self.args,self.path,translator=t,grace=0),'Hola')
        self.assertEqual(t.call_args.args[2],'es')
    def test_no_local_translation_still_receives_native(self):
        self.args.no_translate=True; t=Mock(side_effect=AssertionError('disabled'))
        timer=threading.Timer(.04,lambda:self.write('Hola')); timer.start()
        try: self.assertEqual(resolve_live_box('Hello',self.args,self.path,translator=t,grace=0),'Hola')
        finally: timer.join()
        t.assert_not_called()
    def test_timeout_never_returns_source(self):
        self.args.translation_timeout=.06
        with self.assertRaises(TranslationUnavailable): resolve_live_box('Hello',self.args,self.path,translator=lambda *a:'Hello',grace=0)
    def test_scene_cancellation(self):
        token=threading.Event(); token.set()
        with self.assertRaises(Cancelled): resolve_live_box('Hello',self.args,self.path,token,translator=Mock())
    def test_invalid_sidecar_ignored(self):
        self.path.write_text('invalid base64!'); self.assertIsNone(read_box_translation(self.path))
    def test_protocol_old_and_new(self):
        p=enqueue(self.temp.name,'a39ba87c-5b0a-4e4a-bdae-4ef1a12f8e10','Name','Hello',False)
        old=p.read_text().rstrip('\r\n')
        self.assertEqual(parse_event(p,True,True)[-2:],('default',False))
        p.write_text(old+'\nbox\ntranslation-update')
        self.assertEqual(parse_event(p,True,True)[-2:],('box',True))
        self.assertEqual(parse_event(p,True)[-1],'box')
        p.write_text(old+'\nbox\ninvalid')
        with self.assertRaises(ValueError): parse_event(p,True,True)
    def test_cleanup_only_old_sidecars(self):
        p=Path(self.temp.name)/'0000000000000000000-abc.boxtr'; p.write_text('x')
        untouched=p.with_suffix('.evt'); untouched.write_text('x')
        self.write('Hola'); purge_box_updates(self.path.parent,20)
        self.assertFalse(p.exists()); self.assertTrue(untouched.exists()); self.assertTrue(self.path.exists())
    def test_capture_update_contract(self):
        source=(ROOT/'src/SMAVoiceCapture.cs').read_text()
        self.assertIn('SameBoxText(original,line.Original)',source)
        self.assertIn('Path.ChangeExtension(line.EventPath,".boxtr")',source)
        self.assertIn('if (liveTranslation) payload += "\\ntranslation-update";',source)
        self.assertIn('if (line.Sent) { PublishBoxTranslation(line); continue; }',source)

if __name__=='__main__':unittest.main()
