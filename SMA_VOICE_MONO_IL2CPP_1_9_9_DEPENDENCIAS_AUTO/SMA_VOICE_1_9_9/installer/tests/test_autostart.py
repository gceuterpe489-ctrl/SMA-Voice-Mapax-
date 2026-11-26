import contextlib, io, json, os, sys, tempfile, types, unittest
from pathlib import Path
from unittest.mock import patch, Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'runtime')]
import instalar_portatil as installer
import iniciar
from session_guard import marker_state, SessionGuard, TICKS_EPOCH

class AutoStartTests(unittest.TestCase):
    def test_source_only_build(self):
        self.assertTrue((ROOT/'src/SMAVoiceCapture.cs').is_file())
        self.assertTrue((ROOT/'src/SMAVoiceAutoStart.cs').is_file())
        self.assertNotIn("bundled_dll('SMAVoiceCapture.dll')",(ROOT/'instalar_portatil.py').read_text())

    def test_cfg_edit_preserves_other_sections(self):
        old='## comment\r\n[Startup]\r\nEnabled = false\r\n\r\n[Audio]\r\nAnnounce = false\r\nBufferMs = 500\r\n'
        self.assertEqual(installer.config_value(old,'Startup','Enabled','true'),old.replace('Enabled = false','Enabled = true'))
        self.assertIn('[Startup]\nEnabled = true',installer.config_value('','Startup','Enabled','true'))
        capture='[BarkFilter]\nCaptureSource = Subtitle\nAllowedSpeakerNames = A|B\n'
        self.assertEqual(installer.config_value(capture,'BarkFilter','CaptureSource','Hybrid','diagnostic'),capture)
        self.assertEqual(installer.config_value(capture.replace('Subtitle','Diagnostic'),'BarkFilter','CaptureSource','Hybrid','diagnostic'),capture.replace('Subtitle','Hybrid'))

    def fixture(self,base):
        runtime=base/'OneDrive Documentos'/'SMA Voice'; root=base/'Jogo com espaços'; runtime.mkdir(parents=True)
        queue=root/'BepInEx/SMA-Voice-Queue'; queue.mkdir(parents=True)
        central=root/'BepInEx/plugins/SMAVoiceCapture/CONFIGURACOES.txt'; central.parent.mkdir(parents=True); central.touch()
        cfg={'mode':'sma','project_root':str(root),'queue':str(queue),'settings':str(central),'model_dir':str(base/'modelo local')}
        (runtime/'instalacao.json').write_text(json.dumps(cfg)); return runtime,root,queue,central

    def test_autostart_same_process_and_settings(self):
        with tempfile.TemporaryDirectory() as d:
            runtime,root,queue,central=self.fixture(Path(d)); marker=queue/'session-a.state'
            with patch('runpy.run_path') as run,patch('subprocess.call') as child,patch.dict(os.environ,{},clear=False),patch.object(sys,'argv',['iniciar.py']):
                def inspect_run(*args,**kwargs):
                    self.assertEqual(Path(args[0]),runtime/'sma_voice_stream.py')
                    self.assertEqual(sys.argv[sys.argv.index('--settings')+1],str(central))
                    self.assertEqual(sys.argv[sys.argv.index('--queue')+1],str(queue))
                    self.assertEqual(sys.argv[sys.argv.index('--session-file')+1],str(marker))
                    self.assertEqual(os.environ['SMA_XTTS_MODEL_DIR'],str(Path(d)/'modelo local'))
                    self.assertEqual(os.environ['SMA_VOICE_DATA'],str(runtime))
                    print('PRONTO',flush=True)
                run.side_effect=inspect_run
                self.assertEqual(iniciar.main(runtime,['--autostart-root',str(root),'--game-pid','123','--session-file',str(marker)]),0)
                child.assert_not_called(); run.assert_called_once()
            self.assertIn('PRONTO',(runtime/'voice.log').read_text())

    def test_wrong_game_rejected_and_logged(self):
        with tempfile.TemporaryDirectory() as d:
            runtime,root,queue,central=self.fixture(Path(d))
            with patch('runpy.run_path') as run:
                self.assertEqual(iniciar.main(runtime,['--autostart-root',str(root/'other')]),1)
                run.assert_not_called()
            self.assertIn('nao e o projeto ativo',(runtime/'voice.log').read_text())

    def test_session_reset_cancels_audio(self):
        import time
        with tempfile.TemporaryDirectory() as d:
            marker=Path(d)/'session.state'; stamp=time.time(); ticks=int(stamp*10_000_000)+TICKS_EPOCH
            marker.write_text(f'abc\n0\n{ticks}\n'); guard=SessionGuard(marker,stamp)
            try:
                token=guard.begin(stamp+.01); self.assertFalse(token.is_set())
                marker.write_text(f'abc\n1\n{ticks+10_000_000}\n'); guard.refresh()
                self.assertTrue(token.is_set()); self.assertEqual(guard.eligible(stamp+.01),'sessao/cena anterior')
            finally: guard.close()

    def test_transaction_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); runtime=base/'runtime'; root=base/'game'; runtime.mkdir(); root.mkdir()
            old=root/'old.dll'; old.write_bytes(b'old'); fresh=root/'fresh'; duplicate=root/'duplicate'; duplicate.write_bytes(b'dupe')
            backup=runtime/'backups/test'; original_replace=Path.replace
            def fail_once(src,dst):
                if dst==fresh: raise OSError('simulated disk error')
                return original_replace(src,dst)
            with patch.object(Path,'replace',fail_once):
                with self.assertRaises(OSError): installer.install_files({old:b'new',fresh:b'fresh'},[duplicate],runtime,root,backup)
            self.assertEqual(old.read_bytes(),b'old'); self.assertEqual(duplicate.read_bytes(),b'dupe'); self.assertFalse(fresh.exists())
            self.assertEqual((backup/'projeto/old.dll').read_bytes(),b'old')

    def test_install_sma_simulation(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); root=base/'Game'; root.mkdir(); runtime=base/'OneDrive'/'Documentos'/'SMA Voice'
            for rel in ('Some Modeling Agency.exe','BepInEx/core/BepInEx.dll','BepInEx/core/0Harmony.dll','Some Modeling Agency_Data/Managed/UnityEngine.CoreModule.dll','BepInEx/plugins/old/SMAVoiceAutoStart.dll'):
                p=root/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b'old')
            cfg=root/'BepInEx/config/local.sma.voiceautostart.cfg'; cfg.parent.mkdir(); cfg.write_text('[Startup]\nEnabled = false\n[Audio]\nAnnounce = false\n')
            fake_python=base/'Python env/python.exe'; fake_python.parent.mkdir(); fake_python.touch()
            def compile_stub(src,out,refs): out.write_bytes(b'MZ'+src.stem.encode())
            with patch.object(installer,'os',types.SimpleNamespace(name='nt',environ={})),patch.object(installer,'ensure_game_dependencies',return_value=False),patch.object(installer,'runtime_path',return_value=runtime),patch.object(installer,'choose_environment',return_value=(fake_python,'auto')),patch.object(installer,'compile_dll',side_effect=compile_stub) as compiler,patch('subprocess.run',return_value=types.SimpleNamespace(stdout='')),patch('sma_voice_stream.lock_queue',return_value=Mock()),patch('builtins.input',side_effect=['SMA',str(root),'','']),patch.object(sys,'argv',['instalar_portatil.py']),contextlib.redirect_stdout(io.StringIO()):
                installer.main()
            self.assertEqual(compiler.call_count,2)
            self.assertEqual([c.args[0].name for c in compiler.call_args_list],['SMAVoiceAutoStart.cs','SMAVoiceCapture.cs'])
            self.assertIn(root/'BepInEx/core/0Harmony.dll',compiler.call_args.args[2])
            self.assertEqual((root/'BepInEx/plugins/SMAVoiceCapture/SMAVoiceCapture.dll').read_bytes(),b'MZSMAVoiceCapture')
            self.assertEqual((root/'BepInEx/plugins/SMAVoiceAutoStart/SMAVoiceAutoStart.dll').read_bytes(),b'MZSMAVoiceAutoStart')
            self.assertFalse((root/'BepInEx/plugins/old/SMAVoiceAutoStart.dll').exists())
            self.assertEqual(list(runtime.glob('backups/*/projeto/BepInEx/plugins/old/SMAVoiceAutoStart.dll'))[0].read_bytes(),b'old')
            self.assertEqual((root/'BepInEx/config/sma-voice-portable.paths').read_text().splitlines(),[str(fake_python),str(runtime)])
            self.assertIn('Enabled = true',cfg.read_text()); self.assertIn('Announce = false',cfg.read_text())
            self.assertTrue(json.loads((runtime/'instalacao.json').read_text())['autostart'])
            self.assertTrue((root/'SMA_DIAGNOSTICO.bat').is_file())
            self.assertTrue((root/'SMA_VERIFICAR.bat').is_file())
            self.assertIn('CaptureSource = Hybrid',(root/'BepInEx/config/local.sma.voicecapture.cfg').read_text())

if __name__=='__main__': unittest.main()
