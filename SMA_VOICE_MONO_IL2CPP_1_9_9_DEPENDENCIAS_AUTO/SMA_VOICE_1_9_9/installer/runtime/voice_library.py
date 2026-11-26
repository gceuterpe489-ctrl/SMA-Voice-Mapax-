"""Expandable voice pool. Built-in speaker names + local authorized WAV references."""
import json, os
from pathlib import Path
from character_voices import VOICES
from character_cards import wav_reference

class VoiceLibrary:
    def __init__(self, base, available, log=print):
        self.base=Path(base); self.available=set(available); self.log=log
        self.voices=(); self.references={}; self._cache={}; self._summary=None
    def refresh(self):
        config=self.base/'voice_library.json'
        try:
            cfg=json.loads(config.read_text(encoding='utf-8-sig')) if config.exists() else {}
            builtins=cfg.get('builtin_voices',list(VOICES)); include=cfg.get('include_wav',True)
            if not isinstance(builtins,list) or not all(isinstance(v,str) and v.strip() for v in builtins) or not isinstance(include,bool): raise ValueError('biblioteca invalida')
        except (ValueError,OSError,AttributeError) as exc:
            self.log('Biblioteca de vozes: '+str(exc))
            if self.voices: return
            builtins=list(VOICES); include=True
        folder=self.base/'voices'; refs={}; cache={}
        shared=os.environ.get('SMA_VOICE_SHARED')
        folders=[folder]
        if shared and (Path(shared)/'voices').resolve()!=folder.resolve(): folders.append(Path(shared)/'voices')
        for folder in folders:
            if not folder.is_dir(): continue
            for p in sorted(folder.iterdir()):
                if p.suffix.lower()!='.wav' or p.is_symlink() or not p.is_file(): continue
                try:
                    s=p.stat(); sig=(s.st_size,s.st_mtime_ns); previous=self._cache.get(p)
                    if previous and previous[0]==sig: digest=previous[1]
                    else:
                        try: digest=wav_reference(p)
                        except (OSError,ValueError,EOFError) as exc:
                            self.log('WAV ignorado: '+p.name+' | '+str(exc)); digest=None
                        except Exception as exc:
                            self.log('WAV ignorado: '+p.name+' | '+type(exc).__name__); digest=None
                    cache[p]=(sig,digest)
                    if digest: refs.setdefault('custom:'+digest,p)
                except OSError: continue
        self._cache=cache; self.references=refs
        pool=list(dict.fromkeys(v for v in builtins if v in self.available))
        if include: pool+=list(refs)
        # Never break startup because a user removed every voice from the pool.
        if not pool: pool=[v for v in VOICES if v in self.available] or sorted(self.available)[:1]
        if not pool: raise RuntimeError('Nenhuma voz XTTS disponivel.')
        self.voices=tuple(pool)
        summary=(self.voices,tuple(refs.items()),tuple(v for v in builtins if v not in self.available))
        if summary!=self._summary:
            self.log(f'Biblioteca: {len(pool)} vozes no sorteio | {len(refs)} WAVs reconhecidos')
            if summary[2]: self.log('Vozes internas nao encontradas: '+', '.join(summary[2]))
            for key,p in refs.items(): self.log(f'WAV {p.name} | ID={key}')
            self._summary=summary
