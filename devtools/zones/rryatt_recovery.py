"""Real protocol Rryatt mastery/clone/unstick actions; fixture setup is explicit."""
import math,time
from protocol_driver import bot_query

PREFIX='conversation/ep3_achonnko:'
TOKENS=['s_187','s_191','s_195','s_199']

def offered(case,key,target):
    peer=case.sessions[key]
    peer.send('converse '+target)
    options=peer.wait('conversation_responses',20)
    if options['target']!=target:raise RuntimeError('Master conversation target changed')
    return options

def answer(case,key,options,token):
    peer=case.sessions[key];value=PREFIX+token
    if value not in options['responses']:raise RuntimeError('Master response not offered: '+value+' '+str(options))
    peer.send('respond '+value);peer.wait('conversation_answered',10)

def master(case,key):
    for attempt in range(16):
        setup=case.setup(key,'botRryattMaster')
        if case.setup_rows[key]['guide_visible']=='true':return setup
    raise RuntimeError('Master has no visible nearby approach')

def await_flag(case,key,name,timeout=20):
    deadline=time.monotonic()+timeout
    while True:
        row=case.row(key)
        if row.get(name)=='true':return row
        if time.monotonic()>=deadline:raise RuntimeError('Quest state did not settle: '+name+' '+str(row))
        time.sleep(.5)

def begin_mastery(case,key):
    case.setup(key,'botRryattQuestReset')
    setup=master(case,key)
    options=offered(case,key,setup['target'])
    if any(PREFIX+t in options['responses'] for t in TOKENS):raise RuntimeError('Unlearned shortcuts offered')
    for token in ['s_173','s_177','s_181']:
        answer(case,key,options,token)
        if token!='s_181':options=case.sessions[key].wait('conversation_responses',20)
    row=await_flag(case,key,'mastery_active')
    case.report.setdefault('rryatt_mastery_grants',[]).append({'bot':key,'setup':setup,'after':row})

def wait_point(case,key,expected,controller,timeout=60):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        row=bot_query(case.project,case.bots[key])
        if (row and row['scene']==expected['scene'] and row['instance']==expected['instance'] and
            all(abs(float(row[k])-float(expected[k]))<=.15 for k in ['x','z'])):
            case.sessions[key].send('awaitReady');case.sessions[key].wait('action_ready',30)
            row=case.row(key)
            if row['instance_controller']!=controller or row['outstanding']!='false':raise RuntimeError('Recovery lost controller/settlement')
            if abs(float(row['y'])-float(expected['y']))>3:raise RuntimeError('Recovery missed authored floor: '+str(row))
            return row
        time.sleep(.5)
    raise RuntimeError('Rryatt recovery missed expected point: '+str(row))

def complete_recovery(case,key,entrance):
    before=case.row(key);controller=before['instance_controller'];anchor=int(entrance['buildout_row'])
    await_flag(case,key,'mastery')
    for index,token in enumerate(TOKENS):
        setup=master(case,key);options=offered(case,key,setup['target'])
        if not all(PREFIX+t in options['responses'] for t in TOKENS):raise RuntimeError('Completed mastery shortcuts missing')
        route,x,y,z=setup['routes'].split(',')[index].split(':')
        answer(case,key,options,token)
        expected={'scene':'kashyyyk_rryatt_trail','instance':before['instance'],'x':x,'y':y,'z':z}
        row=wait_point(case,key,expected,controller)
        if int(row['buildout_row'])!=anchor+index:raise RuntimeError('Shortcut crossed linked set')
        case.report.setdefault('rryatt_shortcuts',[]).append({'bot':key,'route':route,'setup':setup,'after':row})
        print('SCENARIO mastery '+key+' '+route,flush=True)

    clone(case,key)

    case.rryatt_guide(key,0)
    route=next(r for r in reversed(case.report['rryatt_routes']) if r['bot']==key)
    master(case,key)
    for foreign in [False,True]:
        if foreign:case.setup(key,'botRryattForeignGuide')
        start=case.row(key);started=time.monotonic();case.sessions[key].send('unstick');case.sessions[key].wait('unstick_requested',10)
        expected=entrance if foreign else route['after']
        row=wait_point(case,key,expected,controller,timeout=65)
        elapsed=time.monotonic()-started
        if elapsed<28:raise RuntimeError('Normal non-god unstick delay bypassed')
        if foreign and row['last_rryatt_guide'] not in ('null','0'):raise RuntimeError('Foreign guide reference retained')
        case.report.setdefault('rryatt_unstucks',[]).append({'bot':key,'foreign_guide':foreign,'before':start,'after':row,'seconds':elapsed})
        print('SCENARIO unstick '+key+' foreign='+str(foreign),flush=True)

