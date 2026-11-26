import sys, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'runtime')]
from sma_voice_stream import prepare_spoken, TranslationUnavailable
from session_guard import SessionGuard

class BoxReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.args=SimpleNamespace(no_translate=False,language='pt',source_language='auto',model='test',translation_timeout=25)
    def test_translated_box_never_calls_ollama(self):
        t=Mock(side_effect=AssertionError('unnecessary translation'))
        self.assertEqual(prepare_spoken('Olá!',True,self.args,'box',t),('Olá!','pt',True))
        t.assert_not_called()
    def test_translation_failure_never_speaks_original(self):
        t=Mock(side_effect=TimeoutError('offline'))
        with self.assertRaises(TranslationUnavailable):
            prepare_spoken('Hello!',False,self.args,'box',t)
        self.assertEqual(t.call_count,2)
    def test_empty_translation_never_speaks_source(self):
        self.args.source_language='es'
        with self.assertRaises(TranslationUnavailable):
            prepare_spoken('Hola!',False,self.args,'box',lambda *a:'...')
    def test_successful_translation_keeps_target(self):
        self.assertEqual(prepare_spoken('Hello!',False,self.args,'box',lambda *a:'Olá!'),('Olá!','pt',True))
    def test_bubble_translation_behavior_unchanged(self):
        with self.assertRaises(TimeoutError):
            prepare_spoken('Hello!',False,self.args,'default',Mock(side_effect=TimeoutError()))
    def test_box_duplicate_independent_and_success_only(self):
        g=SessionGuard(None,time.time()-1,20,2)
        try:
            self.assertFalse(g.duplicate('a','Hello'))
            self.assertFalse(g.duplicate('a','Hello',kind='box',record=False))
            self.assertFalse(g.duplicate('a','Hello',kind='box',record=False))
            self.assertFalse(g.duplicate('a','Hello',kind='box'))
            self.assertTrue(g.duplicate('a','Hello',kind='box',record=False))
            self.assertFalse(g.duplicate('b','Hello',kind='box',record=False))
            self.assertTrue(g.duplicate('a','Hello'))
        finally:g.close()
    def test_cancelled_box_not_marked_played(self):
        g=SessionGuard(None,time.time()-1,20,2)
        try:
            token=g.begin(time.time()); token.set()
            self.assertFalse(g.duplicate('a','Hello',kind='box',token=token))
            self.assertFalse(g.duplicate('a','Hello',kind='box',record=False))
        finally:g.close()
    def test_source_contracts_not_game_execution(self):
        s=(ROOT/'src/SMAVoiceCapture.cs').read_text()
        self.assertIn('NativeCapture", true',s)
        self.assertIn('!object.Equals(player,false) || !object.Equals(npc,true)',s)
        self.assertIn('finally { DrainNativeBox(now); }',s)
        self.assertIn('line.Failed=true',s)
        self.assertIn('SMA BOX_ACCEPT native',s)
        self.assertIn('SMA BOX_NATIVE ',s)
        self.assertIn('Path.GetFileNameWithoutExtension(path)',s)
        self.assertIn('GetInstanceID().ToString()',s)

if __name__=='__main__':unittest.main()
