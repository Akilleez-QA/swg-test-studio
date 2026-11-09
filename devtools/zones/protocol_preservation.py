"""Read-only preservation snapshots for the retained two-character fixture."""
import hashlib
import json
import re
from protocol_driver import sql


def snapshot(project, schema):
    if project != 'swg-cold-test-d9d6e6af' or schema != 'WGC_AE80ACB41011':
        raise ValueError('Original-character preservation scope requires the reviewed retained fixture')
    roots = '1785924018,2231922704,2421959299,2421960571,2421959297,2421960569'
    hierarchy = sql(project, schema, f"""select distinct json_object('id' value to_char(object_id))
        from {schema}.objects start with object_id in ({roots})
        connect by nocycle prior object_id=contained_by or prior object_id=load_with;""")
    ids = sorted({r['id'] for r in hierarchy})
    if not 45 <= len(ids) <= 4096 or any(not re.fullmatch('[1-9][0-9]{0,18}', value) for value in ids):
        raise RuntimeError('Original character hierarchy identity/bound changed')
    scope = ','.join(ids)
    rows = sql(project, schema, f"""select json_object('kind' value 'object','row' value
        json_object(*) format json) from {schema}.objects where object_id in ({scope}) order by object_id;
        select json_object('kind' value 'variable','object' value to_char(object_id),'name' value name,'value' value value)
        from {schema}.object_variables_view where object_id in ({scope}) order by object_id,name;""")
    if sum(row['kind'] == 'object' for row in rows) != len(ids):
        raise RuntimeError('Incomplete original character preservation snapshot')
    return {'objects': len(ids), 'rows': rows,
            'sha256': hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()}
