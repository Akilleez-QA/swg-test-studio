"""Explicit temporary POB setup for the retained copied SWG fixture only."""
import re

SCHEMA='WGC_AE80ACB41011'
MARKER='private-crew-ship-fixture'
FLAG='capacityPrivateCrewFixture'


def policy():
    return dict(schema_version=1,temporary_owned_ship='object/ship/player/player_yt1300.iff',
                temporary_control_device='object/intangible/ship/yt1300_pcd.iff',
                temporary_skill='pilot_neutral_master',requires_no_existing_devices=True,
                cleanup_requires_packed_ship=True,cleanup_restores_original_skills=True,
                group_admission_enabled=False,canonical_release=False)


def clear(text):
    pattern=r'(?ms)^# '+MARKER+r' begin\n.*?^# '+MARKER+r' end\n?'
    starts=len(re.findall(r'(?m)^# '+MARKER+r' begin$',text))
    ends=len(re.findall(r'(?m)^# '+MARKER+r' end$',text))
    if starts!=ends or starts>1 or len(re.findall(pattern,text))!=starts:
        raise ValueError('Malformed owned POB fixture block')
    plain=re.sub(pattern,'',text)
    if re.search(r'(?m)^\s*'+FLAG+r'\s*=',plain):
        raise ValueError('POB fixture flag belongs to an unknown configuration source')
    return plain


def configure(text,role,enabled,schema,private):
    if type(enabled) is not bool:raise ValueError('Typed POB fixture opt-in required')
    plain=clear(text)
    if not enabled:return plain
    if schema!=SCHEMA or not isinstance(private,dict) or private.get('private_player_admission') is not True or private.get('canonical_release') is not False:
        raise ValueError('Explicit retained-schema private-entry fixture required for POB setup')
    if role!='game':return plain
    return plain.rstrip()+'\n# '+MARKER+' begin\n[GameServer]\n'+FLAG+'=1\n# '+MARKER+' end\n'
