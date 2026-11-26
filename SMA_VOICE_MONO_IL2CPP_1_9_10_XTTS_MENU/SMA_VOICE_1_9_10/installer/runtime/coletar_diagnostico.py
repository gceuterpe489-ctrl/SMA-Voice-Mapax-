"""Local-only diagnostics for SMA/CMA; never uploads files or edits game settings."""
import argparse, datetime, json, os, time, traceback
from pathlib import Path
BASE=Path(__file__).resolve().parent


def project(base):
    cfg=json.loads((base/'instalacao.json').read_text(encoding='utf-8-sig'))
    root=Path(cfg['project_root'])
    if not root.is_dir(): raise RuntimeError('Game folder not found / Pasta do jogo ausente: '+str(root))
    return root


def latest(root):
    reports=sorted(root.glob('SMA_VOICE_*.log'))
    return reports[-1] if reports else None


def collect(base=BASE, snapshot=None):
    root=project(base); report=latest(root)
    blocks=['SMA Voice - local diagnostic / diagnostico local',
            'UTC: '+datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'Review before sharing: local paths and character names may appear. Nothing is uploaded.']
    if report:
        blocks+=['\n--- Full SMA Voice session / Sessao completa: '+report.name+' ---',report.read_text(encoding='utf-8-sig',errors='replace')]
    else:
        blocks+=['\nNo SMA_VOICE_*.log found. Check ENABLE_LOG=true, start game, reproduce issue.']
        legacy=base/'voice.log'
        if legacy.is_file(): blocks+=['\n--- Legacy reader log (may be older) ---',legacy.read_text(encoding='utf-8-sig',errors='replace')]
    if snapshot is not None:
        blocks+=['\n--- UI inspection from this request: '+snapshot.name+' ---',snapshot.read_text(encoding='utf-8-sig',errors='replace')]
    blocks+=['\nPlease also attach the complete BepInEx console output (or BepInEx/LogOutput.log or .txt) from the SAME session and SMA_VERIFICACAO.txt.']
    out=root/'DIAGNOSTICO_SMA_VOICE.txt'; out.write_text('\n'.join(blocks)+'\n',encoding='utf-8-sig'); return out


def inspect_focus(root, delay=10, count=5, timeout=8, interval=2):
    """Request a bounded series; accept only a newly completed snapshot."""
    req=root/'SMA_INSPECIONAR.request'; src=root/'SMA_INSPECTOR.txt'
    out=root/('SMA_INSPECTOR_FOCO_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.txt')
    print('Open the fixed dialogue and Alt+Tab to the game now / Abra a caixa fixa e volte ao jogo. Keep it focused.',flush=True)
    time.sleep(delay)
    lines=['SMA Voice - focused UI snapshots / snapshots com foco']; ok=0
    for i in range(count):
        previous=src.stat().st_mtime_ns if src.is_file() else -1
        req.touch(); deadline=time.monotonic()+timeout; saved=False
        while time.monotonic()<deadline:
            time.sleep(.25)
            try:
                if not req.exists() and src.is_file() and src.stat().st_mtime_ns>previous:
                    data=src.read_text(encoding='utf-8-sig',errors='replace')
                    # Old and new inspectors terminate with Total=... | falhas=...
                    if any(line.startswith('Total=') and 'falhas=' in line for line in data.splitlines()[-3:]):
                        lines.extend([f'\n=== SNAPSHOT {i+1} ===',data]); ok+=1; saved=True; break
            except OSError: pass
        if not saved: lines.append(f'SNAPSHOT {i+1}: no new completed snapshot / sem resposta nova')
        if i+1<count: time.sleep(interval)
    out.write_text('\n'.join(lines)+'\n',encoding='utf-8-sig')
    print(f'New snapshots / Capturas novas: {ok}/{count}\n{out}')
    if not ok: print('Check ENABLE_INSPECTOR=true and keep the game open/focused.')
    return out


def main():
    p=argparse.ArgumentParser(); p.add_argument('--support',action='store_true'); p.add_argument('--open-latest',action='store_true'); p.add_argument('--inspect',action='store_true'); args=p.parse_args()
    root=project(BASE)
    if args.open_latest:
        report=latest(root)
        if report is None: raise RuntimeError('No session log found. Check ENABLE_LOG=true.')
        os.startfile(str(report)); return 0
    snapshot=None
    if args.support:
        print('1 - Collect full mod log / Coletar log completo do mod\n2 - Inspect UI + collect log / Inspecionar interface + coletar log')
        choice=input('Option / Opcao [1/2]: ').strip()
        if choice not in ('1','2'): raise RuntimeError('Choose 1 or 2 / Escolha 1 ou 2.')
        if choice=='2': snapshot=inspect_focus(root)
    elif args.inspect: snapshot=inspect_focus(root)
    print('Report / Relatorio:',collect(snapshot=snapshot))
    print('Review before sharing / Revise antes de compartilhar. No data sent / Nenhum dado enviado.')
    return 0

if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception:
        traceback.print_exc(); raise SystemExit(1)
