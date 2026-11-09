"""Validate an observed retirement boundary before a separately scoped fault.

This is a status consistency check. It supplies no PID, ownership, empty-world,
save or signal authority; the live runner must prove those independently.
"""
import re

FAMILIES=frozenset(('space_npe_falcon','space_ord_mantell','kashyyyk_rryatt_trail'))
PHASES=('fencing','authorizing','freezing','committing','stopping_games','stopping_planet')


def number(value,maximum,zero=False):
    if (not isinstance(value,str) or not re.fullmatch('0|[1-9][0-9]{0,18}',value) or
            int(value)>maximum or (not zero and value=='0')):
        raise ValueError('Canonical bounded native counter required')
    return int(value)


def boundary(row,expected,phase,nodes):
    """Require the same native operation and the intended unreaped boundary."""
    identity=('definition','instance','generation','operation','workers')
    if (phase not in PHASES or not isinstance(expected,dict) or set(expected)!=set(identity) or
            not isinstance(expected['definition'],str) or expected['definition'] not in FAMILIES or type(nodes) is not int or not 1<=nodes<=32):
        raise ValueError('Explicit reviewed family, operation and supervisor count required')
    for key in ('instance','generation','operation'):number(expected[key],9223372036854775807)
    workers=number(expected['workers'],256)
    if (not isinstance(row,dict) or any(row.get(key)!=expected[key] for key in identity) or
            row.get('state')!=phase or row.get('failed_at')!='idle' or row.get('failure_reason')!='none'):
        raise RuntimeError('Retirement operation or boundary changed')
    observed=number(row.get('nodes'),32)
    counters={name:number(row.get(name),256 if name!='fenced_nodes' else 32,True)
              for name in ('frozen','saved','game_reaps','reaped_launches','fenced_nodes')}
    frozen,saved,reaped,launches,fenced=(counters[n] for n in ('frozen','saved','game_reaps','reaped_launches','fenced_nodes'))
    if (observed!=nodes or fenced>nodes or frozen>workers or saved>frozen or reaped>saved or launches>workers+1):
        raise RuntimeError('Inconsistent retirement proof counters')
    if phase!='fencing' and fenced!=nodes:
        raise RuntimeError('Complete supervisor fencing is required')
    if phase in ('fencing','authorizing') and any((frozen,saved,reaped,launches)):
        raise RuntimeError('Boundary has advanced past authorization')
    if phase=='freezing' and (frozen>=workers or any((saved,reaped,launches))):
        raise RuntimeError('Boundary has advanced past the held freeze')
    if phase=='committing' and (frozen!=workers or any((saved,reaped,launches))):
        raise RuntimeError('Boundary lacks the exact frozen roster or has advanced')
    if phase=='stopping_games' and (frozen!=workers or saved!=workers or reaped or launches>workers):
        raise RuntimeError('Boundary lacks committed workers or has advanced past game reaping')
    if phase=='stopping_planet' and (frozen!=workers or saved!=workers or reaped!=workers or launches!=workers):
        raise RuntimeError('Controller reap is no longer held after complete game reaping')
    return dict(row)