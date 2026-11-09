#!/usr/bin/env python3
"""Read-only canonical zone definitions and explicit legacy migration aliases."""
import json

from capacity import REPO, load_catalog, scene_names


def definitions(repo=REPO, catalog=None):
    known=scene_names(repo)
    catalog=load_catalog(known=known) if catalog is None else catalog
    canonical={name: {"name":name,"legacy_aliases":[],"family":name,
                      "capacity_unit":"player","content_review_required":True}
               for name in sorted(known)}
    for group in catalog['groups']:
        members=group['scenes']
        # The catalog explicitly lists the original definition first. This is
        # data-driven alias resolution, never suffix stripping.
        name=members[0]
        if name not in canonical or any(alias not in canonical for alias in members[1:]):
            raise ValueError('Overlapping or unknown definition family')
        canonical[name].update(family=group['id'],capacity_unit=group['capacity_unit'])
        if group['kind'] == 'duplicate_scene':
            canonical[name]['legacy_aliases']=members[1:]
            for alias in members[1:]:
                del canonical[alias]
        elif group['kind'] == 'duplicate_candidate':
            # Similar names are not migration aliases. These variants have
            # separate authored terrain/content and retain their own identity.
            for variant in members:
                canonical[variant].update(family=variant, capacity_unit=group['capacity_unit'])
        elif len(members)!=1:
            raise ValueError('Distinct content cannot be merged')
    return {"schema_version":1,"runtime_enabled":False,
            "identity_fields":["definition","instance_id"],
            "definitions":[canonical[name] for name in sorted(canonical)]}


if __name__=='__main__':
    print(json.dumps(definitions(),indent=2))
