import sys, unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
from sma_voice_stream import clean_for_voice, synthesis_text, protected_speech_parts, Voice

class BoxPunctuationTests(unittest.TestCase):
    def test_explicit_annotations_and_literals(self):
        self.assertEqual(synthesis_text('Olá, (vírgula) tudo bem. (ponto)'), 'Olá tudo bem')
        self.assertEqual(synthesis_text('Olá [vírgula] tudo bem [ponto].'), 'Olá tudo bem')
        self.assertEqual(synthesis_text('Meu ponto de vista e a vírgula da frase.'), 'Meu ponto de vista e a vírgula da frase')
        self.assertEqual(synthesis_text('Vale 1.234,56, certo?'), 'Vale 1.234,56 certo?')
        self.assertEqual(synthesis_text('... , (ponto)'), '')
    def test_segmentation_still_uses_boundaries(self):
        parts=protected_speech_parts('Esta primeira frase esta completa. A segunda frase continua de forma natural e termina aqui.','pt')
        self.assertGreater(len(parts),1)
        self.assertTrue(parts[0].endswith('.'))
        self.assertFalse(synthesis_text(parts[0]).endswith('.'))
    def test_inference_never_receives_literal_marks_for_both_backends(self):
        class Chunk:
            def detach(self): return self
            def float(self): return self
            def cpu(self): return self
            def numpy(self): return np.linspace(-.2,.2,50,dtype=np.float32)
        for protection in (False,True):
            v=Voice.__new__(Voice); v.rate=100; v.np=np; v.latent=v.embedding=None
            v.args=SimpleNamespace(safe_audio=protection,language='pt',chunk_size=20,quality='original',speed=1.,sentence_pause_ms=120)
            calls=[]
            def infer(text,*args,**kwargs):
                calls.append(text); yield Chunk()
            v.model=SimpleNamespace(inference_stream=infer)
            self.assertTrue(list(v.stream_chunks('Olá, tudo bem. (ponto)')))
            self.assertEqual(calls,['Olá tudo bem'])
    def test_native_alternatives_and_npc_authorization_static(self):
        s=(ROOT/'src/SMAVoiceCapture.cs').read_text()
        for needle in ('StandardUISubtitlePanel','parameters[0].ParameterType.FullName != "PixelCrushers.DialogueSystem.Subtitle"','!object.Equals(player,false) || !object.Equals(npc,true)','bool authorized = subtitle ? authorizedName','HasNpcPanel(path)','SMA BOX_UI_QUEUED','SMA BOX_DISCOVERY','Component concrete = ConcreteText(target)','FreshBoxEvidence(concrete, current','if (!visible && boxEvidence) text = current;','RememberBoxWrite(c, __0)','lock (boxWrites) boxWrites.Remove(id);'):
            self.assertIn(needle,s)
    def test_punctuation_cache_version_static(self):
        s=(ROOT/'runtime/sma_voice_stream.py').read_text()
        self.assertIn('speech-punctuation-v2:',s)
        self.assertIn('Never spell out punctuation names',s)

if __name__=='__main__': unittest.main()
