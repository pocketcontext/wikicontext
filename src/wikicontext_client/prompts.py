"""Publication-pinned reusable prompt documents; never execute prompt content."""
import re
from . import cli as wc
from . import exporter as exp
from . import properties
from . import repository_files as rf

METADATA = ('purpose', 'target_agents', 'required_skills', 'inputs', 'approval_boundaries', 'last_validated_at')
SLUG = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')


def pinned(cfg, sequence=None):
    if sequence is not None and (type(sequence) is not int or sequence < 1):
        raise wc.Fail(1, 'A positive publication sequence is required')
    space = wc.space_id(cfg)
    where = f'space = {exp.literal(space)}' + ('' if sequence is None else f' AND sequence = {sequence}')
    pubs = exp.query(cfg, f'SELECT id,sequence,manifest FROM publications WHERE {where} ORDER BY sequence DESC LIMIT 1')
    if len(pubs) != 1:
        raise wc.Fail(1, 'No matching publication exists')
    manifest = exp.decoded(pubs[0]['manifest'])
    if not isinstance(manifest, dict):
        raise wc.Fail(1, 'Invalid publication manifest')
    return space, pubs[0], manifest


def prompt(revision, page):
    p, _ = properties.read(revision)
    if (revision['page'] != page or revision['archived'] or p.get('catalog_type') != 'repository_document'
            or p.get('document_type') != 'prompt'):
        raise wc.Fail(1, 'Not a published prompt in selected publication')
    return p


def list_prompts(cfg, sequence=None, query=None):
    space, pub, manifest = pinned(cfg, sequence)
    rows = exp.query(cfg, 'SELECT g.id AS page,g.slug,r.id,r.page AS revision_page,r.title,r.summary,r.archived,r.properties,r.property_evidence '
        'FROM publications p JOIN json_each(p.manifest) e JOIN pages g ON g.id = e.key AND g.space = p.space JOIN page_revisions r ON r.id = e.value '
        f"WHERE p.id = {exp.literal(pub['id'])} AND NOT r.archived AND json_extract(r.properties, '$.catalog_type') = 'repository_document' "
        "AND json_extract(r.properties, '$.document_type') = 'prompt' ORDER BY g.slug")
    tokens = (query or '').lower().split()
    found = []
    for row in rows:
        if manifest.get(row['page']) != row['id'] or not SLUG.fullmatch(row['slug']):
            raise wc.Fail(1, 'Invalid published page identity')
        p = prompt(dict(row, page=row['revision_page']), row['page'])
        text = ' '.join(str(v or '') for v in (row['slug'], row['title'], row['summary'], p.get('purpose'))).lower()
        if all(token in text for token in tokens):
            found.append(dict({'page': row['page'], 'slug': row['slug'], 'revision': row['id'], 'title': row['title'], 'summary': row['summary']},
                              **{k: p.get(k) for k in METADATA}, output_mode=p['output_mode']))
    return {'space': space, 'publication': pub['id'], 'sequence': pub['sequence'], 'prompts': sorted(found, key=lambda v: v['slug'])}


def render_prompt(cfg, page, sequence):
    if type(sequence) is not int or sequence < 1:
        raise wc.Fail(1, 'A positive publication sequence is required')
    if not isinstance(page, str) or not SLUG.fullmatch(page):
        raise wc.Fail(1, 'Prompt must be a page ID or slug')
    space, pub, manifest = pinned(cfg, sequence)
    pages = exp.query(cfg, f'SELECT id,slug FROM pages WHERE space = {exp.literal(space)} AND (id = {exp.literal(page)} OR slug = {exp.literal(page)}) LIMIT 2')
    if len(pages) != 1:
        raise wc.Fail(1, 'Prompt page not found or ambiguous in selected space')
    page_id, slug = pages[0]['id'], pages[0]['slug']
    if page_id not in manifest:
        raise wc.Fail(1, 'Prompt page absent from selected publication')
    revision = exp.one(cfg, 'page_revisions', 'id,page,body,archived,properties,property_evidence', manifest[page_id])
    p = prompt(revision, page_id)
    receipt = {'space': space, 'publication': pub['id'], 'sequence': sequence, 'page': page_id, 'slug': slug, 'revision': revision['id']}
    if p['output_mode'] == 'exact_copy':
        source = exp.one(cfg, 'sources', 'id,original,sha256', p['source_id'])
        content = exp.download(cfg, source)
        try:
            content.decode('utf-8')
        except UnicodeDecodeError:
            raise wc.Fail(1, 'Prompt original is not valid UTF-8 text') from None
        receipt['source'] = source['id']
    else:
        content = rf.portable(revision['body'])
    return content, dict(receipt, output_mode=p['output_mode'], rendered_sha256=exp.digest(content), **{k: p.get(k) for k in METADATA})


def export(cfg, page, output, sequence):
    content, receipt = render_prompt(cfg, page, sequence)
    rf.write_new(output, content)
    return dict(receipt, output=str(output))
