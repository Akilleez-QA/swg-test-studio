"""Typed whole-world policy selection for the retained SWG test fixture.

This renders a fixture plan only. It neither activates a canonical release nor
supplies hosted-room readiness, authored access or retirement acceptance.
"""
import runtime_policy
import world_runtime_policy
from instance_scope import load as instance_scope


def supports_worlds(manifest):
    proof=manifest.get('whole_world_families')
    return (isinstance(proof,dict) and type(proof.get('schema_version')) is int and
            proof['schema_version']==1 and type(proof.get('configured_families')) is int and
            proof['configured_families']==18 and proof.get('configured_definitions')==sorted(world_runtime_policy.eligible()) and
            proof.get('scope_revision')==instance_scope()['revision'] and isinstance(proof.get('native_build'),str) and
            bool(proof['native_build']))


def extend(state, selected, definitions, capacity=2, maximum=2):
    runtime_policy.validate_state(state)
    if (state.get('schema_version') != 4 or not isinstance(selected,list) or
            not isinstance(definitions,list) or not definitions or
            any(not isinstance(s,str) for s in definitions) or
            len(set(definitions)) != len(definitions)):
        raise ValueError('Explicit distinct world definitions and a linked-set fixture profile required')
    extra = world_runtime_policy.eligible() - {runtime_policy.ORD}
    if not set(definitions) <= extra:
        raise ValueError('Only canonical eligible whole-world definitions may be added')
    result = {'schema_version':5,'mode':'world_instances','base':dict(state),
              'world_families':[{'definition':s,'capacity':capacity,'minimum_ready':1,
                                 'maximum_instances':maximum,'growth_percent':75}
                                for s in sorted(definitions)]}
    selection=list(dict.fromkeys(selected+sorted(definitions)))
    world_runtime_policy.report(result,selection)
    return result,selection


def additions(report):
    """Validate report identities before deriving expected running workers."""
    definitions=report.get('whole_world_families',[])
    if (not isinstance(definitions,list) or any(not isinstance(s,str) for s in definitions) or
            len(definitions)!=len(set(definitions)) or definitions!=sorted(definitions)):
        raise ValueError('Typed sorted whole-world fixture definitions required')
    state=report.get('policy')
    if not definitions:
        if isinstance(state,dict) and state.get('schema_version')==5:
            raise ValueError('Expanded policy cannot omit its fixture definitions')
        return []
    runtime_policy.validate_state(state)
    if (state['schema_version']!=5 or
            definitions!=sorted(row['definition'] for row in state['world_families'])):
        raise ValueError('Fixture definitions must match the complete expanded policy')
    return definitions
