import contextlib, io, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import instalar_portatil as installer

class XTTSSelectionTests(unittest.TestCase):
    def test_menu_always_explicit_and_no_auto_reuse(self):
        s=(ROOT/'BOOTSTRAP.ps1').read_text()
        self.assertIn('$registered=$old[0]',s)
        self.assertNotIn('$python=$old[0]',s)
        self.assertIn('while (-not $python)',s)
        for i in range(1,5): self.assertIn(f"$mode -eq '{i}'",s)
        self.assertIn("if (-not $registered)",s)
        self.assertIn("$python=$registered; $kind='existing'",s)
        self.assertIn("$python=Find-ExistingPython; $kind='existing'",s)
        self.assertIn("$kind='auto'; $python=Find-Python311",s)
        self.assertLess(s.index('Installation cancelled'),s.index('--xtts $kind'))
    def test_existing_environment_has_no_pip_calls(self):
        with patch.object(installer.subprocess,'run') as run:
            self.assertEqual(installer.choose_environment('existing',Path('unused')),(Path(sys.executable),'auto'))
            run.assert_not_called()
    def test_reserve_environment_avoids_managed_unmanaged_and_file(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); (root/'xtts').mkdir(); (root/'xtts'/'sma-managed.txt').write_text('previous'); (root/'xtts-2').mkdir(); (root/'xtts-3').write_text('do not touch')
            new=installer.reserve_new_xtts(root)
            self.assertEqual(new,root/'xtts-4'); self.assertEqual((root/'xtts'/'sma-managed.txt').read_text(),'previous'); self.assertEqual((root/'xtts-3').read_text(),'do not touch')
    def test_fresh_environment(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'runtime'; new=installer.reserve_new_xtts(root)
            self.assertEqual(new,root/'xtts'); self.assertTrue((new/'sma-managed.txt').is_file())
    def test_new_cpu_environment_never_installs_into_old_venv(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); old=root/'xtts'; old.mkdir(); (old/'sma-managed.txt').write_text('previous'); (old/'sma-backend.txt').write_text('cuda')
            with patch.object(installer.sys,'version_info',(3,11,0)),patch.object(installer.subprocess,'run') as run,patch('builtins.input',return_value='2'),contextlib.redirect_stdout(io.StringIO()):
                python,device=installer.choose_environment('auto',root)
            self.assertEqual(python,root/'xtts-2'/'Scripts/python.exe'); self.assertEqual(device,'cpu'); self.assertEqual((old/'sma-backend.txt').read_text(),'cuda')
            self.assertTrue(any('https://download.pytorch.org/whl/cpu' in c.args[0] for c in run.call_args_list))
            self.assertFalse(any('uninstall' in c.args[0] for c in run.call_args_list))
            for c in run.call_args_list[1:]: self.assertEqual(c.args[0][0],str(python))
    def test_device_setting_preserves_unrelated_settings(self):
        self.assertEqual(installer.set_processing('# test\r\nPROCESSAMENTO=cuda\r\nIDIOMA=pt\r\n','cpu'),'# test\r\nPROCESSAMENTO=cpu\r\nIDIOMA=pt\r\n')
        self.assertEqual(installer.set_processing('IDIOMA=pt\n','cuda'),'IDIOMA=pt\nPROCESSAMENTO=cuda\n')
    def test_all_seven_manuals_updated(self):
        manuals=sorted((ROOT.parent/'manuals').glob('0*.txt')); self.assertEqual(len(manuals),7)
        for p in manuals:
            lines=p.read_text(encoding='utf-8-sig').splitlines(); self.assertIn('1.9.10',lines[1]); self.assertIn('PROCESSAMENTO',lines[12]); self.assertTrue(all(str(i) in lines[12] for i in range(1,5)))
