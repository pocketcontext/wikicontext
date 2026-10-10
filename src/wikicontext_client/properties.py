"""Revision property shapes shared by lint and deterministic export."""
import json
import math
import re
from . import cli as wc

RELATIONSHIPS = frozenset(('deployment_profiles', 'applications', 'resources', 'credentials',
                           'consumers', 'replaces', 'replaced_by', 'members', 'accountable_owners', 'backup_owners'))
TARGET_CATALOGS = {'members': 'person', 'accountable_owners': 'group', 'backup_owners': 'group'}
RESERVED = frozenset(('wikicontext_page', 'wikicontext_revision', 'id', 'page', 'page_id',
    'revision', 'revision_id', 'publication', 'publication_id', 'kind', 'title', 'summary',
    'body', 'archived', 'run', 'base_revision', 'created', 'updated', 'created_by',
    'updated_by', 'properties', 'property_evidence', 'constructor', 'prototype', '__proto__'))


def decode(value):
    # PocketBase's JSON fields on revisions predating the migration may be null.
    return json.loads(value) if isinstance(value, str) else value


def read(revision):
    try:
        properties = decode(revision.get('properties'))
        evidence = decode(revision.get('property_evidence'))
        properties = {} if properties is None else properties
        evidence = {} if evidence is None else evidence
        if not isinstance(properties, dict) or len(properties) > 64 or not isinstance(evidence, dict):
            raise ValueError()
        for key, value in properties.items():
            if not re.fullmatch('[a-z][a-z0-9_]{0,63}', key) or key in RESERVED:
                raise ValueError()
            valid = (value is None or type(value) is bool
                     or (isinstance(value, str) and len(value) <= 2048)
                     or (type(value) in (int, float) and math.isfinite(value) and abs(value) <= 9007199254740991)
                     or (isinstance(value, list) and len(value) <= 100
                         and all(isinstance(item, str) and len(item) <= 2048 for item in value)
                         and len(set(value)) == len(value)))
            if not valid:
                raise ValueError()
            if key in RELATIONSHIPS and (not isinstance(value, list) or
                    any(not re.fullmatch('[a-z0-9]{15}', item) for item in value)):
                raise ValueError()
            if key == 'catalog_type' and value not in ('resource', 'credential', 'deployment', 'person', 'group'):
                raise ValueError()
        if 'members' in properties and properties.get('catalog_type') != 'group':
            raise ValueError()
        for key, markers in evidence.items():
            if (key not in properties or not isinstance(markers, list) or len(markers) > 32
                    or any(not isinstance(marker, str) or not re.fullmatch('[1-9][0-9]{0,5}', marker) for marker in markers)
                    or len(set(markers)) != len(markers)):
                raise ValueError()
        return properties, evidence
    except (ValueError, TypeError, OverflowError):
        raise wc.Fail(1, 'Invalid published revision properties') from None