def clone(case,key):
    before=case.row(key);controller=before['instance_controller'];anchor=int(before['buildout_row'])//4*4
    # Death is explicit bot setup; selection and respawn use the real SUI path.
    case.setup(key,'botRryattDeath')
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        page=case.sessions[key].wait('sui',max(.1,deadline-time.monotonic()))
        row=bot_query(case.project,case.bots[key])
        if str(page['page'])==row['clone_page']:break
    else:raise RuntimeError('Correlated clone page missing')
    targets=row['clone_targets'].split(',');choices=[]
    for i,value in enumerate(targets):
        fields=value.split(':')
        if len(fields)==5 and fields[0]=='kashyyyk_rryatt_trail' and int(fields[4])==anchor:choices.append((i,fields))
        elif value!='none':raise RuntimeError('Clone menu offered another linked set: '+str(row))
    if len(choices)!=1 or page['name']!='Script.listBox' or str(page['page'])!=row['clone_page']:
        raise RuntimeError('Expected one correlated own-set clone choice: '+str(page)+' '+str(row))
    index,fields=choices[0];case.sessions[key].send(f"answer {page['page']} ok {index}");case.sessions[key].wait('sui_answered',10)
    expected=dict(scene=fields[0],instance=before['instance'],x=fields[1],y=fields[2],z=fields[3])
    row=wait_point(case,key,expected,controller)
    deadline=time.monotonic()+30
    while row['dead']!='false' and time.monotonic()<deadline:time.sleep(.5);row=case.row(key)
    if row['dead']!='false':raise RuntimeError('Clone did not resurrect bot')
    case.report.setdefault('rryatt_clones',[]).append({'bot':key,'anchor':anchor,'page':page,'targets':targets,'after':row})
    print('SCENARIO clone '+key+' anchor='+str(anchor),flush=True)



def assert_guide_audit(fields):
    from rryatt_linked import ROUTES
    rows=[value.split(':') for value in fields.get('guides','').split(',')]
    expected={(anchor+row,route) for anchor in range(0,24,4) for row,route in zip((0,0,0,1,1,2,2,3),ROUTES)}
    if fields.get('count')!='48' or len(rows)!=48 or any(len(row)!=13 for row in rows):
        raise RuntimeError('Expected all 48 original Rryatt guides')
    if {(int(row[0]),row[1]) for row in rows}!=expected or len({row[2] for row in rows})!=48:
        raise RuntimeError('Original guide identities or linked rows changed')
    for row in rows:
        point=list(map(float,row[3:9]))
        if (not all(math.isfinite(value) for value in point) or abs(point[0]-point[3])>.1 or
                abs(point[2]-point[5])>.1 or abs(point[1]-point[4])>3 or row[9]!='true' or row[12]!='true'):
            raise RuntimeError('Original guide left its stationary authored platform: '+str(row))
    return rows


def audit_guides(case,key,label):
    fields=bot_query(case.project,case.bots[key],'botRryattAudit')
    rows=assert_guide_audit(fields)
    case.report.setdefault('rryatt_guide_audits',[]).append({'label':label,'worker':fields['worker'],'guides':rows})
    print('SCENARIO authored_guide_audit '+label+' count='+str(len(rows)),flush=True)
