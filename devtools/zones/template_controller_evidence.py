"""Read controller-related TPF inheritance; never infer runtime readiness.

Only literal scripts and controller objvars are resolved. Unsupported relevant
syntax, missing bases and cycles fail closed instead of inventing a controller.
"""
import copy
import hashlib
import json
from pathlib import Path,PurePosixPath
import re

ROOT=Path('dsrc/sku.0/sys.server/compiled/game')
FIELDS={'instance_name','isControllerObject','space_dungeon.name','instance.data_table'}
TOKEN=re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/|\s+|[A-Za-z_][A-Za-z_0-9.]*|-?[0-9]+|.',re.S)


def _text(source):
    return ''.join(''.join(c if c in '\r\n' else ' ' for c in m[0]) if m[0].startswith(('//','/*')) else m[0] for m in TOKEN.finditer(source))


def _tokens(source):
    return [m[0] for m in TOKEN.finditer(source) if not m[0].isspace() and not m[0].startswith(('//','/*'))]


def _items(tokens,start):
    if tokens[start]!='[':raise ValueError('Expected literal template list')
    stack=[']'];items=[];current=[];pairs={'[':']','(':')','{':'}'}
    for i in range(start+1,len(tokens)):
        token=tokens[i]
        if token in pairs:stack.append(pairs[token])
        elif token in (']',')','}'):
            if not stack or token!=stack.pop():raise ValueError('Malformed template list')
            if not stack:
                if current:items.append(current)
                return items,i+1
        if token==',' and len(stack)==1:
            if current:items.append(current)
            current=[]
        else:current.append(token)
    raise ValueError('Unterminated template list')


class Templates:
    def __init__(self,repo):
        self.repo=Path(repo);self.inputs={};self.cache={}

    def resolve(self,name,stack=()):
        if (not isinstance(name,str) or not name.startswith('object/') or not name.endswith('.iff') or
                '..' in PurePosixPath(name).parts or PurePosixPath(name).as_posix()!=name or not re.fullmatch(r'[A-Za-z0-9_./-]+',name)):
            raise ValueError('Controller evidence needs an original object template path')
        relative=ROOT/PurePosixPath(name).with_suffix('.tpf')
        key=relative.as_posix()
        if key in stack or len(stack)>=64:raise ValueError('Controller template inheritance cycle/depth')
        if key in self.cache:return copy.deepcopy(self.cache[key])
        path=self.repo/relative
        if not path.resolve().is_relative_to(self.repo.resolve()):raise ValueError('Controller template leaves the SWG source root')
        if not path.is_file():return dict(declarations={},scripts=[],sources=[],complete=False,missing=[key])
        raw=path.read_bytes();self.inputs[key]=hashlib.sha256(raw).hexdigest()
        source=_text(raw.decode('latin-1'))
        bases=re.findall(r'^\s*@base\s+("[^"\n]+"|[^\s]+)\s*$',source,re.M)
        if len(re.findall(r'^\s*@base\b',source,re.M))!=len(bases):raise ValueError('Unsupported template base declaration: '+key)
        if len(bases)>1:raise ValueError('Multiple template bases: '+key)
        result=(self.resolve(json.loads(bases[0]) if bases[0].startswith('"') else bases[0],stack+(key,)) if bases else
                dict(declarations={},scripts=[],sources=[],complete=True,missing=[]))
        result['sources'].append(key)
        tokens=_tokens(source);i=0
        while i<len(tokens):
            field=tokens[i]
            if field not in ('objvars','scripts') or i+1>=len(tokens) or tokens[i+1]!='=':
                i+=1;continue
            i+=2;operation='='
            if i<len(tokens) and tokens[i]=='-':raise ValueError('Unsupported template list subtraction: '+key)
            if i<len(tokens) and tokens[i]=='+':operation=tokens[i];i+=1
            if i>=len(tokens) or tokens[i]!='[':raise ValueError('Nonliteral controller/template script list: '+key)
            items,i=_items(tokens,i)
            if operation=='=':result['declarations' if field=='objvars' else 'scripts']={} if field=='objvars' else []
            if field=='scripts':
                values=[]
                for item in items:
                    if len(item)!=1 or not item[0].startswith('"'):raise ValueError('Nonliteral template script: '+key)
                    values.append(json.loads(item[0]))
                result['scripts']=list(dict.fromkeys(result['scripts']+values))
            else:
                seen=set()
                for item in items:
                    if not item or not item[0].startswith('"'):raise ValueError('Nonliteral template objvar key: '+key)
                    name=json.loads(item[0])
                    if name not in FIELDS:continue
                    if name in seen:raise ValueError('Duplicate controller objvar: '+key)
                    seen.add(name)
                    if len(item)!=3 or item[1]!='=':raise ValueError('Nonliteral controller objvar: '+key)
                    value=item[2]
                    if value.startswith('"'):value=json.loads(value)
                    elif re.fullmatch(r'-?[0-9]+',value):value=str(int(value))
                    else:raise ValueError('Nonliteral controller value: '+key)
                    result['declarations'][name]=value
        self.cache[key]=copy.deepcopy(result)
        return result
