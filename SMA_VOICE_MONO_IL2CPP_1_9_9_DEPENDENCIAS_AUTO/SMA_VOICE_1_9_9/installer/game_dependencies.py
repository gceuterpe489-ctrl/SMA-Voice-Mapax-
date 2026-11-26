"""Install only missing pinned game dependencies; never infer or switch engine."""
import hashlib
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

# Fingerprints of the exact four reference archives supplied by the maintainer.
# Not vendor signatures. A changed upstream archive is deliberately refused.
PACKAGES = {
    'SMA': (
        ('BepInEx_win_x64_5.4.23.6.zip', '6c57a714a892efb4e9e1fef63d608a3391f30ec984031c465404e4ee381a0755', 'https://github.com/BepInEx/BepInEx/releases/download/v5.4.23.6/BepInEx_win_x64_5.4.23.6.zip'),
        ('UnityGameTranslator-BepInEx5-v0.16.1.zip', 'cbee9f2ca94aeea7e70203a95c7f575eacbc12942e80a29bb1702ad1d6536346', 'https://downloads.sourceforge.net/project/unitygametranslator/v0.16.1/UnityGameTranslator-BepInEx5-v0.16.1.zip')),
    'CMA': (
        ('BepInEx-Unity.IL2CPP-win-x64-6.0.0-be.793+dbc82f0.zip', '5b63d7d0e92a2448ccd13b738ff95ff1cc1026c6d718555d4df8e6c824953ac4', 'https://builds.bepinex.dev/projects/bepinex_be/793/BepInEx-Unity.IL2CPP-win-x64-6.0.0-be.793%2Bdbc82f0.zip'),
        ('UnityGameTranslator-BepInEx6-IL2CPP-v0.16.1.zip', '352dd6d113ff7aa203ac0523c88137616d46b8f1b009bae74836f46447909a27', 'https://downloads.sourceforge.net/project/unitygametranslator/v0.16.1/UnityGameTranslator-BepInEx6-IL2CPP-v0.16.1.zip')),
}
REQUIRED = {
    'SMA': ('winhttp.dll','doorstop_config.ini','BepInEx/core/BepInEx.dll','BepInEx/core/0Harmony.dll','BepInEx/core/BepInEx.Preloader.dll'),
    'CMA': ('winhttp.dll','doorstop_config.ini','BepInEx/core/BepInEx.Unity.IL2CPP.dll','BepInEx/core/BepInEx.Core.dll','BepInEx/core/Il2CppInterop.Runtime.dll','BepInEx/core/0Harmony.dll','dotnet/coreclr.dll', 'dotnet/hostpolicy.dll'),
}
TRANSLATOR = 'BepInEx/plugins/UnityGameTranslator/UnityGameTranslator.dll'
TRANSLATOR_HASHES = {'SMA': '63ed4e2848a79f8f6723154d2cdf1719e17b0feed54da31894037fe873c23083', 'CMA': '94d7c2af61a933d1cb4f50b159d2de4a8092242b92e8dc118f301ae0c07db625'}
MAX_ZIP = 100 * 1024 * 1024
MAX_EXPANDED = 300 * 1024 * 1024

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()

def obtain(package, local, work):
    name, expected, url=package
    candidate=local/name
    dest=work/name
    if candidate.is_file():
        print('Local ZIP:',candidate); shutil.copyfile(candidate,dest)
    else:
        print('Downloading / Baixando:',url)
        req=urllib.request.Request(url,headers={'User-Agent':'SMA-Voice-Installer/1.9.9'})
        with urllib.request.urlopen(req,timeout=60) as response, dest.open('wb') as out:
            if not response.geturl().startswith('https://'): raise RuntimeError('Insecure download redirect refused.')
            total=0
            while True:
                block=response.read(1024*1024)
                if not block: break
                total+=len(block)
                if total>MAX_ZIP: raise RuntimeError('Download exceeds size limit.')
                out.write(block)
    if sha(dest)!=expected: raise RuntimeError('SHA-256 mismatch / checksum invalido: '+name+'; no files installed. Use the exact reference ZIP.')
    return dest

def archive_entries(path):
    with zipfile.ZipFile(path) as z:
        seen=set(); total=0
        for item in z.infolist():
            raw=item.filename; p=PurePosixPath(raw)
            if ('\\' in raw or ':' in raw or p.is_absolute() or '..' in p.parts or not p.parts or (item.external_attr>>16)&0o170000==0o120000):
                raise RuntimeError('Unsafe ZIP entry: '+raw)
            if item.is_dir(): continue
            key=str(p).casefold()
            if key in seen: raise RuntimeError('Duplicate ZIP entry: '+raw)
            seen.add(key); total+=item.file_size
            if total>MAX_EXPANDED: raise RuntimeError('ZIP expansion limit exceeded.')
            yield str(p), z.read(item)

def safe_target(root, rel):
    target=root/rel
    if not target.resolve().is_relative_to(root.resolve()): raise RuntimeError('Destination outside game root: '+str(target))
    # Refuse symlinks, including ones targeting another file within the game.
    for part in [target,*target.parents]:
        if part==root: break
        if part.is_symlink(): raise RuntimeError('Symlink destination refused: '+str(part))
    return target

def ensure_game_dependencies(choice, root, local, install_files, assert_closed):
    root=root.resolve()
    required=REQUIRED[choice]; bep,translator=PACKAGES[choice]
    missing=[rel for rel in required if not (root/rel).is_file()]
    copies=[p for p in (root/'BepInEx/plugins').rglob('*') if p.is_file() and p.name.casefold()=='unitygametranslator.dll']
    if len(copies)>1: raise RuntimeError('Multiple UnityGameTranslator DLLs. Keep only the correct one, then retry.')
    if copies:
        digest=sha(copies[0]); other='CMA' if choice=='SMA' else 'SMA'
        if digest==TRANSLATOR_HASHES.get(other): raise RuntimeError('UnityGameTranslator is for the other backend. Replace manually with the correct variant.')
        print('UnityGameTranslator present; preserving:',copies[0])
        if digest!=TRANSLATOR_HASHES.get(choice): print('WARNING: existing translator version/backend not verified; keeping user files.')
    if not missing and copies:
        print('Game dependencies present; no downloads / Dependencias presentes.')
        return False
    with tempfile.TemporaryDirectory(prefix='sma-deps-') as temp:
        work=Path(temp); updates={}
        if missing:
            print('BepInEx missing files:',', '.join(missing))
            entries=dict(archive_entries(obtain(bep,local,work)))
            if not set(required)<=set(entries): raise RuntimeError('Reference archive incomplete.')
            for rel,data in entries.items():
                target=safe_target(root,rel)
                if target.exists():
                    if not target.is_file() or target.read_bytes()!=data:
                        # Never merge different BepInEx binaries. User configuration may be retained.
                        if rel in ('doorstop_config.ini','changelog.txt') and target.is_file(): continue
                        raise RuntimeError('Conflicting existing dependency file; not overwritten: '+str(target))
                else: updates[target]=data
        if not copies:
            entries=dict(archive_entries(obtain(translator,local,work)))
            if set(entries)!={'UnityGameTranslator.dll'}: raise RuntimeError('Unexpected translator archive layout.')
            updates[safe_target(root,TRANSLATOR)]=entries['UnityGameTranslator.dll']
        assert_closed()
        # All downloads/hash checks/conflict checks finish before touching game files.
        for target in updates:
            if target.exists(): raise RuntimeError('Dependency destination changed during setup; retry: '+str(target))
        install_files(updates,[],work,root,work/'backup')
    print('Missing game dependencies installed / Dependencias ausentes instaladas.')
    return True
