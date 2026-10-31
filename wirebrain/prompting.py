"""Versioned package prompts with strict, single-pass variable substitution."""
from functools import lru_cache
from importlib.resources import files
import json
from pathlib import PurePosixPath
from string import Template


def _resource(path):
    if not isinstance(path,str) or '\\' in path:
        raise ValueError('Invalid prompt resource path')
    parts=PurePosixPath(path)
    if parts.is_absolute() or '..' in parts.parts or not parts.parts:
        raise ValueError('Invalid prompt resource path')
    return files('wirebrain').joinpath('prompts',*parts.parts)


@lru_cache(maxsize=1)
def _catalog():
    data=json.loads(_resource('catalog.json').read_text(encoding='utf-8'))
    if data.get('schema_version')!=1 or not isinstance(data.get('prompts'),dict):
        raise ValueError('Unsupported prompt catalog')
    return data['prompts']


def prompt_info(name):
    if not isinstance(name,str) or name not in _catalog():
        raise ValueError('Unknown Wirebrain prompt: '+str(name))
    return json.loads(json.dumps(_catalog()[name]))


@lru_cache(maxsize=64)
def _template(name):
    info=prompt_info(name)
    text=_resource(info['file']).read_text(encoding='utf-8').rstrip('\n')
    template=Template(text)
    if not text.strip() or not template.is_valid() or set(template.get_identifiers())!=set(info['variables']):
        raise ValueError('Prompt variables do not match the catalog: '+name)
    return template


def render_prompt(name, **values):
    """Insert data once; never evaluate expressions, files, or nested templates."""
    info=prompt_info(name)
    if set(values)!=set(info['variables']):
        raise ValueError('Expected prompt variables for '+name+': '+', '.join(info['variables']))
    if any(not isinstance(value,str) for value in values.values()):
        raise ValueError('Prompt variable values must be strings')
    return _template(name).substitute(values)


def load_schema(name):
    info=prompt_info(name)
    if not info.get('schema'):
        raise ValueError('This prompt has no structured-output schema: '+name)
    schema=json.loads(_resource(info['schema']).read_text(encoding='utf-8'))
    if not isinstance(schema,dict) or schema.get('type')!='object':
        raise ValueError('Invalid structured-output schema: '+name)
    return schema
