"""Verify files, settings and dependencies for this project; no repair or upload."""
import hashlib, json, sys, traceback, datetime
from pathlib import Path
from importlib import metadata


def verify(base):
    manifest=json.loads((base/'MANIFESTO_INSTALACAO.json').read_text(encoding='utf-8-sig'))
    errors=[]
    for item in manifest['files']:
        p=Path(item['path'])
        if not p.is_file(): errors.append('AUSENTE / MISSING: '+str(p))
        elif not item.get('mutable') and hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:
            errors.append('ALTERADO / CHANGED: '+str(p))
    cfg=json.loads((base/'instalacao.json').read_text(encoding='utf-8-sig'))
    if not Path(cfg['python']).is_file(): errors.append('Python ausente / missing: '+cfg['python'])
    if not Path(cfg['queue']).is_dir(): errors.append('Fila ausente / Queue missing: '+cfg['queue'])
    if cfg.get('model_dir') and not Path(cfg['model_dir']).is_dir(): errors.append('Modelo ausente / Model missing: '+cfg['model_dir'])
    return manifest,errors


def report(base):
    root=None; errors=[]; lines=['SMA Voice - installation check / verificacao da instalacao', 'UTC: '+datetime.datetime.now(datetime.timezone.utc).isoformat(), 'Review before sharing. Local paths may appear.']
    try:
        cfg=json.loads((base/'instalacao.json').read_text(encoding='utf-8-sig'))
        root=Path(cfg['project_root'])
        manifest,errors=verify(base)
        lines.extend(['Game / Jogo: '+str(cfg.get('selected_game','legacy')),'Backend: '+str(cfg.get('unity_backend','unknown')),'Root: '+str(root),'Runtime: '+str(base),'Python: '+sys.executable,'Python version: '+sys.version.split()[0]])
        from voice_settings import read_settings
        try: read_settings(Path(cfg['settings'])); lines.append('CONFIGURACOES.txt: OK')
        except Exception as exc: errors.append('CONFIGURACOES.txt: '+str(exc))
        plugins=root/'BepInEx/plugins'; translators=list(plugins.rglob('UnityGameTranslator.dll'))
        lines.append('UnityGameTranslator.dll: '+str(len(translators))+' found (expected 1 for integration)')
        if len(translators)!=1: lines.append('WARNING: install only the translator version for the selected BepInEx backend.')
        for name in ('torch','torchaudio','coqui-tts','TTS','numpy','sounddevice'):
            try: lines.append(name+': '+metadata.version(name))
            except metadata.PackageNotFoundError: lines.append(name+': not installed (TTS or coqui-tts, not both, is expected)')
        try:
            import torch, numpy, sounddevice
            from TTS.api import TTS
            lines.append('XTTS imports: OK | CUDA available: '+str(torch.cuda.is_available()))
            devices=sounddevice.query_devices()
            lines.append('Audio output devices / Saidas de audio (DISPOSITIVO_AUDIO):')
            for index,device in enumerate(devices):
                if device['max_output_channels']>0: lines.append(f'  {index}: {device["name"]} ({device["max_output_channels"]} channels)')
        except Exception as exc: errors.append('XTTS/audio import or device check: '+repr(exc))
        lines.extend(errors or ['OK: installed files, paths, hashes, central settings and XTTS imports checked. No synthesis performed.'])
    except Exception:
        errors.append('Verification failed'); lines.append(traceback.format_exc())
    out=(root if root and root.is_dir() else base)/'SMA_VERIFICACAO.txt'
    out.write_text('\n'.join(lines)+'\n',encoding='utf-8-sig')
    print('\n'.join(lines)); print('Report / Relatorio:',out)
    return bool(errors)

if __name__=='__main__':
    try: raise SystemExit(report(Path(__file__).resolve().parent))
    except Exception:
        traceback.print_exc(); raise SystemExit(1)
