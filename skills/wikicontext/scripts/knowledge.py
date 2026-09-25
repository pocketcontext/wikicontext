"""Queries against committed knowledge, never against generated Markdown."""
import json
import re
import wc


def rows(cfg, sql):
    result = wc.must(cfg, 'POST', '/api/context/query', {'sql': sql})
    if result.get('truncated'):
        raise wc.Fail(1, 'Query was truncated; narrow the selection before continuing')
    return [dict(zip(result['columns'], row)) for row in result['rows']]


def published(cfg):
    result = rows(cfg, 'SELECT id, sequence, manifest FROM publications ORDER BY sequence DESC LIMIT 1')
    if not result:
        return None, []
    publication = result[0]
    manifest = publication['manifest']
    if isinstance(manifest, str):
        manifest = json.loads(manifest)
    pages = []
    for page_id, revision_id in manifest.items():
        if not re.fullmatch('[a-z0-9]{15}', page_id) or not re.fullmatch('[a-z0-9]{15}', revision_id):
            raise wc.Fail(1, 'Invalid publication manifest')
        result = rows(cfg, "SELECT r.*, p.slug, p.kind FROM page_revisions r JOIN pages p ON p.id=r.page "
                      f"WHERE r.id='{revision_id}' AND p.id='{page_id}'")
        if len(result) != 1:
            raise wc.Fail(1, 'Incomplete publication')
        if not result[0]['archived']:
            pages.append(result[0])
    return publication, pages


def search(cfg, term):
    publication, pages = published(cfg)
    words = term.casefold().split()
    matches = []
    for page in pages:
        content = '\n'.join(str(page[key]) for key in ('slug', 'title', 'summary', 'body')).casefold()
        if all(word in content for word in words):
            matches.append({key: page[key] for key in ('id', 'page', 'slug', 'title', 'summary')})
    return {'publication': publication['id'] if publication else None, 'pages': sorted(matches, key=lambda p:p['slug'])}


def lint(cfg):
    publication, pages = published(cfg)
    incoming = {page['page']: 0 for page in pages}
    findings = []
    for page in pages:
        links = rows(cfg, f"SELECT target FROM page_links WHERE page_revision='{page['id']}' ORDER BY id")
        citations = rows(cfg, f"SELECT marker FROM citations WHERE page_revision='{page['id']}' ORDER BY id")
        for link in links:
            if link['target'] not in incoming:
                findings.append({'page': page['slug'], 'kind': 'broken-link', 'target': link['target']})
            else:
                incoming[link['target']] += 1
        if '[needs verification]' in page['body']:
            findings.append({'page': page['slug'], 'kind': 'needs-verification'})
        if not citations:
            findings.append({'page': page['slug'], 'kind': 'no-citations'})
    for page in pages:
        if not incoming[page['page']]:
            findings.append({'page': page['slug'], 'kind': 'orphan'})
    return {'publication': publication['id'] if publication else None, 'findings': findings,
            'semantic_review': 'Contradictions, claim support and outdated evidence require agent review of source passages.'}
