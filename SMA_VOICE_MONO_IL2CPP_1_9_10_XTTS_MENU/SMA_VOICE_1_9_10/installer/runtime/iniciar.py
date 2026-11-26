"""Portable launcher; the automatic reader runs in this very process (no orphan child)."""
import argparse, json, os, sys, subprocess, traceback, runpy
from pathlib import Path


def command(base, extra, expected_root=None):
    cfg=json.loads((base/'instalacao.json').read_text(encoding='utf-8-sig'))
    root=Path(cfg.get('project_root') or base.parent)
    queue=root/cfg['queue']; settings=root/cfg['settings']
    if expected_root is not None:
        if not cfg.get('autostart',cfg['mode']=='sma') or root.resolve()!=expected_root.resolve():
            raise RuntimeError('Este jogo nao e o projeto ativo do SMA Voice. Execute INSTALAR.bat para seleciona-lo.')
        plugin='SMAVoiceCapture' if cfg['mode']=='sma' else 'SMA Voice'
        if queue.resolve()!=(root/'BepInEx/SMA-Voice-Queue').resolve() or settings.resolve()!=(root/'BepInEx/plugins'/plugin/'CONFIGURACOES.txt').resolve():
            raise RuntimeError('Fila/configuracao do AutoStart nao corresponde ao jogo. Reinstale o mod.')
    if not settings.is_file():
        raise FileNotFoundError('CONFIGURACOES.txt nao encontrado: '+str(settings))
    env=os.environ.copy()
    backend=cfg.get('unity_backend','unknown')
    # New installations persist an explicit user selection. Never override it.
    if cfg.get('selected_game'):
        expected={'SMA':'Mono','CMA':'IL2CPP'}.get(cfg['selected_game'])
        if expected is None or backend!=expected: raise RuntimeError('Selected game/backend mismatch; reinstall with the correct game.')
    elif backend not in ('Mono','IL2CPP'):
        # Legacy profile compatibility only.
        if (root/'GameAssembly.dll').is_file(): backend='IL2CPP'
        elif (root/'BepInEx/core/BepInEx.dll').is_file(): backend='Mono'
    if backend=='IL2CPP': env['SMA_VOICE_IL2CPP']='1'
    else: env.pop('SMA_VOICE_IL2CPP',None)
    env['SMA_VOICE_BACKEND']=backend
    if cfg.get('shared_voice_root'): env['SMA_VOICE_SHARED']=cfg['shared_voice_root']
    else: env.pop('SMA_VOICE_SHARED',None)
    if cfg.get('model_dir'): env['SMA_XTTS_MODEL_DIR']=cfg['model_dir']
    else: env.pop('SMA_XTTS_MODEL_DIR',None)
    if cfg['mode']=='generic':
        env['SMA_VOICE_GENERIC']='1'; env['SMA_VOICE_DATA']=str(base/'dados')
    else:
        env.pop('SMA_VOICE_GENERIC',None); env['SMA_VOICE_DATA']=str(base)
    args=[sys.executable,str(base/'sma_voice_stream.py'),'--queue',str(queue),'--settings',str(settings)]
    return args+extra,env


def main(base=None, argv=None):
    base=base or Path(__file__).resolve().parent
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--autostart-root',type=Path)
    parser.add_argument('--session-report',type=Path)
    parser.add_argument('--session-report-off',action='store_true')
    parser.add_argument('--status-file',type=Path)
    known, extra=parser.parse_known_args(sys.argv[1:] if argv is None else argv)
    if known.autostart_root is None:
        args,env=command(base,extra)
        return subprocess.call(args,env=env)
    # New DLL sends an explicit per-session report path or OFF. Old DLLs retain legacy logging.
    from session_report import SessionWriter, status
    from voice_settings import read_settings
    output=None; oldout,olderr=sys.stdout,sys.stderr
    try:
        if known.status_file: os.environ['SMA_VOICE_STATUS_FILE']=str(known.status_file)
        else: os.environ.pop('SMA_VOICE_STATUS_FILE',None)
        if known.session_report_off:
            output=open(os.devnull,'w',encoding='utf-8')
        elif known.session_report:
            try: output=SessionWriter(known.session_report)
            except OSError: output=open(os.devnull,'w',encoding='utf-8')
        else:
            # Compatibility with older AutoStart DLLs. Honor central OFF when readable.
            try:
                cfg=json.loads((base/'instalacao.json').read_text(encoding='utf-8-sig'))
                enabled=read_settings(Path(cfg['settings']))['ENABLE_LOG']
            except (OSError,ValueError,KeyError): enabled=True
            if not enabled: output=open(os.devnull,'w',encoding='utf-8')
            else:
                log=base/'voice.log'
                if log.exists() and log.stat().st_size>2_000_000:
                    try: log.replace(base/'voice.previous.log')
                    except OSError: pass
                output=log.open('a',encoding='utf-8',buffering=1)
        sys.stdout=sys.stderr=output
        status('STARTING','launcher Python iniciado')
        print('SESSION_READER_START | python='+sys.executable,flush=True)
        args,env=command(base,extra,known.autostart_root)
        os.environ.clear(); os.environ.update(env)
        sys.argv=args[1:]
        runpy.run_path(args[1],run_name='__main__')
        status('STOPPED','leitor encerrado normalmente')
        return 0
    except SystemExit as exc:
        if exc.code:
            print('Leitor encerrado:',exc.code,flush=True)
            # Keep a more specific error already published by the reader.
            try: existing=known.status_file.read_text(encoding='utf-8') if known.status_file else ''
            except OSError: existing=''
            if not existing.startswith('ERROR |'): status('ERROR',str(exc.code))
        else: status('STOPPED','leitor encerrado')
        return exc.code if isinstance(exc.code,int) else (1 if exc.code else 0)
    except Exception as exc:
        traceback.print_exc(); status('ERROR',type(exc).__name__+': '+str(exc)); return 1
    finally:
        print('SESSION_READER_FINALLY',flush=True)
        sys.stdout,sys.stderr=oldout,olderr
        if output is not None: output.close()

if __name__=='__main__': raise SystemExit(main())
