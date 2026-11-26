import contextlib, io, json, sys, tempfile, types, unittest
from pathlib import Path
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'runtime')]
import instalar_portatil as installer
import iniciar
from verificar_instalacao import verify

class CompatibilityTests(unittest.TestCase):
    def game(self, root, name, sma=False):
        for rel in (name+'.exe', 'BepInEx/core/BepInEx.dll', 'BepInEx/core/0Harmony.dll',name+'_Data/Managed/UnityEngine.CoreModule.dll'):
            p=root/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b'fixture')
        if sma: (root/(name+'_Data/Managed/Assembly-D_C_Dependientes_ReSc.DialogueSys.dll')).touch()
        return root

    def install(self, root, shared, python, choice='SMA', selection=None, inputs=None, fail_compile=False):
        def compiler(src,out,refs,defines=()):
            if fail_compile: raise RuntimeError('simulated incompatible libraries')
            out.write_bytes(b'MZ'+src.stem.encode()+str(defines).encode())
        with patch.object(installer,'os',types.SimpleNamespace(name='nt',environ={})),patch.object(installer,'ensure_game_dependencies',return_value=False),patch.object(installer,'runtime_path',return_value=shared),patch.object(installer,'choose_environment',return_value=(python,'auto')),patch.object(installer,'compile_dll',side_effect=compiler) as comp,patch('subprocess.run',return_value=types.SimpleNamespace(stdout='')),patch('sma_voice_stream.lock_queue',return_value=Mock()),patch('builtins.input',side_effect=[choice,str(selection or root),*(inputs if inputs is not None else ['',''])]),patch.object(sys,'argv',['instalar_portatil.py']),contextlib.redirect_stdout(io.StringIO()):
            installer.main()
        return comp

    def test_renamed_sma_with_manual_selection(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); root=self.game(base/'outro disco'/'Cópia do jogo','Renamed',True); shared=base/'Documents/SMA Voice'; py=base/'XTTS/python.exe'; py.parent.mkdir(); py.touch()
            comp=self.install(root,shared,py,'SMA',root/'Renamed.exe')
            self.assertEqual(comp.call_count,2)
            with self.assertRaises(RuntimeError): installer.select_game('SMA',str(root/'Renamed_Data/Managed'))
            plugins=root/'BepInEx/plugins'
            for rel in ('SMAVoiceCapture/SMAVoiceCapture.dll','SMAVoiceAutoStart/SMAVoiceAutoStart.dll','SMAVoiceCapture/CONFIGURACOES.txt','SMAVoiceCapture/MANUAL_CONFIGURACOES.txt'):
                self.assertTrue((plugins/rel).is_file(),rel)
            manifest,errors=verify(shared); self.assertEqual(errors,[]); self.assertEqual(manifest['mode'],'sma')
            (plugins/'SMAVoiceCapture/SMAVoiceCapture.dll').unlink(); self.assertTrue(any('AUSENTE' in x for x in verify(shared)[1]))

    def test_cma_mono_folder_rejected_no_auto_switch(self):
        for name in ('Corrupted Modeling Agency','Corrupt Modeling Agency'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                base=Path(d); root=self.game(base/'CMA',name); shared=base/'Docs'; py=base/'python.exe'; py.touch()
                for choice in ('SMA','CMA'):
                    with self.assertRaisesRegex(RuntimeError,'nao corresponde'):
                        self.install(root,shared,py,choice)
                self.assertFalse(shared.exists())

    def test_cma_il2cpp_requires_explicit_choice_and_dependencies(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); root=base/'CMA'; shared=base/'Docs'; py=base/'python.exe'; py.touch()
            for rel in ('Corrupted Modeling Agency.exe','GameAssembly.dll','Some Modeling Agency_Data/il2cpp_data/Metadata/global-metadata.dat','BepInEx/core/BepInEx.Unity.IL2CPP.dll','BepInEx/interop/'+installer.DIALOGUE_ASSEMBLY):
                p=root/rel; p.parent.mkdir(parents=True,exist_ok=True); p.touch()
            for choice in ('','3'):
                with self.assertRaisesRegex(RuntimeError,'Escolha SMA ou CMA'):
                    self.install(root,shared,py,choice)
            with self.assertRaisesRegex(RuntimeError,'nao corresponde'):
                self.install(root,shared,py,'SMA')
            with self.assertRaisesRegex(RuntimeError,'IL2CPP: dependencias ausentes'):
                self.install(root,shared,py,'CMA')
            self.assertFalse(shared.exists()); self.assertFalse((root/'BepInEx/plugins').exists())

    def test_il2cpp_complete_compiles_both_plugins(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); root=base/'CMA'; shared=base/'Docs'; py=base/'python.exe'; py.touch()
            for rel in ('Corrupted Modeling Agency.exe','GameAssembly.dll','BepInEx/core/BepInEx.Unity.IL2CPP.dll','BepInEx/core/BepInEx.Core.dll','BepInEx/core/Il2CppInterop.Runtime.dll','BepInEx/core/0Harmony.dll','BepInEx/interop/Il2Cppmscorlib.dll','BepInEx/interop/UnityEngine.CoreModule.dll'):
                p=root/rel; p.parent.mkdir(parents=True,exist_ok=True); p.touch()
            comp=self.install(root,shared,py,'CMA')
            self.assertEqual(comp.call_count,2)
            for call in comp.call_args_list:
                self.assertIn('SMA_IL2CPP',call.kwargs['defines'])
                self.assertNotIn(root/'BepInEx/core/BepInEx.dll',call.args[2])
            self.assertEqual(verify(shared)[1],[])
            self.assertTrue((root/'BepInEx/plugins/SMAVoiceCapture/SMAVoiceCapture.dll').is_file())
            self.assertTrue((root/'BepInEx/plugins/SMAVoiceAutoStart/SMAVoiceAutoStart.dll').is_file())

    def test_il2cpp_restore_isolated_and_build_no_restore(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); out=base/'SMAVoiceAutoStart.dll'; ref=base/'BepInEx.Core.dll'; ref.touch()
            calls=[]
            def run(args, **kw):
                calls.append(args[1])
                if args[1]=='--list-sdks': return types.SimpleNamespace(stdout='8.0.400')
                if args[1]=='restore':
                    import xml.etree.ElementTree as ET
                    config=ET.parse(args[args.index('--configfile')+1])
                    self.assertIsNotNone(config.find('./packageSources/clear'))
                    self.assertEqual(config.find('./packageSources/add').get('value'),'https://api.nuget.org/v3/index.json')
                    self.assertEqual(ET.parse(args[2]).find('./PropertyGroup/TargetFramework').text,'net6.0')
                elif args[1]=='build':
                    self.assertIn('--no-restore',args)
                    target=Path(args[args.index('--output')+1]); target.mkdir()
                    (target/out.name).write_bytes(b'MZfixture')
                return types.SimpleNamespace(stdout='')
            with patch.object(installer.shutil,'which',return_value='dotnet'),patch.object(installer.subprocess,'run',side_effect=run):
                installer.compile_il2cpp(ROOT/'src/SMAVoiceAutoStart.cs',out,[ref],['SMA_IL2CPP'])
            self.assertEqual(calls,['--list-sdks','restore','build'])
            self.assertEqual(out.read_bytes(),b'MZfixture')

    def test_il2cpp_restore_failure_never_builds(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'SMAVoiceAutoStart.dll'
            failure=installer.subprocess.CalledProcessError(1,['dotnet','restore'])
            with patch.object(installer.shutil,'which',return_value='dotnet'),patch.object(installer.subprocess,'run',side_effect=[types.SimpleNamespace(stdout='8.0.400'),failure]) as run:
                with self.assertRaisesRegex(RuntimeError,'Falha ao restaurar referencias .NET 6'):
                    installer.compile_il2cpp(ROOT/'src/SMAVoiceAutoStart.cs',out,[],['SMA_IL2CPP'])
            self.assertEqual(run.call_count,2)
            self.assertFalse(out.exists())

    def test_renamed_il2cpp_family_via_interop(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for rel in ('Renamed.exe','GameAssembly.dll','Renamed_Data/il2cpp_data/Metadata/global-metadata.dat','BepInEx/interop/'+installer.DIALOGUE_ASSEMBLY):
                p=root/rel; p.parent.mkdir(parents=True,exist_ok=True); p.touch()
            recognized,managed,exe=installer.inspect_game(root)
            self.assertTrue(recognized); self.assertEqual(exe.name,'Renamed.exe')
            self.assertEqual(installer.select_game('CMA',str(root))[3],'IL2CPP')

    def test_sma_cma_isolated_profiles(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); a=self.game(base/'SMA','Some Modeling Agency',True); b=base/'CMA'; shared=base/'Documents/SMA Voice'; py=base/'python.exe'; py.touch()
            for rel in ('Corrupted Modeling Agency.exe','GameAssembly.dll','BepInEx/core/BepInEx.Unity.IL2CPP.dll','BepInEx/core/BepInEx.Core.dll','BepInEx/core/Il2CppInterop.Runtime.dll','BepInEx/core/0Harmony.dll','BepInEx/interop/Il2Cppmscorlib.dll','BepInEx/interop/UnityEngine.CoreModule.dll'):
                p=b/rel; p.parent.mkdir(parents=True,exist_ok=True); p.touch()
            self.install(a,shared,py,'SMA')
            original=(shared/'instalacao.json').read_bytes()
            comp=self.install(b,shared,py,'CMA')
            profile=installer.project_runtime(shared,b)
            self.assertNotEqual(profile,shared); self.assertEqual((shared/'instalacao.json').read_bytes(),original)
            self.assertEqual(comp.call_count,2); self.assertEqual(comp.call_args.kwargs['defines'],('SMA_IL2CPP',))
            args,env=iniciar.command(profile,[],b); self.assertEqual(env['SMA_VOICE_BACKEND'],'IL2CPP'); self.assertEqual(args[args.index('--queue')+1],str(b/'BepInEx/SMA-Voice-Queue'))
            self.assertEqual(verify(profile)[1],[]); self.assertEqual(verify(shared)[1],[])
            self.assertEqual((b/'BepInEx/config/sma-voice-portable.paths').read_text().splitlines(),[str(py),str(profile)])
            self.assertEqual(installer.project_runtime(shared,b),profile)
            self.assertEqual(installer.project_runtime(shared,a),shared)

    def test_plain_project_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); root=base/'Projeto'; root.mkdir(); shared=base/'Docs'; py=base/'python.exe'; py.touch()
            with self.assertRaisesRegex(RuntimeError,'nao validada'):
                self.install(root,shared,py,'SMA')
            self.assertFalse(shared.exists())

    def test_compile_failure_no_partial_install(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); root=self.game(base/'Game','Some Modeling Agency',True); shared=base/'Docs'; py=base/'python.exe'; py.touch()
            with self.assertRaisesRegex(RuntimeError,'simulated incompatible'): self.install(root,shared,py,fail_compile=True)
            self.assertFalse((root/'BepInEx/plugins').exists()); self.assertFalse(shared.exists())

    def test_missing_dependencies_clear_error(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'BepInEx').mkdir(); (root/'Some Modeling Agency.exe').touch()
            with self.assertRaisesRegex(RuntimeError,'BepInEx.dll'): installer.unity_references(root,None,root/'Some Modeling Agency.exe','sma','Mono')

    def test_wrong_runtime_root_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); root=self.game(base/'SMA','Some Modeling Agency',True); shared=base/'Docs'; py=base/'python.exe'; py.touch(); self.install(root,shared,py)
            with self.assertRaisesRegex(RuntimeError,'nao e o projeto ativo'): iniciar.command(shared,[],base/'wrong')

    def test_mutable_config_and_modified_runtime(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); root=self.game(base/'SMA','Some Modeling Agency',True); shared=base/'Docs'; py=base/'python.exe'; py.touch(); self.install(root,shared,py)
            cfg=root/'BepInEx/plugins/SMAVoiceCapture/CONFIGURACOES.txt'; cfg.write_text('IDIOMA=es\n'); self.assertEqual(verify(shared)[1],[])
            (shared/'iniciar.py').write_text('changed'); self.assertTrue(any('ALTERADO' in x for x in verify(shared)[1]))
