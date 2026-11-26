from pathlib import Path
import argparse, datetime, json, os, shutil, subprocess, sys, tempfile, struct, hashlib, re, uuid
BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(BASE/'runtime'))
from voice_storage import game_documents
from game_dependencies import ensure_game_dependencies

def runtime_path():
    return game_documents()/'SMA Voice'

DIALOGUE_ASSEMBLY = 'Assembly-D_C_Dependientes_ReSc.DialogueSys.dll'
GAME_NAMES = {
    'somemodelingagency': 'SMA',
    'corruptedmodelingagency': 'CMA',
    'corruptmodelingagency': 'CMA',
}


def game_name(stem):
    return GAME_NAMES.get(re.sub(r'[^a-z0-9]', '', stem.casefold()))


def game_executables(root):
    return sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower()=='.exe')


def game_data_dirs(root):
    return sorted(p for p in root.iterdir() if p.is_dir() and p.name.lower().endswith('_data'))


def inspect_game(root):
    """Validate known game files and locate the executable; do not choose a backend."""
    executables=game_executables(root)
    data_dirs=game_data_dirs(root)
    named_exes=[p for p in executables if game_name(p.stem)]
    named_data=[p for p in data_dirs if game_name(p.name[:-5])]
    dialogue_data=[p for p in data_dirs if (p/'Managed'/DIALOGUE_ASSEMBLY).is_file()]
    # A renamed IL2CPP copy can be recognized through its generated dialogue assembly.
    interop_marker=(root/'BepInEx/interop'/DIALOGUE_ASSEMBLY).is_file()
    paired=[p for p in executables if any(d.name.casefold()==(p.stem+'_Data').casefold() for d in data_dirs)]
    sma=bool(named_exes or named_data or dialogue_data or (interop_marker and len(paired)==1))
    choices=sorted(set(named_data+dialogue_data)) if sma else []
    if not choices:
        choices=[d for d in data_dirs if (d/'Managed').is_dir() or (d/'il2cpp_data').is_dir()]
    if len(choices)>1 or len(named_exes)>1:
        raise RuntimeError('Mais de um jogo Unity encontrado. Selecione uma raiz com apenas um jogo.')
    data=choices[0] if choices else None
    managed=data/'Managed' if data and (data/'Managed').is_dir() else None
    # A CMA executable may still use Some Modeling Agency_Data internally.
    exe=named_exes[0] if named_exes else next((p for p in executables if data and p.stem.casefold()==data.name[:-5].casefold()),None)
    if exe is None and len(paired)==1: exe=paired[0]
    if exe is None and len(executables)==1 and sma: exe=executables[0]
    if exe is None: exe=root/'Some Modeling Agency.exe'
    return sma,managed,exe


GAME_BACKENDS = {'SMA':'Mono', 'CMA':'IL2CPP'}

def select_game(choice, raw):
    """Validate the explicit selection; never select or switch backend by probing."""
    choice=choice.strip().upper()
    if choice not in GAME_BACKENDS: raise RuntimeError('Escolha SMA ou CMA / Enter SMA or CMA.')
    if not raw.strip(): raise RuntimeError('Pasta obrigatoria / Game folder required.')
    path=Path(raw.strip().strip('"')).expanduser().resolve()
    selected_exe=path if path.is_file() and path.suffix.lower()=='.exe' else None
    root=selected_exe.parent if selected_exe else path
    if not root.is_dir(): raise RuntimeError('Pasta inexistente / Folder not found: '+str(root))
    recognized,managed,exe=inspect_game(root)
    if not recognized: raise RuntimeError('Pasta SMA/CMA nao validada / Not a supported game root.')
    if selected_exe and selected_exe!=exe: raise RuntimeError('Executavel incorreto / Select the game executable, not a launcher.')
    if not exe.is_file(): raise RuntimeError('Executavel do jogo ausente / Game executable missing.')
    backend=GAME_BACKENDS[choice]
    core=root/'BepInEx/core'
    il2cpp_files=(root/'GameAssembly.dll').is_file() or any((d/'il2cpp_data').is_dir() for d in game_data_dirs(root))
    if backend=='Mono':
        if il2cpp_files or (core/'BepInEx.Unity.IL2CPP.dll').is_file() or game_name(exe.stem)=='CMA':
            raise RuntimeError('SMA/Mono selecionado, mas a pasta nao corresponde / Selected SMA/Mono does not match folder.')
        if managed is None: raise RuntimeError('SMA/Mono requer *_Data/Managed / Managed folder required.')
    else:
        if not il2cpp_files or (core/'BepInEx.dll').is_file() or (core/'BepInEx.Unity.Mono.dll').is_file():
            raise RuntimeError('CMA/IL2CPP selecionado, mas a pasta nao corresponde / Selected CMA/IL2CPP does not match folder.')
    return root, managed, exe, backend


