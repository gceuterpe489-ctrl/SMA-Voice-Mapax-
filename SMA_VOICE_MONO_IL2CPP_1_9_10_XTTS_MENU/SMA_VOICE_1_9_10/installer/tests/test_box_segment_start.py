import sys, tempfile, threading, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'runtime')]
from sma_voice_stream import Voice, AudioBuffer, box_speech_parts, box_segment_enabled, clean_for_voice, split_for_voice
from voice_settings import read_settings
from session_guard import Cancelled

TEXT='Esta primeira frase tem uma pausa natural para a personagem falar. A segunda frase continua com o restante da conversa sem perder nenhuma palavra. E esta é a última parte.'

class BoxSegmentTests(unittest.TestCase):
    def test_natural_split_preserves_text(self):
        parts=box_speech_parts(TEXT,'pt')
        self.assertEqual(parts[0], 'Esta primeira frase tem uma pausa natural para a personagem falar.')
        self.assertEqual(' '.join(parts),clean_for_voice(TEXT))
        self.assertGreater(len(parts),1)
    def test_long_no_punctuation_word_boundary(self):
        text=' '.join(['palavra%d'%i for i in range(30)])
        parts=box_speech_parts(text,'pt')
        self.assertLessEqual(len(parts[0]),105)
        self.assertEqual(' '.join(parts),text)
    def test_short_and_cjk(self):
        self.assertEqual(box_speech_parts('Hola, ¿cómo estás?','es'),['Hola, ¿cómo estás?'])
        text='これは長い会話の最初の文章です。'+'この文章は会話の続きを表しています。'*5
        self.assertEqual(''.join(box_speech_parts(text,'ja')),text)
    def test_mode_and_kind(self):
        for mode in ('adaptive','stream','stable'):
            for kind in ('box','default','bubble'):
                self.assertEqual(box_segment_enabled(SimpleNamespace(mode=mode),kind),mode=='adaptive' and kind=='box')
        self.assertFalse(box_segment_enabled(SimpleNamespace(mode='adaptive',box_segment_start=False),'box'))
    def test_threshold_and_cancellation(self):
        b=AudioBuffer(None,24000,500); b.push([0]*11999)
        self.assertFalse(b.start_if_ready()); b.push([0]); self.assertTrue(b.start_if_ready())
        t=threading.Event(); b.reset(t); b.push([0]*12000); t.set()
        self.assertFalse(b.start_if_ready())
    def test_existing_config_default_and_opt_out(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'cfg.txt'; p.write_text('MODO_REPRODUCAO=adaptive\n')
            self.assertTrue(read_settings(p)['INICIO_CAIXA_POR_SEGMENTO'])
            p.write_text('INICIO_CAIXA_POR_SEGMENTO=false\n')
            self.assertFalse(read_settings(p)['INICIO_CAIXA_POR_SEGMENTO'])
    def run_play(self,kind='box',mode='adaptive',enabled=True,cancel=False):
        # Simulate slow synthesis (one second of audio per two seconds of computation).
        # No XTTS weights, GPU, numpy, sound device, or wall-clock sleeps needed.
        with tempfile.TemporaryDirectory() as d:
            v=Voice.__new__(Voice); v.rate=100; v.cache=Path(d); v.buffer=AudioBuffer(None,100,960)
            v.args=SimpleNamespace(mode=mode,box_segment_start=enabled,box_buffer_ms=500,
                language='es',source_language='en',model='test',no_translate=False,no_cache=True,
                chunk_size=20,quality='original',speed=1.0,sentence_pause_ms=120,voice='a')
            v.speakers={'a':None}; v.set_speaker=lambda name:setattr(v,'speaker_name',name)
            seen=[]; clock=[0.]; token=threading.Event()
            def stream(text,language=None,parts=None,on_part_complete=None):
                actual=parts or list(split_for_voice(text))
                for i,part in enumerate(actual):
                    seen.append((i,part,language,v.buffer.active))
                    clock[0]+=2.; yield [0.1]*100
                    if on_part_complete: on_part_complete(i)
                    if cancel and i==0: token.set()
            v.stream_chunks=stream
            v.wait_audio=lambda duration,token: None
            with patch('sma_voice_stream.time.perf_counter',side_effect=lambda:clock[0]):
                if cancel:
                    with self.assertRaises(Cancelled): v.play(TEXT,True,token,kind=kind)
                    self.assertFalse(v.buffer.active)
                else: self.assertTrue(v.play(TEXT,True,token,kind=kind))
            return seen
    def test_slow_box_plays_before_second_segment(self):
        seen=self.run_play()
        self.assertFalse(seen[0][3]); self.assertTrue(seen[1][3])
        self.assertTrue(all(row[2]=='es' for row in seen))
        self.assertEqual(' '.join(row[1] for row in seen),TEXT)
    def test_bubble_stable_and_opt_out_never_force_early_start(self):
        for kind,mode,enabled in [('bubble','adaptive',True),('box','stable',True),('box','adaptive',False)]:
            seen=self.run_play(kind,mode,enabled)
            self.assertFalse(any(row[3] for row in seen))
    def test_scene_cancel_during_segment(self):
        self.run_play(cancel=True)

if __name__=='__main__': unittest.main()
