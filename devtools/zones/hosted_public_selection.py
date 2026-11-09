"""Validate public fixture reports before accepting their original host scenes."""
import hosted_public_fixture

SOURCES={'myyydril_caverns':'kashyyyk_dead_forest','nova_orion_station':'space_nova_orion'}


def additions(report):
    value=report.get('hosted_public_fixture')
    if value is None:return []
    if not isinstance(value,dict):raise ValueError('Typed original-host public policy required')
    rows=value.get('families')
    if not isinstance(rows,list) or not rows:raise ValueError('Public family rows required')
    try:
        families=[r['family'] for r in rows]
        limit=rows[0]['limit']
    except (KeyError,TypeError) as error:
        raise ValueError('Typed public family identity and budget required') from error
    expected=hosted_public_fixture.policy(families,limit)
    if value!=expected:raise ValueError('Stale or modified original-host public profile')
    worlds=report.get('whole_world_families')
    if (not isinstance(worlds,list) or any(not isinstance(w,str) for w in worlds) or
        len(worlds)!=len(set(worlds)) or worlds!=sorted(worlds) or
        any(SOURCES[f] not in worlds for f in families)):
        raise ValueError('Public profile requires its explicitly selected original source world')
    return sorted({r['definition'] for r in rows})