def project_runtime(shared,root):
    """Keep the original runtime in place; additional roots get isolated profiles."""
    ident=hashlib.sha256(str(root.resolve()).casefold().encode('utf-8')).hexdigest()[:24]
    profile=shared/'projetos'/ident
    if (profile/'instalacao.json').is_file(): return profile
    original=shared/'instalacao.json'
    if not original.is_file(): return shared
    previous=json.loads(original.read_text(encoding='utf-8-sig')).get('project_root')
    if previous and Path(previous).resolve()==root: return shared
    return profile


def unity_references(root,managed,exe,mode,backend):
    bepin=root/'BepInEx'
    if backend not in ('Mono','IL2CPP'): raise RuntimeError('Select Mono or IL2CPP explicitly.')
    if backend=='IL2CPP':
        core=bepin/'core'; interop=bepin/'interop'
        required=[exe,core/'BepInEx.Unity.IL2CPP.dll',core/'BepInEx.Core.dll',
                  core/'Il2CppInterop.Runtime.dll',core/'0Harmony.dll',
                  interop/'Il2Cppmscorlib.dll',interop/'UnityEngine.CoreModule.dll']
        missing=[str(p) for p in required if not p.is_file()]
        if missing:
            raise RuntimeError('IL2CPP: dependencias ausentes. Use BepInEx 6 IL2CPP, abra o jogo uma vez para gerar BepInEx/interop e feche antes de instalar. Ausentes: '+', '.join(missing))
        optional=[core/n for n in ('Il2CppInterop.Common.dll','BepInEx.Unity.Common.dll','Il2CppInterop.HarmonySupport.dll')]
        optional += [interop/n for n in ('UnityEngine.dll','UnityEngine.SharedInternalsModule.dll','UnityEngine.UIModule.dll')]
        return [p for p in required if p!=exe]+[p for p in optional if p.is_file()]
    if (bepin/'core/BepInEx.Unity.Mono.dll').is_file() and not (bepin/'core/BepInEx.dll').is_file():
        raise RuntimeError('BepInEx 6 Mono detectado. As DLLs atuais exigem BepInEx 5 Mono; nenhuma DLL foi instalada.')
    required=[bepin/'core/BepInEx.dll',exe]
    if mode=='sma': required.append(bepin/'core/0Harmony.dll')
    missing=[str(p) for p in required if not p.is_file()]
    if managed is None: missing.append('Unity *_Data/Managed (Mono)')
    elif not (managed/'UnityEngine.CoreModule.dll').is_file(): missing.append(str(managed/'UnityEngine.CoreModule.dll'))
    if missing: raise RuntimeError('Requer Unity Mono moderno e BepInEx 5; instale as dependencias compativeis na raiz selecionada. Ausentes: '+', '.join(missing))
    return [bepin/'core/BepInEx.dll',managed/'UnityEngine.CoreModule.dll']+[managed/n for n in ('UnityEngine.dll','netstandard.dll') if (managed/n).is_file()]


def assert_game_closed(exe):
    if not exe.is_file(): return
    running=subprocess.run(['tasklist','/FI','IMAGENAME eq '+exe.name,'/FO','CSV','/NH'],capture_output=True,text=True,check=True)
    if exe.name.lower() in running.stdout.lower(): raise RuntimeError('Feche o jogo antes de instalar: '+exe.name)


def backup_path(dst, runtime, root, backup):
    # Runtime and game may be on entirely different volumes.
    try: return backup/'runtime'/dst.relative_to(runtime)
    except ValueError: return backup/'projeto'/dst.relative_to(root)

def import_legacy_data(old, runtime, mode):
    # Preserve old files and do not relocate Python virtual environments or stale events.
    if not old.is_dir() or old.resolve()==runtime.resolve(): return
    names=['voice_cache_v12']
    if mode=='generic': names.append('dados')
    else:
        names.extend(('cards','voices'))
        for name in ('character_voices.json','sources.json','characters.json','voice_library.json'):
            source,dest=old/name,runtime/name
            if source.is_file() and not source.is_symlink() and not dest.exists():
                runtime.mkdir(parents=True,exist_ok=True); shutil.copy2(source,dest)
    for name in names:
        source=old/name
        if not source.is_dir() or source.is_symlink(): continue
        for f in source.rglob('*'):
            if not f.is_file() or f.is_symlink(): continue
            try: f.resolve().relative_to(source.resolve())
            except ValueError: continue
            dest=runtime/name/f.relative_to(source)
            if not dest.exists():
                dest.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(f,dest)


