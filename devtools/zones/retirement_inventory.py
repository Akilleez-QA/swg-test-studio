"""Source-derived retirement coverage. Pinned content is never a gameplay pass."""
from capacity import REPO,scene_names
from instance_definitions import definitions
from hosted_content import inventory as hosted_inventory
import hashlib,json,re

REVIEWED={'space_npe_falcon','space_ord_mantell','kashyyyk_rryatt_trail'}

def inventory():
    scenes=scene_names();defs=definitions()['definitions'];coverage=[]
    for d in defs:
        for scene in [d['name'],*d['legacy_aliases']]:
            coverage.append({'scene':scene,'definition':d['name'],'alias':scene!=d['name'],
                             'retirement':'reviewed' if scene in REVIEWED else 'pinned'})
    if {r['scene'] for r in coverage}!=scenes or len(coverage)!=len(scenes):
        raise ValueError('Every original scene must have exactly one coverage outcome')
    authored=hosted_inventory()
    inputs=dict(authored['input_sha256']);hosted=authored['hosted_content']
    for row in hosted:
        row['retirement']=('solo-session-proof' if row['scene']=='space_npe_falcon' else
                           'linked-set-proof' if row['scene']=='kashyyyk_rryatt_trail' else
                           'shared-host-pinned')
    tutorial=REPO/'src/engine/server/library/serverGame/src/shared/core/NewbieTutorial.cpp'
    source=tutorial.read_text()
    def constant(name):
        match=re.search(r'\b'+name+r'\("([^\"]+)"\)',source)
        if not match:raise ValueError('Missing authored medical-room constant: '+name)
        return match[1]
    inputs[tutorial.relative_to(REPO).as_posix()]=hashlib.sha256(tutorial.read_bytes()).hexdigest()
    scripted=[{'name':'medical_bay','scene':constant('s_sceneId'),'template':constant('s_tutorialTemplate'),
               'entry_cell':constant('s_startCellName'),'ownership':'one saved character',
               'recovery':'UTC daily reset','retirement':'host-pinned'}]
    if scripted[0]['scene'] not in scenes:raise ValueError('Unknown medical-room host')
    return {'schema_version':2,'scenes':sorted(coverage,key=lambda r:r['scene']),
            'canonical_definitions':len(defs),'scripted_recovery_rooms':scripted,'hosted_content':hosted,'input_sha256':inputs,
            'scope':'eligibility and pin guards; live acceptance is recorded separately'}

if __name__=='__main__':print(json.dumps(inventory(),indent=2))
