import unittest, tempfile, sys, types, json, runpy
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
from voice_settings import read_settings,inference_options,SPEC
from session_guard import SessionGuard
from enviar_evento import enqueue
from sma_voice_stream import parse_event, Voice
sys.path.insert(0,str(ROOT))
import instalar_portatil

class SettingsTest(unittest.TestCase):
    def test_defaults(self):
        cfg=read_settings(ROOT/'config/CONFIGURACOES.txt')
        self.assertEqual(cfg, {**{k:v[0] for k,v in SPEC.items()},'MODELO_OLLAMA':'qwen3:4b-instruct'})
        self.assertEqual(cfg['BUFFER_INICIAL_MS'],960)
        self.assertEqual(cfg['DELAY_BALAO_FLUTUANTE_MS'],350)
        self.assertEqual(cfg['FALLBACK_BALAO_FLUTUANTE_MS'],1500)
        self.assertEqual(inference_options('original',1.0),{})
    def test_edit_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'cfg.txt'; p.write_text('CACHE_AUDIO=false\nVELOCIDADE_VOZ=1.15\nIDIOMA=pt-BR\nDELAY_CAIXA_NORMAL_MS=150\n')
            cfg=read_settings(p); self.assertFalse(cfg['CACHE_AUDIO']); self.assertEqual(cfg['IDIOMA'],'pt'); self.assertEqual(cfg['VELOCIDADE_VOZ'],1.15)
            self.assertEqual(inference_options('consistent',1.15),{'temperature':.60,'top_p':.80,'speed':1.15})
            for invalid in ['BUFFER_INICIAL_MS=99','VELOCIDADE_VOZ=NaN','TRADUCAO=talvez','XXX=1','CACHE_AUDIO=true\nCACHE_AUDIO=false','IDIOMA=xx','DISPOSITIVO_AUDIO=-1']:
                p.write_text(invalid)
                with self.assertRaises(ValueError): read_settings(p)
    def test_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            uid='a39ba87c-5b0a-4e4a-bdae-4ef1a12f8e10'
            event=enqueue(tmp,uid,'Pessoa','Olá!',True)
            actor,text,ready,name,alias=parse_event(event)
            self.assertEqual((actor,text,ready,name),(uid,'Olá!',True,'Pessoa'))
    def test_dedup(self):
        import time
        for interval,expected in [(0,False),(2,True)]:
            guard=SessionGuard(None,time.time(),20,interval)
            try:
                self.assertFalse(guard.duplicate('a','teste')); self.assertEqual(guard.duplicate('a','teste'),expected)
            finally: guard.close()
    def test_stream_options(self):
        # Substitute a lightweight fake model, no weights/audio device required.
        class NumpyStub:
            float32='float32'
            def zeros(self,*a,**k): return []
        model=types.SimpleNamespace(); seen=[]
        def infer(*args,**kwargs):
            seen.append(kwargs); return iter(())
        model.inference_stream=infer
        voice=Voice.__new__(Voice); voice.model=model; voice.np=NumpyStub(); voice.rate=24000; voice.latent=None; voice.embedding=None
        voice.args=types.SimpleNamespace(language='pt',chunk_size=20,quality='expressive',speed=1.1,sentence_pause_ms=120)
        list(voice.stream_chunks('Ola, tudo bem?'))
        self.assertEqual(seen[0]['speed'],1.1); self.assertEqual(seen[0]['temperature'],.85); self.assertEqual(seen[0]['stream_chunk_size'],20)
    def test_launcher_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); runtime=root/'.sma-voice'; runtime.mkdir()
            (runtime/'iniciar.py').write_bytes((ROOT/'runtime/iniciar.py').read_bytes())
            settings=root/'plugins/SMA Voice/CONFIGURACOES.txt'; settings.parent.mkdir(parents=True); settings.touch()
            (runtime/'instalacao.json').write_text(json.dumps({'mode':'generic','queue':'.sma-voice/SMA-Voice-Queue','settings':'plugins/SMA Voice/CONFIGURACOES.txt','model_dir':None}))
            with patch('sys.argv',['iniciar.py','--test']),patch('subprocess.call',return_value=0) as call:
                with self.assertRaises(SystemExit) as err: runpy.run_path(str(runtime/'iniciar.py'),run_name='__main__')
                self.assertEqual(err.exception.code,0)
                args=call.call_args.args[0]
                self.assertEqual(args[args.index('--settings')+1],str(root/'plugins/SMA Voice/CONFIGURACOES.txt'))
                self.assertEqual(args[-1],'--test')
    def test_documents_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs=Path(tmp)/'OneDrive'/'Documentos'
            with patch('voice_storage.documents',return_value=docs):
                self.assertEqual(instalar_portatil.runtime_path(),docs/'TValle Games/Some Modeling Agency/SMA Voice')
    def test_external_runtime_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'Game Drive'/'Projeto'; runtime=Path(tmp)/'Documentos/TValle Games/Some Modeling Agency/SMA Voice'
            runtime.mkdir(parents=True)
            settings=root/'plugins/SMA Voice/CONFIGURACOES.txt'; settings.parent.mkdir(parents=True); settings.touch()
            for mode in ('generic','sma'):
                queue=runtime/'SMA-Voice-Queue' if mode=='generic' else root/'BepInEx/SMA-Voice-Queue'
                (runtime/'iniciar.py').write_bytes((ROOT/'runtime/iniciar.py').read_bytes())
                (runtime/'instalacao.json').write_text(json.dumps({'mode':mode,'project_root':str(root),'queue':str(queue),'settings':str(settings),'model_dir':None}))
                with patch('sys.argv',['iniciar.py']),patch('subprocess.call',return_value=0) as call:
                    with self.assertRaises(SystemExit): runpy.run_path(str(runtime/'iniciar.py'),run_name='__main__')
                    args=call.call_args.args[0]; env=call.call_args.kwargs['env']
                    self.assertEqual(args[args.index('--queue')+1],str(queue))
                    self.assertEqual(args[args.index('--settings')+1],str(settings))
                    self.assertEqual(env['SMA_VOICE_DATA'],str(runtime/'dados' if mode=='generic' else runtime))
                    self.assertEqual(env.get('SMA_VOICE_GENERIC'), '1' if mode=='generic' else None)
            backup=runtime/'backups/test'
            self.assertEqual(instalar_portatil.backup_path(settings,runtime,root,backup),backup/'projeto/plugins/SMA Voice/CONFIGURACOES.txt')
            self.assertEqual(instalar_portatil.backup_path(runtime/'iniciar.py',runtime,root,backup),backup/'runtime/iniciar.py')
    def test_legacy_data_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=Path(tmp)/'old/.sma-voice'; new=Path(tmp)/'new/SMA Voice'
            for sub in ('dados','voice_cache_v12','xtts','SMA-Voice-Queue'):
                (old/sub).mkdir(parents=True); (old/sub/'original').write_text('old')
            (new/'dados').mkdir(parents=True); (new/'dados/original').write_text('new')
            instalar_portatil.import_legacy_data(old,new,'generic')
            self.assertEqual((new/'dados/original').read_text(),'new')
            self.assertEqual((new/'voice_cache_v12/original').read_text(),'old')
            self.assertTrue((old/'voice_cache_v12/original').is_file())
            self.assertFalse((new/'xtts').exists()); self.assertFalse((new/'SMA-Voice-Queue').exists())
if __name__=='__main__': unittest.main()