def find_dotnet_sdk():
    """Find a usable SDK even when Windows PATH has not been refreshed."""
    candidates=[]
    local=os.environ.get('LOCALAPPDATA')
    if local: candidates.append(str(Path(local)/'SMA Voice/dotnet/dotnet.exe'))
    current=shutil.which('dotnet')
    if current: candidates.append(current)
    for key in ('ProgramW6432','ProgramFiles','DOTNET_ROOT'):
        folder=os.environ.get(key)
        if folder:
            candidates.extend(str(Path(folder)/relative) for relative in ('dotnet/dotnet.exe','dotnet.exe'))
    for candidate in dict.fromkeys(candidates):
        if candidate!=current and not Path(candidate).is_file(): continue
        try:
            result=subprocess.run([candidate,'--list-sdks'],capture_output=True,text=True,check=True)
            if any(re.match(r'^(?:[6-9]|[1-9][0-9]+)\.\d+\.\d+',line.strip()) for line in result.stdout.splitlines()):
                return candidate
        except (OSError,subprocess.CalledProcessError): continue
    return None


def ensure_dotnet_sdk():
    dotnet=find_dotnet_sdk()
    if dotnet: return dotnet
    print('SDK .NET ausente. Instalando automaticamente o compilador C#...',flush=True)
    try:
        subprocess.run(['powershell.exe','-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',str(BASE/'INSTALAR_DOTNET.ps1')],check=True)
    except (OSError,subprocess.CalledProcessError) as exc:
        raise RuntimeError('Falha na instalacao do SDK .NET. Consulte o CMD e installer/INSTALAR_DOTNET.ps1 para diagnosticar. Nenhum plugin foi substituido.') from exc
    dotnet=find_dotnet_sdk()
    if not dotnet: raise RuntimeError('SDK .NET nao localizado apos instalacao. Consulte installer/INSTALAR_DOTNET.ps1. Nenhum plugin foi substituido.')
    return dotnet


def compile_il2cpp(source,out,refs,defines):
    """Compile against the actual game's interop files, never the recovered Mono DLLs."""
    import xml.etree.ElementTree as ET
    dotnet=ensure_dotnet_sdk()
    for ref in refs:
        if not ref.is_file(): raise RuntimeError('Referencia IL2CPP ausente: '+str(ref))
    project=ET.Element('Project',Sdk='Microsoft.NET.Sdk')
    props=ET.SubElement(project,'PropertyGroup')
    for key,value in {'TargetFramework':'net6.0','AssemblyName':out.stem,
                      'EnableDefaultCompileItems':'false','GenerateAssemblyInfo':'false',
                      'ImplicitUsings':'disable','Nullable':'disable',
                      'DefineConstants':';'.join(defines),'CopyLocalLockFileAssemblies':'false'}.items():
        ET.SubElement(props,key).text=value
    items=ET.SubElement(project,'ItemGroup')
    sources=[source]+([BASE/'src/VoiceSettings.cs',BASE/'src/SessionReport.cs'] if source.name in ('SMAVoiceAutoStart.cs','SMAVoiceCapture.cs') else [BASE/'src/VoiceSettings.cs'])
    for path in sources: ET.SubElement(items,'Compile',Include=str(path.resolve()))
    for ref in dict.fromkeys(refs):
        node=ET.SubElement(items,'Reference',Include=ref.stem)
        ET.SubElement(node,'HintPath').text=str(ref.resolve())
        ET.SubElement(node,'Private').text='false'
    with tempfile.TemporaryDirectory(prefix='sma-il2cpp-build-') as work:
        work=Path(work); csproj=work/(out.stem+'.csproj'); build=work/'bin'
        ET.ElementTree(project).write(csproj,encoding='utf-8',xml_declaration=True)
        # Isolate the restore from disabled sources and package-source mapping in
        # the user's NuGet configuration. Keep net6.0 for the BepInEx host.
        nuget=work/'NuGet.Config'
        nuget.write_text('<?xml version="1.0" encoding="utf-8"?>\n'
                         '<configuration><packageSources><clear />'
                         '<add key="nuget.org" value="https://api.nuget.org/v3/index.json" />'
                         '</packageSources></configuration>\n',encoding='utf-8')
        print('Restaurando referencias .NET 6:',out.name,flush=True)
        try:
            subprocess.run([dotnet,'restore',str(csproj),'--configfile',str(nuget),'--verbosity','minimal'],check=True,cwd=work)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError('Falha ao restaurar referencias .NET 6 para '+out.name+'. Verifique acesso HTTPS a api.nuget.org, proxy e os erros NU acima. Nenhum plugin foi substituido.') from exc
        print('Compilando IL2CPP:',out.name,flush=True)
        try:
            subprocess.run([dotnet,'build',str(csproj),'--no-restore','--configuration','Release','--output',str(build),'--nologo'],check=True,cwd=work)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError('Falha ao compilar '+out.name+' para IL2CPP. Veja os erros C# acima. Nenhum plugin foi substituido.') from exc
        binary=build/out.name
        if not binary.is_file() or binary.read_bytes()[:2]!=b'MZ': raise RuntimeError('DLL IL2CPP nao gerada: '+out.name)
        shutil.copy2(binary,out)


