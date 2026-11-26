import hashlib, sys, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch, Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'runtime')]
import game_dependencies as deps
import instalar_portatil as installer

class AutoDependenciesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name); self.game=self.base/'game'; self.game.mkdir(); self.local=self.base/'dependencies'; self.local.mkdir()
    def fixture(self,choice):
        items=[]
        for name,_,url in deps.PACKAGES[choice]:
            path=self.local/name
            with zipfile.ZipFile(path,'w') as z:
                if name.startswith('BepInEx'):
                    for rel in deps.REQUIRED[choice]: z.writestr(rel,rel.encode())
                else: z.writestr('UnityGameTranslator.dll',choice.encode())
            items.append((name,deps.sha(path),url))
        return {choice:tuple(items)}
    def install(self,choice):
        return deps.ensure_game_dependencies(choice,self.game,self.local,installer.install_files,lambda:None)
    def test_fresh_both_backends(self):
        for choice in ['SMA','CMA']:
            with self.subTest(choice=choice):
                self.game=self.base/choice; self.game.mkdir()
                with patch.object(deps,'PACKAGES',self.fixture(choice)),patch.object(deps.urllib.request,'urlopen',side_effect=AssertionError('network')):
                    self.assertTrue(self.install(choice)); self.assertFalse(self.install(choice))
                    self.assertTrue(all((self.game/p).is_file() for p in deps.REQUIRED[choice]))
                    self.assertEqual((self.game/deps.TRANSLATOR).read_bytes(),choice.encode())
    def test_checksum_mismatch_no_writes(self):
        fixtures=self.fixture('SMA'); (self.local/fixtures['SMA'][1][0]).write_bytes(b'bad')
        with patch.object(deps,'PACKAGES',fixtures),self.assertRaisesRegex(RuntimeError,'SHA-256'):
            self.install('SMA')
        self.assertEqual(list(self.game.iterdir()),[])
    def test_preserve_complete_bepinex_and_install_only_translator(self):
        fixtures=self.fixture('SMA')
        for rel in deps.REQUIRED['SMA']:
            p=self.game/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'custom')
        (self.local/fixtures['SMA'][0][0]).unlink()
        with patch.object(deps,'PACKAGES',fixtures),patch.object(deps.urllib.request,'urlopen',side_effect=AssertionError('network')):
            self.assertTrue(self.install('SMA'))
        self.assertEqual((self.game/'winhttp.dll').read_bytes(),b'custom')
    def test_conflicting_partial_not_overwritten(self):
        fixtures=self.fixture('SMA'); p=self.game/'winhttp.dll'; p.write_bytes(b'other')
        with patch.object(deps,'PACKAGES',fixtures),self.assertRaisesRegex(RuntimeError,'Conflicting'):
            self.install('SMA')
        self.assertEqual(list(self.game.iterdir()),[p]);self.assertEqual(p.read_bytes(),b'other')
    def test_wrong_translator_refused(self):
        p=self.game/deps.TRANSLATOR;p.parent.mkdir(parents=True);p.write_bytes(b'CMA')
        with patch.object(deps,'TRANSLATOR_HASHES',{'CMA':hashlib.sha256(b'CMA').hexdigest()}),self.assertRaisesRegex(RuntimeError,'other backend'):
            self.install('SMA')
    def test_zip_traversal_refused(self):
        p=self.local/'bad.zip'
        with zipfile.ZipFile(p,'w') as z:z.writestr('../outside',b'bad')
        with self.assertRaisesRegex(RuntimeError,'Unsafe'):list(deps.archive_entries(p))
    def test_menu_and_ollama_script(self):
        bootstrap=(ROOT/'BOOTSTRAP.ps1').read_text(); ollama=(ROOT/'INSTALAR_OLLAMA.ps1').read_text()
        self.assertLess(bootstrap.index('Game / Jogo [1/2]'),bootstrap.index('Game folder or executable'))
        self.assertIn('--game $game --game-root $gamePath',bootstrap)
        self.assertIn('Ollama.Ollama',ollama); self.assertIn('qwen3:4b-instruct',ollama);self.assertIn('pull $Model',ollama);self.assertIn('/api/tags',ollama)
        self.assertIn('MODELO_OLLAMA=qwen3:4b-instruct',(ROOT/'config/CONFIGURACOES.txt').read_text())
