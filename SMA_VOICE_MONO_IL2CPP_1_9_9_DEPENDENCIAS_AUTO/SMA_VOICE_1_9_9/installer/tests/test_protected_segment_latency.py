import sys, tempfile, threading, unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
from sma_voice_stream import Voice, AudioBuffer, protected_speech_parts, protected_segment_enabled, clean_for_voice
from session_guard import Cancelled, BadAudio
from voice_settings import read_settings

TEXT='Esta primeira frase esta completa. A segunda frase continua de forma natural e termina aqui.'

class Chunk:
    def __init__(self,data): self.data=data
    def detach(self): return self
    def float(self): return self
    def cpu(self): return self
    def numpy(self): return self.data

class ProtectedSegmentTest(unittest.TestCase):
    def test_plan_preserves_text(self):
        parts=protected_speech_parts(TEXT,'pt')
        self.assertGreater(len(parts),1)
        self.assertEqual(parts[0],'Esta primeira frase esta completa.')
        self.assertEqual(' '.join(parts),clean_for_voice(TEXT))
        self.assertEqual(protected_speech_parts('Uma frase curta.','pt'),['Uma frase curta.'])
    def test_modes_both_kinds_and_opt_out(self):
        for mode in ('adaptive','stream','stable'):
            args=SimpleNamespace(safe_audio=True,mode=mode,box_segment_start=True,bubble_segment_start=True)
            for kind in ('box','default','bubble','bark'):
                self.assertEqual(protected_segment_enabled(args,kind),mode!='stable')
            args.bubble_segment_start=False
            self.assertFalse(protected_segment_enabled(args,'default'))
        self.assertTrue(read_settings()['INICIO_BALAO_POR_SEGMENTO'])
    def run_voice(self,kind,mode='stream',failure=None):
        with tempfile.TemporaryDirectory() as d:
            v=Voice.__new__(Voice); v.rate=100; v.cache=Path(d); v.buffer=AudioBuffer(np,100,100); v.np=np
            v.args=SimpleNamespace(safe_audio=True,mode=mode,box_segment_start=True,bubble_segment_start=True,box_buffer_ms=100,
                language='pt',source_language='en',model='test',no_translate=False,no_cache=False,chunk_size=20,
                quality='original',speed=1.,sentence_pause_ms=120,voice='a')
            v.speakers={'a':None}; v.latent=v.embedding=None; v.set_speaker=lambda name:setattr(v,'speaker_name',name)
            seen=[]; token=threading.Event(); rng=np.random.default_rng(9); calls=[]
            def infer(part,*a,**kw):
                calls.append(part); i=len(calls); seen.append((i,'begin',v.buffer.active,v.buffer.available))
                yield Chunk(rng.uniform(-.3,.3,120).astype(np.float32))
                seen.append((i,'mid',v.buffer.active,v.buffer.available))
                if i==2 and failure=='bad': yield Chunk(np.full(10,np.nan,dtype=np.float32))
                if i==2 and failure=='cancel': token.set()
                yield Chunk(rng.uniform(-.3,.3,50).astype(np.float32))
            v.model=SimpleNamespace(inference_stream=infer); v.wait_audio=lambda duration,token: None
            if failure:
                with self.assertRaises(BadAudio if failure=='bad' else Cancelled): v.play(TEXT,True,token,kind=kind)
                self.assertEqual(v.buffer.available,0); self.assertFalse(v.buffer.active); self.assertFalse(list(Path(d).glob('*.wav')))
            else:
                self.assertTrue(v.play(TEXT,True,token,kind=kind)); self.assertTrue(list(Path(d).glob('*.wav')))
            return seen
    def test_first_part_validated_before_release_both_kinds(self):
        for kind in ('box','default'):
            seen=self.run_voice(kind)
            self.assertEqual(seen[1],(1,'mid',False,0))
            self.assertEqual(seen[2],(2,'begin',True,170))
            self.assertEqual(seen[3],(2,'mid',True,170))
    def test_invalid_second_part_not_played_or_cached(self):
        seen=self.run_voice('default',failure='bad'); self.assertEqual(seen[-1],(2,'mid',True,170))
    def test_scene_cancel_clears_valid_and_pending_audio(self):
        self.run_voice('box',failure='cancel')
    def test_stable_does_not_release_first_segment(self):
        seen=self.run_voice('box',mode='stable'); self.assertFalse(any(x[2] for x in seen))

if __name__=='__main__': unittest.main()
