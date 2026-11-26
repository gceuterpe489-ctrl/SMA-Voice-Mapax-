import sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
from voice_settings import read_settings
class CmaBarkTests(unittest.TestCase):
    def test_default_and_opt_out(self):
        self.assertTrue(read_settings()['ENABLE_CMA_BARK'])
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'settings.txt'; p.write_text('ENABLE_CMA_BARK=false\n')
            self.assertFalse(read_settings(p)['ENABLE_CMA_BARK'])
    def test_cma_guard_source(self):
        s=(ROOT/'src/SMAVoiceCapture.cs').read_text()
        self.assertIn('if (bark) authorized = enableCmaBark && VerifiedBarkIdentity(identity, name);',s)
        self.assertIn('Guid.TryParse(identity.Id, out id) && id != Guid.Empty',s)
        self.assertIn('id != new Guid("00000001-0000-0000-0000-000000000000")',s)
        self.assertIn('bool authorized = subtitle ? authorizedName : pollFemaleBark.Value;',s)
    def test_installer_migration_source(self):
        self.assertIn("('ENABLE_LOG','ENABLE_INSPECTOR','ENABLE_CMA_BARK','PROTEGER_AUDIO_IL2CPP')",(ROOT/'instalar_portatil.py').read_text())
        self.assertIn('ENABLE_CMA_BARK=true',(ROOT/'config/CONFIGURACOES.txt').read_text())
