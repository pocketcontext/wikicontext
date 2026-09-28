"""Queries against committed knowledge, never against generated Markdown."""
import re
import wc


def rows(cfg, sql):
    result = wc.must(cfg, 'POST', '/api/context/query', {'sql': sql})
    if result.get('truncated'):
        raise wc.Fail(1, 'Query was truncated; narrow the selection before continuing')
    return [dict(zip(result['columns'], row)) for row in result['rows']]


BATCH_SIZE = 100
ID = re.compile(r'[a-z0-9]{15}')


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def batches(cfg, statement):
    """Fetch immutable rows by key; retry an oversized batch without advancing."""
    after, limit = '', BATCH_SIZE
    while True:
        try:
            batch = rows(cfg, statement(after, limit))
        except wc.Fail as error:
            if limit > 1 and ('truncated' in str(error) or
                              'HTTP 413 from POST /api/context/query' in str(error)):
                limit = max(1, limit // 2)
                continue
            raise
        if not batch:
            return
        keys = [row['id'] for row in batch]
        if any(not isinstance(key, str) or not ID.fullmatch(key) for key in keys):
            raise wc.Fail(1, 'Invalid SQL pagination ID')
        if keys != sorted(set(keys)) or keys[0] <= after:
            raise wc.Fail(1, 'Invalid SQL pagination')
        yield from batch
        after = keys[-1]


def manifest_join(publication):
    # Publication IDs come from the server but are still validated before SQL use.
    if not isinstance(publication['id'], str) or not ID.fullmatch(publication['id']):
        raise wc.Fail(1, 'Invalid publication ID')
    return ("FROM publications pub JOIN json_each(pub.manifest) m "
            "LEFT JOIN pages p ON p.id=m.key "
            "LEFT JOIN page_revisions r ON r.id=m.value AND r.page=p.id ")


def publication_where(publication):
    return f"pub.id={literal(publication['id'])}"


def published(cfg):
    # Pin the identity only: the manifest may exceed the SQL response byte limit.
    result = rows(cfg, "SELECT id, sequence, CASE WHEN json_valid(manifest) "
                  "THEN json_type(manifest) ELSE 'invalid' END AS manifest_type "
                  "FROM publications ORDER BY sequence DESC LIMIT 1")
    if not result:
        return None, []
    publication = result[0]
    if publication.pop('manifest_type') != 'object':
        raise wc.Fail(1, 'Invalid publication manifest')
    join, where = manifest_join(publication), publication_where(publication)
    # Validate every entry, including archived pages, before discarding any rows.
    # Exact page/revision pairing and duplicate-key checks avoid silent inner-join loss.
    validation = rows(cfg, "SELECT count(*) AS total, count(DISTINCT m.key) AS unique_keys, "
        "coalesce(sum(CASE WHEN length(m.key)!=15 OR m.key GLOB '*[^a-z0-9]*' "
        "OR m.type!='text' OR length(m.value)!=15 OR m.value GLOB '*[^a-z0-9]*' "
        "OR p.id IS NULL OR r.id IS NULL THEN 1 ELSE 0 END),0) AS invalid, "
        "coalesce(sum(CASE WHEN r.archived=0 THEN 1 ELSE 0 END),0) AS active "
        + join + 'WHERE ' + where)[0]
    if validation['invalid'] or validation['total'] != validation['unique_keys']:
        raise wc.Fail(1, 'Invalid or incomplete publication manifest')
    pages = list(batches(cfg, lambda after, limit:
        "SELECT r.*, p.slug, p.kind " + join + "WHERE " + where +
        f" AND r.archived=0 AND r.id>{literal(after)} ORDER BY r.id LIMIT {limit}"))
    if len(pages) != validation['active']:
        raise wc.Fail(1, 'Incomplete publication')
    return publication, pages


def relationships(cfg, publication, table, column):
    # Callers supply only the two fixed table/column pairs below. Draft and historical
    # relationships cannot enter the result because their revision must match manifest.
    join, where = manifest_join(publication), publication_where(publication)
    return batches(cfg, lambda after, limit:
        f"SELECT rel.id, rel.page_revision, rel.{column} " + join +
        f"JOIN {table} rel ON rel.page_revision=r.id WHERE " + where +
        f" AND r.archived=0 AND rel.id>{literal(after)} ORDER BY rel.id LIMIT {limit}")


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
    links_by_revision, cited = {}, set()
    if publication:
        for link in relationships(cfg, publication, 'page_links', 'target'):
            links_by_revision.setdefault(link['page_revision'], []).append(link)
        for citation in relationships(cfg, publication, 'citations', 'marker'):
            cited.add(citation['page_revision'])
    for page in pages:
        links = links_by_revision.get(page['id'], [])
        for link in links:
            if link['target'] not in incoming:
                findings.append({'page': page['slug'], 'kind': 'broken-link', 'target': link['target']})
            else:
                incoming[link['target']] += 1
        if '[needs verification]' in page['body']:
            findings.append({'page': page['slug'], 'kind': 'needs-verification'})
        if page['id'] not in cited:
            findings.append({'page': page['slug'], 'kind': 'no-citations'})
    for page in pages:
        if not incoming[page['page']]:
            findings.append({'page': page['slug'], 'kind': 'orphan'})
    return {'publication': publication['id'] if publication else None, 'findings': findings,
            'semantic_review': 'Contradictions, claim support and outdated evidence require agent review of source passages.'}
