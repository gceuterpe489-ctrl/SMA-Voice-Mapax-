"""User data location and non-destructive migration from SMA Voice <= 1.6."""
import ctypes, os, json, shutil, uuid
from pathlib import Path
from character_voices import VOICES, canonical_id


def documents():
    if os.name == 'nt':
        # Windows resolves redirected/OneDrive Documents via the shell.
        buffer = ctypes.create_unicode_buffer(32768)
        result = ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer)
        if result == 0 and buffer.value: return Path(buffer.value)
    return Path.home() / 'Documents'


def game_documents():
    return documents() / 'TValle Games' / 'Some Modeling Agency'


def data_root():
    return Path(os.environ['SMA_VOICE_DATA']) if os.environ.get('SMA_VOICE_DATA') else game_documents() / 'SMA Voice'


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        tmp.replace(path)
    finally: tmp.unlink(missing_ok=True)


def setup_storage(old, new, log=print):
    old,new=Path(old),Path(new)
    new.mkdir(parents=True,exist_ok=True)
    for sub in ('voices','cards','backups'): (new/sub).mkdir(exist_ok=True)
    # Import once, preserving existing destination records. Old originals remain as backup.
    marker=new/'migration_v17.json'
    if not marker.exists() and old.resolve()!=new.resolve():
        for name in ('character_voices.json','sources.json','characters.json'):
            src,dst=old/name,new/name
            if not src.is_file(): continue
            if not dst.exists(): shutil.copy2(src,dst)
            else:
                previous=json.loads(src.read_text(encoding='utf-8-sig'))
                current=json.loads(dst.read_text(encoding='utf-8-sig'))
                if not isinstance(previous,dict) or not isinstance(current,dict): raise ValueError('Cadastro invalido: '+name)
                if name=='sources.json':
                    merged={**previous,**current,'paths':list(dict.fromkeys(previous.get('paths',[])+current.get('paths',[])))}
                else: merged={**previous,**current}
                if merged!=current: write_json(dst,merged)
        source=old/'cards'
        if source.is_dir():
            for f in source.rglob('*'):
                if not f.is_file() or f.is_symlink() or not f.resolve().is_relative_to(source.resolve()): continue
                target=new/'cards'/f.relative_to(source)
                if not target.exists():
                    target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(f,target)
                elif f.read_bytes()!=target.read_bytes():
                    log('Migracao: cartao existente preservado: '+str(target))
        write_json(marker,{'source':str(old),'originals_preserved':True})
    config=new/'voice_library.json'
    if not config.exists(): write_json(config,{'builtin_voices':list(VOICES),'include_wav':True})
    guide=new/'voices'/'LEIA-ME.txt'
    if not guide.exists(): guide.write_text('Coloque aqui WAVs de referencia proprios, licenciados ou autorizados (PCM, 3-30 s, mono/estereo, 16/24/32 bits, 8-96 kHz, ate 20 MB). Cada WAV valido entra no sorteio quando include_wav=true. O ID e o hash do conteudo, renomear nao muda a voz. Nao substitua o conteudo de uma voz existente se quiser manter seu ID.\n',encoding='utf-8')
    return new
