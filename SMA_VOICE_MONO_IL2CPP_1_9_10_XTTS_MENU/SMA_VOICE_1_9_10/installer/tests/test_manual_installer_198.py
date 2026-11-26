import contextlib, hashlib, io, json, sys, tempfile, types, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'runtime')]
import instalar_portatil as installer
import coletar_diagnostico as diagnostics
import verificar_instalacao as verification
import iniciar

class ManualInstallerTests(unittest.TestCase):
    def fixture(self,base):
        root=base/'Game'; root.mkdir(); runtime=base/'runtime'; runtime.mkdir()
        q=root/'BepInEx/SMA-Voice-Queue'; q.mkdir(parents=True)
        settings=root/'BepInEx/plugins/SMAVoiceCapture/CONFIGURACOES.txt'; settings.parent.mkdir(parents=True); settings.write_text('IDIOMA=auto\n')
        py=base/'python.exe'; py.touch()
        cfg={'project_root':str(root),'queue':str(q),'settings':str(settings),'mode':'sma','selected_game':'SMA','unity_backend':'Mono','python':str(py),'autostart':True}
        (runtime/'instalacao.json').write_text(json.dumps(cfg)); return root,runtime,cfg

    def test_selected_backend_not_overridden(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,runtime,cfg=self.fixture(Path(tmp))
            (root/'GameAssembly.dll').touch()
            _,env=iniciar.command(runtime,[],root)
            self.assertEqual(env['SMA_VOICE_BACKEND'],'Mono')
            self.assertNotIn('SMA_VOICE_IL2CPP',env)
            cfg['unity_backend']='IL2CPP'; (runtime/'instalacao.json').write_text(json.dumps(cfg))
            with self.assertRaisesRegex(RuntimeError,'mismatch'): iniciar.command(runtime,[],root)

    def test_cleanup_only_known_unmodified_launchers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,runtime,_=self.fixture(Path(tmp)); a=runtime/'VER_LOG.bat'; a.write_bytes(b'old')
            b=runtime/'TESTAR_VOZ.bat'; b.write_bytes(b'edited')
            c=root/'SMA_INSPECIONAR.bat'; c.write_bytes(b'old')
            d=root/'custom.bat'; d.write_bytes(b'old')
            e=root/'SMA_INSPECIONAR_COM_FOCO.bat'; e.write_bytes(b'custom')
            oldhash=hashlib.sha256(b'old').hexdigest()
            (runtime/'MANIFESTO_INSTALACAO.json').write_text(json.dumps({'files':[{'path':str(x),'sha256':oldhash} for x in (a,b,c,d)]}))
            self.assertEqual(set(installer.old_support_launchers(runtime,root)),{a,c})
            backup=runtime/'backups/test'; installer.install_files({},[a,c],runtime,root,backup)
            self.assertFalse(a.exists()); self.assertFalse(c.exists()); self.assertTrue(b.exists()); self.assertTrue(d.exists()); self.assertTrue(e.exists())
            self.assertEqual((backup/'runtime/VER_LOG.bat').read_bytes(),b'old')
            self.assertEqual((backup/'projeto/SMA_INSPECIONAR.bat').read_bytes(),b'old')

    def test_diagnostic_preserves_full_latest_log_and_only_requested_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,runtime,_=self.fixture(Path(tmp))
            (root/'SMA_VOICE_20260101.log').write_text('old')
            body='START\n'+'line\n'*2101+'END\n'
            (root/'SMA_VOICE_20260102.log').write_text(body)
            (root/'SMA_INSPECTOR.txt').write_text('stale snapshot')
            snapshot=root/'SMA_INSPECTOR_FOCO_1.txt'; snapshot.write_text('fresh snapshot')
            out=diagnostics.collect(runtime,snapshot)
            self.assertEqual(out,root/'DIAGNOSTICO_SMA_VOICE.txt')
            content=out.read_text(encoding='utf-8-sig'); self.assertIn(body,content); self.assertIn('fresh snapshot',content); self.assertNotIn('stale snapshot',content); self.assertNotIn('--- Full SMA Voice session / Sessao completa: SMA_VOICE_20260101.log',content)

    def test_no_log_explains_absence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,runtime,_=self.fixture(Path(tmp)); out=diagnostics.collect(runtime)
            self.assertIn('No SMA_VOICE_*.log found',out.read_text(encoding='utf-8-sig'))

    def test_focus_does_not_accept_stale_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,runtime,_=self.fixture(Path(tmp)); src=root/'SMA_INSPECTOR.txt'; src.write_text('stale\nTotal=1 | falhas=0\n')
            with contextlib.redirect_stdout(io.StringIO()): out=diagnostics.inspect_focus(root,delay=0,count=1,timeout=0,interval=0)
            content=out.read_text(encoding='utf-8-sig');self.assertIn('no new completed snapshot',content);self.assertNotIn('stale',content)

    def test_focus_accepts_new_complete_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,runtime,_=self.fixture(Path(tmp)); req=root/'SMA_INSPECIONAR.request'; src=root/'SMA_INSPECTOR.txt'
            def emulate_sleep(seconds):
                if req.exists(): req.unlink(); src.write_text('new snapshot\nTotal=1 | falhas=0\n')
            with patch.object(diagnostics.time,'sleep',side_effect=emulate_sleep),contextlib.redirect_stdout(io.StringIO()): out=diagnostics.inspect_focus(root,delay=0,count=1,timeout=1,interval=0)
            self.assertIn('new snapshot',out.read_text(encoding='utf-8-sig'))

    def test_verification_writes_report_when_manifest_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,runtime,_=self.fixture(Path(tmp))
            with contextlib.redirect_stdout(io.StringIO()): failed=verification.report(runtime)
            self.assertTrue(failed); self.assertIn('MANIFESTO_INSTALACAO.json',(root/'SMA_VERIFICACAO.txt').read_text(encoding='utf-8-sig'))

    def test_three_user_facing_bats_and_seven_guides(self):
        package=ROOT.parent
        self.assertEqual(sorted(p.name for p in package.glob('*.bat')),['INSTALAR.bat','INSTALAR_OLLAMA_E_MODELO.bat','VERIFICAR_E_INSTALAR_PRE_REQUISITOS.bat'])
        self.assertEqual(len(list(package.rglob('*.bat'))),3)
        guides=sorted((package/'manuals').glob('[0-9][0-9]-*.txt')); self.assertEqual(len(guides),7)
        for guide in guides:
            s=guide.read_text(encoding='utf-8-sig')
            for key in ('SMA_VERIFICAR.bat','SMA_DIAGNOSTICO.bat','SMA_VERIFICACAO.txt','DIAGNOSTICO_SMA_VOICE.txt','CONFIGURACOES.txt','UnityGameTranslator-BepInEx5-v0.16.1.zip','UnityGameTranslator-BepInEx6-IL2CPP-v0.16.1.zip','BepInEx_win_x64_5.4.23.6.zip','BepInEx-Unity.IL2CPP-win-x64-6.0.0-be.793+dbc82f0.zip','ollama pull qwen3:4b-instruct'):
                self.assertIn(key,s,guide.name)
        self.assertFalse(list(package.rglob('*.dll')))