def compile_dll(source,out,refs=(),defines=()):
    if 'SMA_IL2CPP' in defines: return compile_il2cpp(source,out,refs,defines)
    win=Path(os.environ['WINDIR'])/'Microsoft.NET'
    csc=next((p for p in (win/'Framework64/v4.0.30319/csc.exe',win/'Framework/v4.0.30319/csc.exe') if p.is_file()),None)
    if csc is None: raise RuntimeError('Compilador .NET Framework 4.x csc.exe nao encontrado.')
    for ref in refs:
        if not ref.is_file(): raise RuntimeError('Referencia ausente: '+str(ref))
    subprocess.run([str(csc),'/nologo','/target:library','/optimize+','/out:'+str(out),*('/define:'+d for d in defines),*('/reference:'+str(r) for r in refs),str(source),*( [str(BASE/'src/VoiceSettings.cs'),str(BASE/'src/SessionReport.cs')] if source.name in ('SMAVoiceAutoStart.cs','SMAVoiceCapture.cs') else [str(BASE/'src/VoiceSettings.cs')] )],check=True)
    if not out.is_file(): raise RuntimeError('DLL nao gerada')

def bat_bytes(cmd):
    return ('@echo off\r\nsetlocal DisableDelayedExpansion\r\nchcp 65001 >nul\r\n'+cmd+'\r\nset "RC=%ERRORLEVEL%"\r\npause\r\nexit /b %RC%\r\n').encode('utf-8')


def config_value(text,section,key,value,only_if=None):
    """Modify exactly one BepInEx config key, preserving other keys/comments."""
    lines=text.splitlines(keepends=True); newline='\r\n' if '\r\n' in text else '\n'
    current=None; end=None; found=False
    for i,line in enumerate(lines):
        match=re.match(r'^\s*\[([^]]+)\]\s*$',line)
        if match:
            if current==section and end is None: end=i
            current=match.group(1).strip()
            if current==section: found=True
        if current==section:
            match=re.match(r'^(\s*'+re.escape(key)+r'\s*=\s*)([^\r\n]*)(\r?\n)?$',line,re.I)
            if match:
                if only_if is not None and match.group(2).strip().lower()!=only_if: return text
                lines[i]=match.group(1)+value+(match.group(3) or newline)
                return ''.join(lines)
    if found:
        pos=len(lines) if end is None else end
        if pos and not lines[pos-1].endswith(('\n','\r')): lines[pos-1]+=newline
        lines.insert(pos,key+' = '+value+newline)
    else:
        if lines and not lines[-1].endswith(('\n','\r')): lines[-1]+=newline
        lines.extend([newline+'['+section+']'+newline,key+' = '+value+newline])
    return ''.join(lines)


def migrate_box_settings(text):
    """Migrate only the previous shipped pair. Never change the balloon or custom timing pair."""
    old={'DELAY_CAIXA_NORMAL_MS':'200','FALLBACK_CAIXA_NORMAL_MS':'900'}
    new={'DELAY_CAIXA_NORMAL_MS':'150','FALLBACK_CAIXA_NORMAL_MS':'500'}
    matches={}
    for m in re.finditer(r'(?mi)^([ \t]*(DELAY_CAIXA_NORMAL_MS|FALLBACK_CAIXA_NORMAL_MS)[ \t]*=[ \t]*)([^\r\n]*)(?=\r?$)',text):
        matches[m.group(2).upper()]=m.group(3).strip()
    if matches!=old: return text
    return re.sub(r'(?mi)^([ \t]*(DELAY_CAIXA_NORMAL_MS|FALLBACK_CAIXA_NORMAL_MS)[ \t]*=[ \t]*)([^\r\n]*)(?=\r?$)',lambda m:m.group(1)+new[m.group(2).upper()],text)


def read_cfg(path):
    return path.read_bytes().decode('utf-8-sig') if path.exists() else ''


