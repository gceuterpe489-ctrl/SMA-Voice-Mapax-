import contextlib, io, json, os, sys, tempfile, threading, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
import iniciar, session_report, voice_settings, sma_voice_stream

class ReportTests(unittest.TestCase):
    def fixture(self,base):
        root=base/'game'; runtime=base/'runtime'; runtime.mkdir()
        queue=root/'BepInEx/SMA-Voice-Queue'; queue.mkdir(parents=True)
        settings=root/'BepInEx/plugins/SMAVoiceCapture/CONFIGURACOES.txt'; settings.parent.mkdir(parents=True)
        settings.write_text('ENABLE_LOG=true\n')
        (runtime/'instalacao.json').write_text(json.dumps(dict(mode='sma',project_root=str(root),queue=str(queue),settings=str(settings),autostart=True)))
        return root,runtime,queue,settings
    def run_launch(self,runtime,root,extra):
        def run(*a,**kw):
            print('PRONTO',flush=True); session_report.status('READY','teste')
        with patch('runpy.run_path',side_effect=run),patch.dict(os.environ,{},clear=False),patch.object(sys,'argv',['iniciar.py']):
            return iniciar.main(runtime,['--autostart-root',str(root)]+extra)
    def test_enabled_session_report(self):
        with tempfile.TemporaryDirectory() as d:
            root,runtime,q,_=self.fixture(Path(d)); path=root/'SMA_VOICE_test.log'; state=q/'test.status'
            self.assertEqual(self.run_launch(runtime,root,['--session-report',str(path),'--status-file',str(state)]),0)
            self.assertIn('[PYTHON] PRONTO',path.read_text()); self.assertIn('SESSION_READER_FINALLY',path.read_text()); self.assertIn('STOPPED',state.read_text()); self.assertFalse((runtime/'voice.log').exists())
    def test_disabled_no_report_or_legacy_log(self):
        with tempfile.TemporaryDirectory() as d:
            root,runtime,q,settings=self.fixture(Path(d)); settings.write_text('ENABLE_LOG=false\n'); state=q/'test.status'
            self.assertEqual(self.run_launch(runtime,root,['--session-report-off','--status-file',str(state)]),0)
            self.assertFalse(list(root.glob('*.log'))); self.assertFalse((runtime/'voice.log').exists()); self.assertIn('STOPPED',state.read_text())
    def test_legacy_disabled(self):
        with tempfile.TemporaryDirectory() as d:
            root,runtime,q,settings=self.fixture(Path(d)); settings.write_text('ENABLE_LOG=false\n')
            self.assertEqual(self.run_launch(runtime,root,[]),0); self.assertFalse((runtime/'voice.log').exists())
    def test_multiple_threads_log_lines(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'report.log'; writer=session_report.SessionWriter(path)
            def run(n):
                for i in range(10): writer.write(f'worker{n}'); writer.write(f'-{i}\n')
            workers=[threading.Thread(target=run,args=(i,)) for i in range(4)]
            for t in workers:t.start()
            for t in workers:t.join()
            writer.close(); lines=path.read_text().splitlines(); self.assertEqual(len(lines),40); self.assertEqual(len(set(x.split('[PYTHON] ')[1] for x in lines)),40)
    def test_settings(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'config.txt';p.write_text('enable log=false\n')
            with self.assertRaises(ValueError): voice_settings.read_settings(p)
            p.write_text('ENABLE_LOG=false\nENABLE_INSPECTOR=false\n');self.assertFalse(voice_settings.read_settings(p)['ENABLE_LOG']);self.assertFalse(voice_settings.read_settings(p)['ENABLE_INSPECTOR'])
    def test_bepinex6_listener_contract_source(self):
        # Source regression only; real C# compilation uses game references.
        source=(ROOT/'src/SessionReport.cs').read_text(encoding='utf-8')
        self.assertIn('class SessionReport : ILogListener',source)
        self.assertIn('public LogLevel LogLevelFilter { get { return LogLevel.All; } }',source)
        self.assertIn('public void LogEvent(object sender, LogEventArgs e)',source)
        self.assertIn('public void Dispose()',source)
        self.assertIn('name == "SMA Voice Capture" || name == "SMA Voice AutoStart"',source)
    def test_ollama_offline(self):
        with patch('urllib.request.urlopen',side_effect=ConnectionRefusedError('offline')):
            self.assertEqual(sma_voice_stream.check_ollama('test')[0],'UNAVAILABLE')
    def test_ollama_models(self):
        with patch('urllib.request.urlopen',return_value=io.BytesIO(b'{"models":[{"name":"test:latest"}]}')):
            self.assertEqual(sma_voice_stream.check_ollama('test')[0],'OK')
        with patch('urllib.request.urlopen',return_value=io.BytesIO(b'{"models":[]}')):
            self.assertEqual(sma_voice_stream.check_ollama('test')[0],'MODEL_MISSING')
