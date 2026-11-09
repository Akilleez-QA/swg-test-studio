"""Select an original clone menu for an already-dead retained test actor."""
import math
import time
from capacity import REPO,SERVER_TABLES,read_table
from protocol_driver import bot_query,settled


def choose(row,page,scene):
    if row.get('dead')!='true' or page.get('name')!='Script.listBox' or str(page.get('page'))!=row.get('clone_page'):
        raise RuntimeError('Current dead-player clone menu required')
    choices=[]
    for index,value in enumerate(row.get('clone_targets','none').split(',')):
        fields=value.split(':')
        if len(fields)!=5:raise RuntimeError('No complete original clone destinations available')
        point=[float(v) for v in fields[1:4]]
        if not all(math.isfinite(v) and abs(v)<=16000 for v in point):raise RuntimeError('Invalid clone location')
        if fields[0]==scene:choices.append((index,dict(zip(('x','y','z'),point))))
    if len(choices)!=1:raise RuntimeError('One unambiguous original destination required: '+scene)
    return choices[0]


def execute(project,bot,session,scene):
    before=settled(project,bot)
    if scene!='kashyyyk_main' or before.get('scene') not in ('kashyyyk_hunting','kashyyyk_dead_forest'):
        raise ValueError('Reviewed public Kashyyyk clone route required')
    table=REPO/SERVER_TABLES/'cloning/clone_mapping.tab'
    if not any(r['scene']==before['scene'] and r['clone_scene']==scene for _,r in read_table(table)):
        raise RuntimeError('Original clone mapping missing')
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        page=session.wait('sui',max(.1,deadline-time.monotonic()))
        row=bot_query(project,bot)
        if row and str(page.get('page'))==row.get('clone_page'):break
    else:raise TimeoutError('Correlated clone menu missing')
    index,point=choose(row,page,scene)
    session.send(f"answer {page['page']} ok {index}");session.wait('sui_answered',10)
    arrival=session.wait('scene_ready',120)
    after=settled(project,bot)
    if (arrival.get('scene')!='terrain/'+scene+'.trn' or after.get('scene')!=scene or after.get('instance')!='0' or
            after.get('dead')!='false' or any(abs(float(after[k])-point[k])>tolerance for k,tolerance in (('x',.25),('y',3),('z',.25)))):
        raise RuntimeError('Original clone selection did not revive at the authoritative Kachirho destination: '+str(after))
    return dict(before=before,menu=row,page=page,selection=index,expected=point,arrival=arrival,after=after)
