import sys, tempfile, threading, unittest, json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'runtime')]
from sma_voice_stream import Voice, AudioBuffer, RepeatedPCM
from session_guard import BadAudio, Cancelled, usable_text
from voice_settings import read_settings
from iniciar import command

class AudioRecoveryTests(unittest.TestCase):
    def test_mixed_repeated_letters(self):
        for text in ('a, a, aaaaaaa','A A aaA','a a a a'):
            self.assertFalse(usable_text(text))
        self.assertTrue(usable_text('A casa fica ali.'))
        self.assertTrue(usable_text('Ah, eu entendo.'))
    def test_exact_loop_across_chunks_and_silence(self):
        detector=RepeatedPCM(np,100)
        repeated=np.tile(np.linspace(-.5,.5,25,dtype=np.float32),4)
        detector.feed(repeated[:31]); detector.feed(repeated[31:74])
        with self.assertRaises(BadAudio): detector.feed(repeated[74:])
        detector=RepeatedPCM(np,100); detector.feed(np.zeros(500,dtype=np.float32))
        detector.feed(np.random.default_rng(1).normal(0,.1,200).astype(np.float32))
    def test_cancel_buffer_and_no_resurrection(self):
        b=AudioBuffer(np,100,100); token=threading.Event(); b.reset(token)
        b.push(np.ones(25,dtype=np.float32),allow_start=True)
        out=np.zeros((10,1),dtype=np.float32); b.callback(out,10,None,None)
        self.assertEqual(b.offset,10); token.set(); b.callback(out,10,None,None)
        self.assertFalse(out.any()); self.assertEqual(b.offset,0); self.assertTrue(b.done.is_set())
        b.push(np.ones(20),allow_start=True); self.assertEqual(b.available,0)
        b.reset(); b.push(np.ones(20),allow_start=True); b.callback(out,10,None,None); self.assertTrue(out.all())
    def test_reset_device_discards_old_pcm(self):
        v=Voice.__new__(Voice); v.buffer=AudioBuffer(np,100,100); v.output=Mock()
        v.buffer.push(np.ones(50),allow_start=True); v.recover_output('test')
        self.assertEqual(v.buffer.available,0); self.assertTrue(v.buffer.done.is_set())
        v.output.abort.assert_called_once(); v.output.start.assert_called_once()
    def test_protected_mode_buffers_entire_utterance(self):
        with tempfile.TemporaryDirectory() as d:
            v=Voice.__new__(Voice); v.rate=100; v.cache=Path(d); v.buffer=AudioBuffer(np,100,100); v.np=np
            v.args=SimpleNamespace(safe_audio=True,mode='adaptive',box_segment_start=True,box_buffer_ms=100,
                language='pt',source_language='en',model='test',no_translate=False,no_cache=True,
                chunk_size=20,quality='original',speed=1.,sentence_pause_ms=120,voice='a')
            v.speakers={'a':None}; v.set_speaker=lambda name:setattr(v,'speaker_name',name)
            seen=[]; token=threading.Event()
            def stream(text,language=None,token=None):
                for _ in range(3):
                    seen.append(v.buffer.active); yield np.ones(100,dtype=np.float32)*.1
            v.stream_chunks=stream
            v.wait_audio=lambda duration,token: seen.append(v.buffer.active)
            self.assertTrue(v.play('Ola, tudo bem?',True,token,kind='box'))
            self.assertEqual(seen,[False,False,False,True])
    def test_part_limit_and_generator_close(self):
        class Chunk:
            def detach(self): return self
            def float(self): return self
            def cpu(self): return self
            def numpy(self): return np.random.default_rng(2).normal(0,.1,900).astype(np.float32)
        v=Voice.__new__(Voice); v.rate=100; v.np=np; v.latent=v.embedding=None
        v.args=SimpleNamespace(safe_audio=True,language='pt',chunk_size=20,quality='original',speed=1.,sentence_pause_ms=120)
        closed=[]
        def infer(*args,**kwargs):
            try: yield Chunk()
            finally: closed.append(True)
        v.model=SimpleNamespace(inference_stream=infer)
        with self.assertRaises(BadAudio): list(v.stream_chunks('Ola!'))
        self.assertEqual(closed,[True])
    def test_launch_backend_and_default_optout(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); settings=base/'settings.txt'; settings.write_text('PROTEGER_AUDIO_IL2CPP=false\n')
            self.assertFalse(read_settings(settings)['PROTEGER_AUDIO_IL2CPP']); self.assertTrue(read_settings()['PROTEGER_AUDIO_IL2CPP'])
            cfg={'mode':'sma','queue':'queue','settings':'settings.txt','project_root':str(base),'unity_backend':'IL2CPP'}
            (base/'instalacao.json').write_text(json.dumps(cfg)); self.assertEqual(command(base,[])[1]['SMA_VOICE_IL2CPP'],'1')
            cfg['unity_backend']='Mono'; (base/'instalacao.json').write_text(json.dumps(cfg)); self.assertNotIn('SMA_VOICE_IL2CPP',command(base,[])[1])

if __name__=='__main__': unittest.main()
