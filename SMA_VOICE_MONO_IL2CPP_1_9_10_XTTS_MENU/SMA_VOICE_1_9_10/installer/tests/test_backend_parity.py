import json, sys, tempfile, threading, unittest
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
from voice_settings import read_settings, protected_audio_backend
from iniciar import command
from sma_voice_stream import protected_segment_enabled, Voice, AudioBuffer
from session_guard import Cancelled
import numpy as np

class BackendParityTests(unittest.TestCase):
    def test_backend_defaults_and_independent_opt_outs(self):
        cfg=read_settings()
        for backend in ('Mono','IL2CPP'):
            env={'SMA_VOICE_BACKEND':backend}
            self.assertEqual(protected_audio_backend(cfg,env),(backend,True))
            key='PROTEGER_AUDIO_'+backend.upper()
            changed={**cfg,key:False}
            self.assertEqual(protected_audio_backend(changed,env),(backend,False))
            other='Mono' if backend=='IL2CPP' else 'IL2CPP'
            self.assertTrue(protected_audio_backend(changed,{'SMA_VOICE_BACKEND':other})[1])
        self.assertFalse(protected_audio_backend(cfg,{})[1])
    def test_launcher_backend_selection(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); (base/'settings.txt').touch()
            for backend in ('Mono','IL2CPP','desconhecido'):
                (base/'instalacao.json').write_text(json.dumps(dict(mode='sma',project_root=str(base),queue='queue',settings='settings.txt',unity_backend=backend)))
                env=command(base,[])[1]
                self.assertEqual(env['SMA_VOICE_BACKEND'],backend)
                self.assertEqual(env.get('SMA_VOICE_IL2CPP'),'1' if backend=='IL2CPP' else None)
    def test_both_engines_and_both_dialogue_kinds(self):
        cfg=read_settings()
        for engine in ('Mono','IL2CPP'):
            for mode in ('stream','adaptive','stable'):
                args=SimpleNamespace(safe_audio=protected_audio_backend(cfg,{'SMA_VOICE_BACKEND':engine})[1],mode=mode,box_segment_start=True,bubble_segment_start=True)
                for kind in ('box','default','bark'):
                    self.assertEqual(protected_segment_enabled(args,kind),mode!='stable')
    def test_cancelled_finished_buffer_not_reported_success(self):
        v=Voice.__new__(Voice); v.buffer=AudioBuffer(np,100,100)
        token=threading.Event(); v.buffer.reset(token); token.set(); v.buffer.finish()
        with self.assertRaises(Cancelled): v.wait_audio(1,token)
    def test_mono_recovery_preserves_native_policy(self):
        s=(ROOT/'src/SMAVoiceCapture.cs').read_text()
        for needle in ('enableMonoBarkRecovery && (pollFemaleBark.Value || controllerHooks == 0)', 'authorized = VerifiedBarkIdentity(identity, name) && (visible || barkEvidence)', 'SMA SESSION_BARK_END', 'public sealed class SMAVoiceCapture : BaseUnityPlugin','public sealed class SMAVoiceCapture : BasePlugin'):
            self.assertIn(needle,s)
        a=(ROOT/'src/SMAVoiceAutoStart.cs').read_text()
        self.assertIn('SceneManager.sceneUnloaded += SceneUnloaded;',a)
        self.assertIn('SceneManager.sceneUnloaded -= SceneUnloaded;',a)
    def test_optional_profile_valid_and_migration(self):
        cfg=read_settings(ROOT/'config/PERFIL_LATENCIA_MONO_IL2CPP.txt')
        for key in ('PROTEGER_AUDIO_MONO','PROTEGER_AUDIO_IL2CPP','INICIO_CAIXA_POR_SEGMENTO','INICIO_BALAO_POR_SEGMENTO','ENABLE_MONO_BARK_RECOVERY'):
            self.assertTrue(cfg[key])
            self.assertIn(key,(ROOT/'instalar_portatil.py').read_text())
