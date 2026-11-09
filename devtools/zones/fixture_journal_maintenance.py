"""Existing SWG fixture journals, mounted directly without added capabilities."""
from pathlib import Path
import hashlib
import json
import re
import stat

ROOTS={'/capacity-journal/instances':('capacity-journal','instances'),
       '/capacity-journal/admission':('capacity-journal','admission'),
       '/capacity-journal/family-logins':('capacity-journal','family-logins'),
       '/login-journal/records':('login-journal','records')}
ACK={'/capacity-journal/instances':'--acknowledge-stopped',
     '/capacity-journal/admission':'--acknowledge-admission-stopped',
     '/capacity-journal/family-logins':'--acknowledge-family-logins-stopped',
     '/login-journal/records':'--acknowledge-login-stopped'}


def runtime_mounts(overlay):
    manifest=json.loads((overlay/'manifest.json').read_text())
    files=manifest.get('files',{})
    selected=[name for name in files if name=='bin/instance-journal' or name.startswith('lib/')]
    if 'bin/instance-journal' not in selected or not 2<=len(selected)<=256:
        raise ValueError('Bounded verified maintenance executable/libraries required')
    mounts=[]
    for name in sorted(selected):
        if name!='bin/instance-journal' and not re.fullmatch(r'lib/lib[A-Za-z0-9_.+-]+\.so(?:\.[0-9]+)*',name):
            raise ValueError('Unexpected native runtime artifact')
        path=overlay/name;digest=files[name].get('sha256','')
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(overlay):raise ValueError('Native runtime artifact escaped its overlay')
        info=path.stat()
        required=stat.S_IROTH|(stat.S_IXOTH if name.startswith('bin/') else 0)
        if not stat.S_ISREG(info.st_mode) or info.st_mode&required!=required:
            raise ValueError('Native artifact must already be readable/executable without changing its mode')
        with path.open('rb') as stream:
            header=stream.read(20);stream.seek(0)
            actual=hashlib.file_digest(stream,'sha256').hexdigest()
        if header[:6]!=b'\x7fELF\x02\x01' or header[18:20]!=b'\x3e\0' or digest!=actual:
            raise ValueError('Verified ELF64 runtime artifact required')
        mounts+=['--volume',str(path)+':/maintenance/'+name+':ro']
    return mounts


def verify_metadata(value):
    if not stat.S_ISDIR(value.st_mode) or stat.S_IMODE(value.st_mode)!=0o700 or value.st_uid!=0 or value.st_gid!=0:
        raise ValueError('Existing native journal must retain server ownership and mode 0700')


def verify_root(stage,path):
    if path not in ROOTS:raise ValueError('Unknown fixed fixture journal')
    stage=Path(stage).resolve(strict=True)
    if stage.name!='runtime' or not re.fullmatch('client-[a-f0-9]{12}',stage.parent.name) or not re.fullmatch('swg-cold-test-[a-f0-9]{8}',stage.parent.parent.name):
        raise ValueError('Exact retained SWG fixture runtime required')
    parent,leaf=ROOTS[path];source=stage/parent/leaf
    if source.is_symlink() or (stage/parent).is_symlink() or not source.resolve(strict=True).is_relative_to(stage):
        raise ValueError('Fixture journal must remain inside its exact runtime directory')
    verify_metadata(source.stat())
    return source


def command(stage,path,option,definitions,overlay,image):
    if ACK.get(path)!=option:raise ValueError('Only the matching existing-journal acknowledgement is allowed')
    if not re.fullmatch(r'starwarsgalaxies/central:[A-Za-z0-9_.-]+',image):raise ValueError('Pinned SWG Central image required')
    from instance_scope import load
    known={row['definition'] for row in load()['definitions']}
    # Fixed stopped-generation acknowledgement reads historical records. It
    # cannot launch a worker or configure a forbidden persistent-world policy.
    if not isinstance(definitions,(tuple,list)) or any(not isinstance(n,str) or n not in known for n in definitions):
        raise ValueError('Explicit canonical decoding definitions required')
    if (path=='/capacity-journal/instances')!=bool(definitions):raise ValueError('Only the world journal accepts its explicit definition set')
    source=verify_root(stage,path);overlay=Path(overlay).resolve(strict=True)
    mounts=runtime_mounts(overlay)
    script='export LD_LIBRARY_PATH=/maintenance/lib:/opt/whitengold/lib:$LD_LIBRARY_PATH; exec /maintenance/bin/instance-journal "$@"'
    return ['docker','run','--rm','--pull','never','--network','none','--read-only','--user','0:0','--cap-drop','ALL',
            '--security-opt','no-new-privileges:true']+mounts+['--volume',str(source)+':/journal',
            '--entrypoint','/bin/sh',image,'-ec',script,'existing-swg-journal',option,'/journal']+list(definitions)