def install_files(updates, removals, runtime, root, backup):
    """Back up every target first; rollback overwritten/new files if a write fails."""
    targets=list(updates)+list(removals)
    if len(set(targets))!=len(targets): raise RuntimeError('Destinos duplicados na instalacao')
    originals={}
    for dst in targets:
        if dst.exists():
            target=backup_path(dst,runtime,root,backup)
            target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(dst,target)
            originals[dst]=target
    changed=[]
    def replace(dst,data):
        dst.parent.mkdir(parents=True,exist_ok=True)
        temp=dst.with_name(dst.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            if isinstance(data,Path): shutil.copy2(data,temp)
            else: temp.write_bytes(data)
            temp.replace(dst)
        finally: temp.unlink(missing_ok=True)
    try:
        for dst,data in updates.items():
            replace(dst,data); changed.append(dst)
            expected=data.read_bytes() if isinstance(data,Path) else data
            if dst.read_bytes()!=expected: raise RuntimeError('Verificacao de copia falhou: '+str(dst))
        for dst in removals:
            dst.unlink(); changed.append(dst)
    except BaseException:
        errors=[]
        for dst in reversed(changed):
            try:
                if dst in originals: replace(dst,originals[dst])
                else: dst.unlink(missing_ok=True)
            except OSError as exc: errors.append(str(exc))
        if errors: print('Falha restaurando arquivos; backup:',backup,errors,file=sys.stderr)
        raise



def old_support_launchers(runtime,root):
    old_names={'INICIAR_VOZ.bat','TESTAR_VOZ.bat','LISTAR_AUDIO.bat','VER_LOG.bat',
               'INSPECIONAR_INTERFACE.bat','VERIFICAR_INSTALACAO.bat','COLETAR_DIAGNOSTICO.bat',
               'ENVIAR_TESTE.bat','SMA_INSPECIONAR.bat'}
    allowed={runtime/name for name in old_names-{'SMA_INSPECIONAR.bat'}} | {root/'SMA_INSPECIONAR.bat'}
    try: files=json.loads((runtime/'MANIFESTO_INSTALACAO.json').read_text(encoding='utf-8-sig'))['files']
    except (OSError,ValueError,KeyError,TypeError): return []
    result=[]
    for item in files:
        try:
            path=Path(item['path'])
            if path in allowed and path.is_file() and not path.is_symlink() and hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']:
                if path not in result: result.append(path)
        except (OSError,KeyError,TypeError): continue
    return result

def set_processing(text,device):
    # A new environment's explicit device choice overrides only this setting.
    pattern=r'(?mi)^([ \t]*PROCESSAMENTO[ \t]*=)[^\r\n]*'
    if re.search(pattern,text):
        return re.sub(pattern,lambda m:m.group(1)+device,text)
    return text.rstrip('\r\n')+'\nPROCESSAMENTO='+device+'\n'

def reserve_new_xtts(runtime):
    """Reserve a fresh environment directory without touching an existing one."""
    runtime.mkdir(parents=True,exist_ok=True)
    for i in range(1,10001):
        env=runtime/('xtts' if i==1 else f'xtts-{i}')
        try:
            env.mkdir()
        except FileExistsError:
            continue
        (env/'sma-managed.txt').write_text('SMA Voice portable managed environment\n')
        return env
    raise RuntimeError('Nenhuma pasta livre para criar o XTTS.')

def choose_environment(kind,runtime):
    if kind=='existing':
        return Path(sys.executable), 'auto'
    if sys.version_info[:2]!=(3,11) or struct.calcsize('P')!=8:
        raise RuntimeError('Instalacao automatica exige Python 3.11 de 64 bits.')
    print('1 - NVIDIA CUDA (driver compativel com CUDA 12.8)\n2 - CPU (mais lento, sem GPU NVIDIA)')
    option=input('Motor / Device [1=NVIDIA CUDA, 2=CPU]: ').strip()
    if option not in ('1','2'): raise RuntimeError('Motor invalido')
    device='cuda' if option=='1' else 'cpu'
    env=reserve_new_xtts(runtime); python=env/'Scripts/python.exe'
    print('Novo ambiente isolado / New isolated environment:',env)
    subprocess.run([sys.executable,'-m','venv',str(env)],check=True)
    subprocess.run([str(python),'-m','pip','install','--upgrade','pip','setuptools','wheel'],check=True)
    index='https://download.pytorch.org/whl/'+('cu128' if device=='cuda' else 'cpu')
    marker=env/'sma-backend.txt'
    subprocess.run([str(python),'-m','pip','install','torch==2.8.0','torchaudio==2.8.0','--index-url',index],check=True)
    marker.write_text(device)
    subprocess.run([str(python),'-m','pip','install','-r',str(BASE/'requirements_auto.txt')],check=True)
    subprocess.run([str(python),'-m','pip','check'],check=True)
    return python,device

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--xtts',choices=['existing','auto'],default='existing'); ap.add_argument('--game',choices=['SMA','CMA']); ap.add_argument('--game-root'); options=ap.parse_args()
    if os.name!='nt': raise RuntimeError('Instalador para Windows.')
    if sys.version_info < (3,9): raise RuntimeError('Python 3.9 ou superior necessario; use seu ambiente XTTS funcional.')
    print('Feche o jogo/projeto e qualquer leitor de voz antes de instalar.')
    print('1) SMA - Some Modeling Agency (Mono / BepInEx 5)\n2) CMA - Corrupted Modeling Agency (IL2CPP / BepInEx 6)')
    choice=options.game or input('Jogo / Game [1/2]: ').strip().upper()
    choice={'1':'SMA','2':'CMA'}.get(choice,choice)
    if choice not in GAME_BACKENDS: raise RuntimeError('Escolha SMA ou CMA / Enter SMA or CMA.')
    raw=options.game_root or input('Pasta raiz do jogo ou executavel / Game folder or executable: ').strip()
    root,managed,exe,backend=select_game(choice,raw)
    mode='sma'; auto_enabled=True
    bepin=root/'BepInEx'
    shared=runtime_path(); runtime=project_runtime(shared,root); current={}
    plugins=bepin/'plugins/SMAVoiceCapture'
    central=plugins/'CONFIGURACOES.txt'
    queue=bepin/'SMA-Voice-Queue'
    print('Jogo escolhido / Selected game:',choice,'| Backend:',backend,'\nRaiz / Root:',root,'\nRuntime:',runtime)
    existing=runtime/'instalacao.json'
    if existing.is_file(): current=json.loads(existing.read_text(encoding='utf-8-sig'))
    assert_game_closed(exe)
    ensure_game_dependencies(choice,root,BASE.parent/'dependencies',install_files,lambda:assert_game_closed(exe))
    if backend=='IL2CPP' and not all((bepin/'interop'/n).is_file() for n in ('Il2Cppmscorlib.dll','UnityEngine.CoreModule.dll')):
        print('CMA: open the game once, wait for BepInEx to generate interop, then CLOSE it. / Abra o CMA, aguarde BepInEx/interop e FECHE o jogo.')
        input('Press ENTER only after closing the game / ENTER somente apos fechar: ')
        assert_game_closed(exe)
    refs=unity_references(root,managed,exe,mode,backend)
    backend_defines=('SMA_IL2CPP',) if backend=='IL2CPP' else ()
    auto_dir=bepin/'plugins/SMAVoiceAutoStart'
    assert_game_closed(exe)
    from voice_settings import read_settings
    settings_source=central if central.exists() else BASE/'config/CONFIGURACOES.txt'
    if not central.exists() and mode=='sma' and current.get('mode')=='generic':
        for old in (bepin/'plugins/SMA Voice/CONFIGURACOES.txt',root/'plugins/SMA Voice/CONFIGURACOES.txt'):
            if old.is_file(): settings_source=old; break
    settings=read_settings(settings_source)
    # Build both mod plugins before expensive XTTS setup or replacing mod files.
    with tempfile.TemporaryDirectory(prefix='sma-portable-') as tmp:
        tmp=Path(tmp)
        if auto_enabled:
            auto=tmp/'SMAVoiceAutoStart.dll'
            defines=backend_defines+(('SMA_GENERIC',) if mode!='sma' else ())
            if defines: compile_dll(BASE/'src/SMAVoiceAutoStart.cs',auto,refs,defines=defines)
            else: compile_dll(BASE/'src/SMAVoiceAutoStart.cs',auto,refs)
        if mode=='sma':
            capture=tmp/'SMAVoiceCapture.dll'
            capture_refs=list(dict.fromkeys(refs+[bepin/'core/0Harmony.dll']))
            if backend_defines: compile_dll(BASE/'src/SMAVoiceCapture.cs',capture,capture_refs,defines=backend_defines)
            else: compile_dll(BASE/'src/SMAVoiceCapture.cs',capture,capture_refs)
        backup=runtime/'backups'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        runtime.mkdir(parents=True,exist_ok=True); queue.mkdir(parents=True,exist_ok=True)
        # Hold the reader lock while replacing files; also refuse a reader from the previous active project.
        from sma_voice_stream import lock_queue
        locks=[]
        try:
            queues={queue.resolve()}
            if existing.is_file():
                previous=json.loads(existing.read_text(encoding='utf-8-sig'))
                prior=Path(previous.get('project_root') or runtime.parent)/previous['queue']
                if prior.is_dir(): queues.add(prior.resolve())
            for path in sorted(queues): locks.append(lock_queue(path))
            python,device=choose_environment(options.xtts,runtime)
            python=python.resolve()
            if options.xtts=='existing' and settings_source==BASE/'config/CONFIGURACOES.txt':
                selected=input('XTTS device / Processamento [auto/cpu/cuda] (ENTER=auto): ').strip().lower() or 'auto'
                if selected not in ('auto','cpu','cuda'): raise RuntimeError('Processamento invalido')
                device=selected
            if settings_source!=BASE/'config/CONFIGURACOES.txt' and options.xtts=='existing':
                device=settings['PROCESSAMENTO']
                print('Configuracao existente preservada; teste usara PROCESSAMENTO='+device)
            model_dir=None
            if options.xtts=='existing':
                previous_model=current.get('model_dir') if current.get('project_root') and Path(current['project_root']).resolve()==root else None
                prompt='Custom XTTS v2 model folder (ENTER = keep '+str(previous_model)+'; - = cache padrao): ' if previous_model else 'Custom XTTS v2 model folder (ENTER = default cache): '
                raw=input(prompt).strip().strip('"')
                if not raw and previous_model: raw=previous_model
                if raw and raw!='-':
                    model_dir=Path(raw).expanduser().resolve()
                    if not model_dir.is_dir(): raise RuntimeError('Pasta de modelo inexistente')
                    print('Use apenas checkpoints de fonte confiavel e com licenca de uso adequada.')
            print('Verificando XTTS v2. O download oficial do modelo pode pedir aceite de licenca; leia antes de aceitar.')
            check=[str(python),str(BASE/'runtime/verificar_xtts.py'),'--device',device,'--audio-device',str(settings['DISPOSITIVO_AUDIO'])]
            if model_dir: check+=['--model-dir',str(model_dir)]
            env=os.environ.copy(); env.pop('SMA_XTTS_MODEL_DIR',None)
            subprocess.run(check,check=True,env=env)
            updates={runtime/p.name:p for p in (BASE/'runtime').glob('*.py')}
            updates[plugins/'MANUAL_CONFIGURACOES.txt']=BASE/'config/MANUAL_CONFIGURACOES.txt'
            updates[plugins/'LOCAL_RUNTIME.txt']=(f'Modo: {mode}\nRuntime: {runtime}\nPython: {python}\nFila: {queue}\nConfiguracao: {central}\nAutoStart: {auto_enabled}\nVerificacao: {root / "SMA_VERIFICAR.bat"}\n').encode('utf-8')
            if not central.exists():
                defaults=read_cfg(settings_source)
                if settings_source==BASE/'config/CONFIGURACOES.txt': defaults=defaults.replace('PROCESSAMENTO=auto','PROCESSAMENTO='+device)
                updates[central]=defaults.encode('utf-8')
            elif mode=='sma':
                original_settings=read_cfg(central)
                migrated=original_settings
                if not re.search(r'(?mi)^[ \t]*BUFFER_CAIXA_NORMAL_MS[ \t]*=',migrated):
                    newline='\r\n' if '\r\n' in migrated else '\n'
                    migrated=migrated.rstrip('\r\n')+newline+'# Buffer exclusivo da caixa normal (limitado pelo buffer geral).'+newline+'BUFFER_CAIXA_NORMAL_MS=500'+newline
                if migrated!=original_settings:
                    updates[central]=migrated.encode('utf-8')
            # Append new settings without overwriting user choices (including false).
            pending=updates.get(central)
            effective=pending.decode('utf-8') if isinstance(pending,bytes) else read_cfg(central)
            if options.xtts=='auto':
                effective=set_processing(effective,device)
            for key in ('ENABLE_LOG','ENABLE_INSPECTOR','ENABLE_CMA_BARK','PROTEGER_AUDIO_IL2CPP') + ('ENABLE_CMA_FIXED_BOX','PRIORIDADE_CAIXA_FIXA'):
                if not re.search(r'(?mi)^[ \t]*'+key+r'[ \t]*=',effective):
                    effective=effective.rstrip('\r\n')+'\n'+key+'=true\n'
            for key in ('INICIO_CAIXA_POR_SEGMENTO','INICIO_BALAO_POR_SEGMENTO','PROTEGER_AUDIO_MONO','ENABLE_MONO_BARK_RECOVERY'):
                if not re.search(r'(?mi)^[ \t]*'+key+r'[ \t]*=',effective):
                    effective=effective.rstrip('\r\n')+'\n'+key+'=true\n'
            if not re.search(r'(?mi)^[ \t]*IDADE_MAX_CAIXA_FIXA_S[ \t]*=',effective):
                effective=effective.rstrip('\r\n')+'\nIDADE_MAX_CAIXA_FIXA_S=45\n'
            if pending is not None or effective!=read_cfg(central): updates[central]=effective.encode('utf-8')
            cfg=runtime/'instalacao.json'
            updates[cfg]=(json.dumps({'mode':mode,'project_root':str(root),'queue':str(queue),'settings':str(central),'model_dir':str(model_dir) if model_dir else None,'python':str(python),'autostart':auto_enabled,'unity_backend':backend,'selected_game':choice,'shared_voice_root':str(shared) if mode=='sma' else None},indent=2)+'\n').encode('utf-8')
            removals=[]
            if auto_enabled:
                assert_game_closed(exe)
                updates[auto_dir/auto.name]=auto
            if mode=='sma':
                updates[plugins/capture.name]=capture
                config=bepin/'config/local.sma.voicecapture.cfg'
                original=read_cfg(config)
                new=config_value(original,'BarkFilter','CaptureSource','Hybrid',only_if='diagnostic')
                if not original:
                    new+='\n[Translator]\nSubtitleReadyWaitSeconds = 0.15\nSubtitleFallbackWaitSeconds = 0.50\nFallbackWaitSeconds = 1.5\n'
                if new!=original:
                    print('Captura Hybrid ativada (Diagnostic nao exporta falas). Demais filtros preservados.')
                    updates[config]=new.encode('utf-8')
            if auto_enabled:
                config=bepin/'config/local.sma.voiceautostart.cfg'
                original=read_cfg(config)
                new=config_value(original,'Startup','Enabled','true')
                if new!=original: updates[config]=new.encode('utf-8')
                updates[bepin/'config/sma-voice-portable.paths']=(str(python)+'\n'+str(runtime)+'\n').encode('utf-8')
                # Only known mod DLL filenames. Backups live outside the plugin discovery tree.
                for path in (bepin/'plugins').rglob('*'):
                    if path.is_file() and (path.name.lower() in ({'smavoicecapture.dll','smavoiceautostart.dll'} if mode=='sma' else {'smavoiceautostart.dll'}) or (mode=='sma' and path==bepin/'plugins/SMA Voice/VoiceQueueBridge.dll')) and path not in updates:
                        removals.append(path); print('DLL duplicada sera movida para backup:',path)
            py=str(python).replace('%','%%')
            rt=str(runtime).replace('%','%%')
            # Only two end-user tools, at the selected game's root.
            updates[root/'SMA_VERIFICAR.bat']=bat_bytes(f'"{py}" "{rt}\\verificar_instalacao.py"')
            updates[root/'SMA_DIAGNOSTICO.bat']=bat_bytes(f'"{py}" "{rt}\\coletar_diagnostico.py" --support')
            # Remove only previously installed, unchanged launchers, backed up transactionally.
            removals.extend(old_support_launchers(runtime,root))
            import_legacy_data(root/'.sma-voice',runtime,mode)
            if mode=='sma': import_legacy_data(Path(r'C:\XTTS\SMA-Voice'),runtime,mode)
            # Report expected components and exact paths; the transaction verifies every copy.
            inventory={'mode':mode,'autostart':auto_enabled,'root':str(root),'runtime':str(runtime),'queue':str(queue),'files':[]}
            for dst,data in updates.items():
                inventory['files'].append({'path':str(dst),'sha256':hashlib.sha256(data.read_bytes() if isinstance(data,Path) else data).hexdigest(),'mutable':dst==central or dst.suffix.lower()=='.cfg'})
            for dst in (central, *((bepin/'config/local.sma.voiceautostart.cfg',) if auto_enabled else ()), *((bepin/'config/local.sma.voicecapture.cfg',) if mode=='sma' else ())):
                if dst not in updates and dst.is_file(): inventory['files'].append({'path':str(dst),'mutable':True,'sha256':hashlib.sha256(dst.read_bytes()).hexdigest()})
            updates[runtime/'MANIFESTO_INSTALACAO.json']=(json.dumps(inventory,indent=2,ensure_ascii=False)+'\n').encode('utf-8')
            install_files(updates,removals,runtime,root,backup)
        finally:
            for lock in reversed(locks): lock.close()
    print('Runtime:',runtime,'\nFila:',queue,'\nPlugins e configuracoes:',plugins,'\nBackup (se havia arquivos):',backup)
    print('AutoStart ATIVADO / Enabled. Abra o jogo normalmente / Start the game normally.\nSMA_VERIFICAR.bat + SMA_DIAGNOSTICO.bat: raiz do jogo / game root.\nConfira PRONTO ou READY no SMA_VOICE_*.log.')

if __name__=='__main__':
    try: main()
    except Exception as e: print('ERRO:',e,file=sys.stderr); raise SystemExit(1)
