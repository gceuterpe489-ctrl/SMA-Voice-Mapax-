import sys, tempfile, threading, time, unittest, base64, json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'runtime')]
from sma_voice_stream import prepare_spoken, resolve_live_box, detect_subtitle_language, TranslationUnavailable, _box_fallback_slot
from session_guard import Cancelled

class BoxLanguageTests(unittest.TestCase):
    def setUp(self):
        self.args=SimpleNamespace(no_translate=False,language='pt',source_language='auto',model='test',translation_timeout=15,sma_language_sync=True)
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'line.boxtr'
    def test_target_echo_is_valid(self):
        t=Mock(return_value='Você está bem?'); v=Mock(return_value='pt')
        self.assertEqual(prepare_spoken('Você está bem?',False,self.args,'box',t,verifier=v),('Você está bem?','pt',True))
        v.assert_called_once(); self.assertLessEqual(v.call_args.args[2],3)
    def test_foreign_echo_is_not_played(self):
        with self.assertRaises(TranslationUnavailable): prepare_spoken('How are you?',False,self.args,'box',Mock(return_value='How are you?'),verifier=Mock(return_value='en'))
    def test_unknown_echo_is_not_played(self):
        with self.assertRaises(TranslationUnavailable): prepare_spoken('OK',False,self.args,'box',Mock(return_value='OK'),verifier=Mock(return_value=None))
    def test_changed_translation_skips_detector(self):
        v=Mock(side_effect=AssertionError('not needed'))
        self.assertEqual(prepare_spoken('Hello',False,self.args,'box',Mock(return_value='Olá'),verifier=v)[0],'Olá'); v.assert_not_called()
    def test_live_echo_accepted(self):
        self.assertEqual(resolve_live_box('Você está bem?',self.args,self.path,translator=Mock(return_value='Você está bem?'),verifier=Mock(return_value='pt'),grace=0),'Você está bem?')
    def test_failed_local_releases_queue_early(self):
        start=time.monotonic()
        with self.assertRaises(TranslationUnavailable): resolve_live_box('Hello',self.args,self.path,translator=Mock(return_value='Hello'),verifier=Mock(return_value='en'),grace=0,failure_grace=.06)
        self.assertLess(time.monotonic()-start,1)
    def test_late_native_still_wins_during_final_wait(self):
        def write(): self.path.write_text(base64.b64encode('Olá'.encode()).decode())
        timer=threading.Timer(.08,write); timer.start()
        try: self.assertEqual(resolve_live_box('Hello',self.args,self.path,translator=Mock(return_value='Hello'),verifier=Mock(return_value='en'),grace=0,failure_grace=.3),'Olá')
        finally: timer.join()
    def test_detector_requires_explicit_certainty(self):
        for payload,expected in [({'language':'pt','certain':True},'pt'),({'language':'pt','certain':False},None),({'language':'unknown','certain':True},None),({'language':'pt','certain':'true'},None)]:
            response=Mock(); response.__enter__=Mock(return_value=response); response.__exit__=Mock(return_value=False)
            response.read.return_value=json.dumps({'message':{'content':json.dumps(payload)}})
            with patch('sma_voice_stream.urllib.request.urlopen',return_value=response): self.assertEqual(detect_subtitle_language('Olá','test',1),expected)
    def test_cancel_during_verification(self):
        token=threading.Event()
        def verify(*a): token.set(); return 'pt'
        with self.assertRaises(Cancelled): prepare_spoken('Olá',False,self.args,'box',Mock(return_value='Olá'),token=token,verifier=verify)

if __name__=='__main__':unittest.main()
