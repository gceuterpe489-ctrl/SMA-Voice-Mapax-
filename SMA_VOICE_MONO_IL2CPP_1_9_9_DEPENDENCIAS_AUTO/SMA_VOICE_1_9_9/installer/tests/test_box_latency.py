import sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'runtime')]
from instalar_portatil import migrate_box_settings
from voice_settings import read_settings
from sma_voice_stream import AudioBuffer, adaptive_start, parse_event
from enviar_evento import enqueue

class BoxLatencyTests(unittest.TestCase):
    def test_upgrade_only_old_box_pair(self):
        old='# keep\r\nDELAY_CAIXA_NORMAL_MS=200\r\nFALLBACK_CAIXA_NORMAL_MS=900\r\nDELAY_BALAO_FLUTUANTE_MS=350\r\nFALLBACK_BALAO_FLUTUANTE_MS=1500\r\nBUFFER_INICIAL_MS=960\r\n'
        new=migrate_box_settings(old)
        self.assertEqual(new, old.replace('NORMAL_MS=200','NORMAL_MS=150').replace('NORMAL_MS=900','NORMAL_MS=500'))
        self.assertEqual(migrate_box_settings(new),new)
        custom=old.replace('NORMAL_MS=900','NORMAL_MS=750')
        self.assertEqual(migrate_box_settings(custom),custom)
        self.assertEqual(migrate_box_settings('DELAY_CAIXA_NORMAL_MS=200\n'), 'DELAY_CAIXA_NORMAL_MS=200\n')

    def test_box_protocol_compatible_with_old_and_generic(self):
        with tempfile.TemporaryDirectory() as d:
            path=enqueue(d,'a39ba87c-5b0a-4e4a-bdae-4ef1a12f8e10','Pessoa','Olá!',True)
            old=parse_event(path)
            self.assertEqual(parse_event(path,True),old+('default',))
            content=path.read_text(encoding='utf-8-sig').rstrip('\r\n')
            path.write_text(content+'\nbox',encoding='utf-8')
            self.assertEqual(parse_event(path,True),old+('box',))
            self.assertEqual(parse_event(path),old)
            path.write_text(content+'\nunknown',encoding='utf-8')
            with self.assertRaises(ValueError): parse_event(path,True)

    def test_box_threshold_does_not_leak_into_next_bubble(self):
        b=AudioBuffer(None,24000,960)
        self.assertEqual(b.threshold,23040)
        b.reset(buffer_ms=500)
        self.assertEqual(b.threshold,12000)
        b.push([0]*11999,allow_start=True); self.assertFalse(b.active)
        b.push([0],allow_start=True); self.assertTrue(b.active)
        b.reset(); self.assertEqual(b.threshold,23040); self.assertFalse(b.active)
        b.push([0]*12000,allow_start=True); self.assertFalse(b.active)
        b.reset(buffer_ms=1500); self.assertEqual(b.threshold,23040)
        b=AudioBuffer(None,24000,350); b.reset(buffer_ms=500); self.assertEqual(b.threshold,8400)

    def test_adaptive_still_requires_sufficient_generation(self):
        # same 0.5 seconds of PCM: early start only when fast enough
        self.assertTrue(adaptive_start('adaptive',12000,24000,12000,.3,.2,6000))
        self.assertFalse(adaptive_start('adaptive',12000,24000,12000,1.0,.8,6000))
        self.assertFalse(adaptive_start('adaptive',12000,24000,23040,.3,.2,6000))
        self.assertFalse(adaptive_start('stable',12000,24000,12000,.3,.2,6000))

    def test_new_setting_defaults_and_validation(self):
        settings=read_settings(ROOT/'config/CONFIGURACOES.txt')
        self.assertEqual((settings['DELAY_CAIXA_NORMAL_MS'],settings['FALLBACK_CAIXA_NORMAL_MS'],settings['BUFFER_CAIXA_NORMAL_MS']),(150,500,500))
        self.assertEqual((settings['DELAY_BALAO_FLUTUANTE_MS'],settings['FALLBACK_BALAO_FLUTUANTE_MS'],settings['BUFFER_INICIAL_MS']),(350,1500,960))
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'config.txt'; p.write_text('BUFFER_INICIAL_MS=600\n')
            self.assertEqual(read_settings(p)['BUFFER_CAIXA_NORMAL_MS'],500)
            p.write_text('BUFFER_CAIXA_NORMAL_MS=99\n')
            with self.assertRaises(ValueError): read_settings(p)

if __name__=='__main__': unittest.main()
