import sys, unittest, subprocess, types, tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import instalar_portatil as installer

class DotnetBootstrapTests(unittest.TestCase):
    def test_existing_sdk_skips_installation(self):
        with patch.object(installer,'find_dotnet_sdk',return_value='dotnet'), patch.object(installer.subprocess,'run') as run:
            self.assertEqual(installer.ensure_dotnet_sdk(),'dotnet')
            run.assert_not_called()

    def test_missing_sdk_installs_and_redetects(self):
        with patch.object(installer,'find_dotnet_sdk',side_effect=[None,'local-dotnet']), patch.object(installer.subprocess,'run') as run:
            self.assertEqual(installer.ensure_dotnet_sdk(),'local-dotnet')
            self.assertEqual(Path(run.call_args.args[0][-1]).name,'INSTALAR_DOTNET.ps1')
            self.assertTrue(run.call_args.kwargs['check'])

    def test_failed_install_stops(self):
        with patch.object(installer,'find_dotnet_sdk',return_value=None), patch.object(installer.subprocess,'run',side_effect=subprocess.CalledProcessError(1,['powershell'])):
            with self.assertRaisesRegex(RuntimeError,'Falha na instalacao do SDK'):
                installer.ensure_dotnet_sdk()

    def test_success_without_sdk_stops(self):
        with patch.object(installer,'find_dotnet_sdk',return_value=None), patch.object(installer.subprocess,'run'):
            with self.assertRaisesRegex(RuntimeError,'nao localizado apos instalacao'):
                installer.ensure_dotnet_sdk()

    def test_runtime_only_not_sdk(self):
        with patch.dict(installer.os.environ,{},clear=True), patch.object(installer.shutil,'which',return_value='dotnet'), patch.object(installer.subprocess,'run',return_value=types.SimpleNamespace(stdout='')):
            self.assertIsNone(installer.find_dotnet_sdk())

    def test_private_sdk_found_without_path(self):
        with tempfile.TemporaryDirectory() as d:
            exe=Path(d)/'SMA Voice/dotnet/dotnet.exe'; exe.parent.mkdir(parents=True); exe.touch()
            with patch.dict(installer.os.environ,{'LOCALAPPDATA':d},clear=True), patch.object(installer.shutil,'which',return_value=None), patch.object(installer.subprocess,'run',return_value=types.SimpleNamespace(stdout='8.0.400 [local]')):
                self.assertEqual(installer.find_dotnet_sdk(),str(exe))
