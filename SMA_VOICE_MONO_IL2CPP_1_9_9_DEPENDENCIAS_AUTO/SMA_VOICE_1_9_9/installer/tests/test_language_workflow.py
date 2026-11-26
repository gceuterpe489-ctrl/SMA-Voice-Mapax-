import sys, unittest, tempfile, json, threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'runtime')]
from voice_language import read_config, resolve_session_language, audio_cache_key
from sma_voice_stream import prepare_spoken, TranslationUnavailable
from session_guard import Cancelled

class LanguageWorkflow(unittest.TestCase):
    def args(self, lang, source='en', disabled=False, sma=True):
        return SimpleNamespace(language=lang,source_language=source,no_translate=disabled,sma_language_sync=sma,model='test',translation_timeout=2)
    def test_config_read_only_and_translator_wins_in_sma(self):
        with tempfile.TemporaryDirectory() as d:
            q=Path(d)/'BepInEx/SMA-Voice-Queue'; q.mkdir(parents=True)
            p=q.parent/'plugins/UnityGameTranslator/config.json'; p.parent.mkdir(parents=True)
            original=json.dumps({'target_language':'es-ES','source_language':'en'})
            p.write_text(original); cfg,found=read_config(q)
            self.assertEqual(found,p)
            self.assertEqual(resolve_session_language(cfg,'pt',sma=True),'es')
            self.assertEqual(resolve_session_language(cfg,'pt',sma=False),'pt')
            self.assertEqual(p.read_text(),original)
    def test_auto_and_unsupported_language(self):
        self.assertEqual(resolve_session_language({'target_language':'auto'},'pt',sma=True,system='fr-FR'),'fr')
        with self.assertRaises(ValueError): resolve_session_language({'target_language':'xx'},'pt',sma=True)
    def test_ready_translation_no_second_translation_any_language(self):
        for lang,text in [('pt','Olá'),('es','Hola'),('fr','Bonjour'),('ja','こんにちは'),('en','Hello')]:
            for kind in ('box','default'):
                t=Mock(side_effect=AssertionError('no second translation'))
                self.assertEqual(prepare_spoken(text,True,self.args(lang),kind,t),(text,lang,True))
                t.assert_not_called()
    def test_fallback_uses_target_and_retries(self):
        t=Mock(side_effect=[ValueError('empty'),'Bonjour'])
        self.assertEqual(prepare_spoken('Hello',False,self.args('fr'),'box',t),('Bonjour','fr',True))
        self.assertEqual([c.args[2] for c in t.call_args_list],['fr','fr'])
        self.assertLessEqual(t.call_args_list[1].args[3],t.call_args_list[0].args[3])
    def test_verbatim_echo_not_spoken(self):
        with self.assertRaises(TranslationUnavailable): prepare_spoken('Hello',False,self.args('es'),'box',lambda *a:'Hello')
    def test_translation_disabled_cannot_bypass_sma_target(self):
        for kind in ('box','default'):
            with self.assertRaises(TranslationUnavailable): prepare_spoken('Hello',False,self.args('pt',disabled=True),kind)
            self.assertEqual(prepare_spoken('Hola',True,self.args('es',disabled=True),kind),('Hola','es',True))
        self.assertEqual(prepare_spoken('Hello',False,self.args('en',disabled=True),'box'),('Hello','en',True))
        self.assertEqual(prepare_spoken('Hello',False,self.args('pt',disabled=True,sma=False)),('Hello','pt',True))
    def test_cancelled_scene_stops_retry(self):
        token=threading.Event()
        def translation(*a): token.set(); raise TimeoutError()
        with self.assertRaises(Cancelled): prepare_spoken('Hello',False,self.args('fr'),'box',translation,token)
    def test_cache_isolated_by_language(self):
        args=('Hello','test','voice',False,True,20)
        self.assertNotEqual(audio_cache_key(*args,'es','en'),audio_cache_key(*args,'pt','en'))
    def test_capture_no_portuguese_gate_and_legacy_protocol(self):
        source=(ROOT/'src/SMAVoiceCapture.cs').read_text()
        self.assertNotIn('translatorPortuguese',source)
        self.assertIn('translated ? "pt-ready" : "translate"',source)

if __name__=='__main__':unittest.main()
