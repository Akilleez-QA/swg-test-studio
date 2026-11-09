"""Opt-in recorder capability and narrow storage mount for isolated SWG fixtures."""
import hashlib
from pathlib import Path
import re

REPO=Path(__file__).resolve().parents[2]
CAPTURE_ROOT='/teststudio-capture'
BEGIN='# BEGIN SWG TEST STUDIO RECORDING'
END='# END SWG TEST STUDIO RECORDING'
NATIVE=(
 'src/engine/server/library/serverGame/src/shared/core/TestStudioRecorder.h',
 'src/engine/server/library/serverGame/src/shared/core/TestStudioCapture.h',
 'src/engine/server/library/serverGame/src/shared/core/Client.cpp',
 'src/engine/server/library/serverGame/src/shared/core/NameManager.h',
 'src/engine/server/library/serverGame/src/shared/core/NameManager.cpp',
 'src/engine/server/library/serverGame/src/shared/network/CentralConnection.cpp',
 'src/engine/server/library/serverGame/src/shared/network/CentralConnection.h',
 'src/engine/server/library/serverGame/src/shared/object/ServerObject.cpp',
 'src/engine/server/library/serverGame/src/shared/core/ServerUIManager.cpp',
 'src/engine/server/library/serverGame/src/shared/command/CommandCppFuncs.cpp',
 'src/engine/server/library/serverGame/src/shared/object/CreatureObject.cpp',
 'src/engine/server/library/serverGame/src/shared/object/GroupObject.cpp',
 'src/engine/server/library/serverGame/src/shared/object/TangibleObject_Conversation.cpp',
 'src/engine/server/library/serverGame/src/shared/controller/ServerController.cpp',
 'src/engine/server/library/serverGame/src/shared/controller/TangibleController.cpp',
 'src/engine/server/library/serverGame/src/shared/controller/PlayerCreatureController.cpp')
TOOLS=('devtools/teststudio_server/retained_peer.py','devtools/teststudio_server/recording_fixture.py',
       'devtools/zones/protocol_driver.py','devtools/zones/fixtures/protocol_bot.java')


def contract():
    return dict(schema_version=1,capture_contract=2,action_capture=1,terminal_metadata=2,adapter_version=1,capture_root=CAPTURE_ROOT,
                inputs={name:hashlib.sha256((REPO/name).read_bytes()).hexdigest() for name in NATIVE+TOOLS})


def supports(manifest):
    expected=contract()
    if manifest.get('test_studio_recording')!=expected:return False
    native={r['path']:r['sha256'] for r in manifest.get('native_sources',[])}
    return all(native.get(name)==expected['inputs'][name] for name in NATIVE)


def configure(text,enabled):
    if type(enabled) is not bool:raise ValueError('Explicit recorder Boolean required')
    if text.count(BEGIN)!=text.count(END) or text.count(BEGIN)>1:raise ValueError('Malformed recorder config block')
    text=re.sub(re.escape(BEGIN)+r'.*?'+re.escape(END)+r'\n?', '',text,flags=re.S)
    text=re.sub(r'(?m)^testStudioRecorder=.*\n?', '',text)
    return text.rstrip()+'\n'+BEGIN+'\n[GameServer]\ntestStudioRecorder='+('true' if enabled else 'false')+'\n'+END+'\n'


def mount(service,folder,enabled):
    if type(enabled) is not bool:raise ValueError('Explicit recorder Boolean required')
    folder=Path(folder).resolve(strict=True);root=folder/'fixture/teststudio'
    if root.is_symlink() or root.parent.is_symlink() or root.resolve()!=root:raise ValueError('Recorder storage path changed')
    if root.exists() and any(root.glob('*.control')):raise ValueError('Stop the owned recording before fixture reconfiguration')
    volumes=[]
    for value in service.get('volumes',[]):
        if isinstance(value,str) and re.search(r':'+re.escape(CAPTURE_ROOT)+r'(?::[^:]*)?$',value):continue
        if isinstance(value,dict) and value.get('target')==CAPTURE_ROOT:
            raise ValueError('Unknown structured recording mount')
        volumes.append(value)
    if enabled:
        root.mkdir(parents=True,exist_ok=True,mode=0o700)
        volumes.append(str(root)+':'+CAPTURE_ROOT+':rw')
    service['volumes']=volumes
