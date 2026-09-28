#!/usr/bin/env python3
"""Opt-in synthetic near-budget benchmark; ordinary HTTP writes, isolated data."""
import argparse
import concurrent.futures
import contextlib
import json
import importlib.util
import sqlite3
from pathlib import Path
import statistics
import tempfile
import time

from integration import ROOT, credentials
from search_integration import Fixture, running


def identifier(prefix,n):return prefix+f'{n:014d}'


def storage_stats(data):
    """Physical allocation only, from a verified complete synthetic backup."""
    spec=importlib.util.spec_from_file_location('benchmark_backup',ROOT/'docker/backup.py')
    backup=importlib.util.module_from_spec(spec);spec.loader.exec_module(backup)
    with tempfile.TemporaryDirectory(prefix='wikicontext-search-size-') as directory:
        dest=Path(directory)/'snapshot';backup.snapshot(data,dest)
        with sqlite3.connect(f"file:{dest/'data.db'}?mode=ro",uri=True) as db:
            fts=db.execute("SELECT coalesce(sum(pgsize),0) FROM dbstat WHERE name GLOB 'published_pages_fts*'").fetchone()[0]
            state=db.execute("SELECT coalesce(sum(pgsize),0) FROM dbstat WHERE name='search_state' OR name GLOB 'sqlite_autoindex_search_state_*'").fetchone()[0]
        return {'snapshot_bytes':(dest/'data.db').stat().st_size,'fts_allocated_bytes':fts,'state_allocated_bytes':state}


def sql_ranked(f,pub,query):
    """One HTTP query with weighted literal substring counts and bounded excerpts."""
    escaped=query.replace("'","''")
    score='+'.join(f"{weight}*(length(lower(r.{field}))-length(replace(lower(r.{field}),'{escaped}','')))/{len(query)}" for field,weight in [('title',8),('summary',3),('body',1)])
    return f.query(f"""WITH scored AS (SELECT r.id,({score}) AS score,substr(r.body,1,240) AS excerpt
        FROM publications pub JOIN json_each(pub.manifest) m
        JOIN page_revisions r ON r.id=m.value AND r.page=m.key
        WHERE pub.id='{pub['id']}' AND r.archived=false)
        SELECT id,score,excerpt FROM scored WHERE score>0 ORDER BY score DESC,id LIMIT 20""")


def lexical(f,pub,query):
    # Mirror client lexical ranking over bounded manifest-aware batches.
    scores=[];last=''
    while True:
        rows=f.query(f"SELECT r.id,r.title,r.summary,r.body FROM publications pub JOIN json_each(pub.manifest) m JOIN page_revisions r ON r.id=m.value AND r.page=m.key WHERE pub.id='{pub['id']}' AND r.archived=false AND r.id>'{last}' ORDER BY r.id LIMIT 200")
        for r in rows:
            score=sum(weight*r[field].lower().count(query) for field,weight in [('title',8),('summary',3),('body',1)])
            if score:scores.append((score,r['id']))
        if len(rows)<200:break
        last=rows[-1]['id']
    return [rid for _,rid in sorted(scores,key=lambda x:(-x[0],x[1]))[:20]]

def measure_existing(binary,data,repeats):
    if not (data.parent/'.synthetic-search-benchmark').is_file():
        raise ValueError('Only a marked synthetic benchmark fixture may be remeasured')
    with tempfile.TemporaryDirectory(prefix='wikicontext-search-measure-') as directory:
        with running(binary,Path(directory)/'app',data=data) as request:
            token=request('POST','/api/collections/users/auth-with-password',{'identity':'agent@example.com','password':'SyntheticUserPassword123!'})['token']
            f=Fixture(request,token);pub=f.query('SELECT id,sequence FROM publications ORDER BY sequence DESC LIMIT 1')[0]
            counts=f.query("""SELECT (SELECT count(*) FROM pages) AS pages,
              (SELECT count(DISTINCT r.id) FROM publications p,json_each(p.manifest) m JOIN page_revisions r ON r.id=m.value AND r.page=m.key WHERE r.archived=false) AS indexed_revisions,
              (SELECT count(*) FROM page_revisions r JOIN ingestion_runs run ON run.id=r.run WHERE run.status='staging') AS drafts""")[0]
            results={}
            for query in ['topic3','evidence','nonexistentterm']:
                timings={'lexical_ms':[],'ranked_sql_ms':[],'fts_ms':[]}
                for _ in range(repeats):
                    for key,fn in [('lexical_ms',lambda:lexical(f,pub,query)),('ranked_sql_ms',lambda:sql_ranked(f,pub,query)),('fts_ms',lambda:f.search(pub,query,limit=20))]:
                        start=time.perf_counter();fn();timings[key].append((time.perf_counter()-start)*1000)
                results[query]={key:round(statistics.median(values),2) for key,values in timings.items()}
            precision={}
            for topic in range(20):
                query='topic'+str(topic)
                hits=f.search(pub,query,limit=20)['hits'];baseline=sql_ranked(f,pub,query)
                precision[query]={'fts':sum(int(h['id'][1:])%20==topic for h in hits)/len(hits),
                    'ranked_sql':sum(int(h['id'][1:])%20==topic for h in baseline)/len(baseline)}
            def read(_):
                start=time.perf_counter();f.search(pub,'evidence',limit=20);return (time.perf_counter()-start)*1000
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:times=list(pool.map(read,range(12)))
            return dict(counts,publication_sequence=pub['sequence'],repeats=repeats,queries=results,
                precision_at_20=precision,concurrent_4_reader_median_ms=round(statistics.median(times),2),
                concurrent_4_reader_max_ms=round(max(times),2),storage=storage_stats(data))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--binary',required=True)
    parser.add_argument('--pages',type=int,default=10000);parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--measure-existing',type=Path,help='Remeasure a retained synthetic pb_data directory without adding knowledge records');parser.add_argument('--output',type=Path);parser.add_argument('--fixture',type=Path,help='Retain synthetic fixture outside the repository for follow-up measurements');args=parser.parse_args()
    if args.measure_existing:
        result=measure_existing(args.binary,args.measure_existing,args.repeats)
        rendered=json.dumps(result,indent=2)
        if args.output:args.output.write_text(rendered+'\n')
        print(rendered);return
    assert 100<=args.pages<=10000
    history=args.pages//5
    if args.fixture and args.fixture.exists() and any(args.fixture.iterdir()):
        raise ValueError('Choose a new empty fixture directory')
    manager=contextlib.nullcontext(args.fixture) if args.fixture else tempfile.TemporaryDirectory(prefix='wikicontext-search-benchmark-')
    with manager as tmp:
        work=Path(tmp)/'app';work.mkdir(parents=True,exist_ok=True)
        (work/'.synthetic-search-benchmark').write_text('Synthetic HTTP-created benchmark fixture.\n')
        with running(args.binary,work,legacy=True) as request:
            admin,user,token=credentials(request);f=Fixture(request,token)
            def batch(items):
                for start in range(0,len(items),20):
                    request('POST','/api/batch',{'requests':items[start:start+20]},token)
            def post(table,body):return {'method':'POST','url':'/api/collections/'+table+'/records','body':body}
            initial=f.run('initial');items=[]
            for i in range(args.pages):
                topic='topic'+str(i%20)
                body=(f'{topic} deployment evidence and recovery procedures. '+('Synthetic paragraph about immutable publications and operations. '*(4+i%20))+' [needs verification]')
                items.extend([post('pages',dict(id=identifier('p',i),slug='synthetic-page-'+str(i),kind='concept')),
                    post('page_revisions',dict(id=identifier('r',i),run=initial['id'],page=identifier('p',i),title=topic+' guide '+str(i),summary='Synthetic '+topic+' summary',body=body))])
            started=time.perf_counter();batch(items);ingest=time.perf_counter()-started
            print(f'Created {args.pages} synthetic pages in {ingest:.1f}s',flush=True)
            started=time.perf_counter();pub=f.publish(initial);initial_publish=time.perf_counter()-started
            historical=f.run('history');items=[]
            for i in range(history):
                topic='topic'+str(i%20)
                items.append(post('page_revisions',dict(id=identifier('h',i),run=historical['id'],page=identifier('p',i),base_revision=identifier('r',i),title=topic+' updated guide '+str(i),summary='Synthetic '+topic+' summary',body=(topic+' current evidence '+('Historical variant operations text. '*(10+i%30))+' [needs verification]'))))
            batch(items);started=time.perf_counter();pub=f.publish(historical);legacy_publish=time.perf_counter()-started
            # A large draft corpus must never become searchable.
            drafts=f.run('drafts');batch([post('page_revisions',dict(id=identifier('d',i),run=drafts['id'],page=identifier('p',i),base_revision=identifier('h',i),title='draftsecret',summary='Unpublished evidence',body='draftsecret [needs verification]')) for i in range(history)])
        before_storage=storage_stats(work/'pb_data');before=before_storage['snapshot_bytes']
        started=time.perf_counter()
        with running(args.binary,work) as request:
            migration_startup=time.perf_counter()-started
            print(f'Migrated {args.pages+history} published revisions in {migration_startup:.1f}s including startup',flush=True)
            admin=request('POST','/api/collections/_superusers/auth-with-password',{'identity':'admin@example.com','password':'SyntheticAdminPassword123!'})['token']
            f=Fixture(request,token)
            migrated_storage=storage_stats(work/'pb_data');migrated_size=migrated_storage['snapshot_bytes']
            def ranked_sql(query):
                return sql_ranked(f,pub,query)
            results={}
            for query in ['topic3','evidence','nonexistentterm']:
                lexical_times=[];fts_times=[];sql_times=[]
                for _ in range(args.repeats):
                    started=time.perf_counter();baseline=lexical(f,pub,query);lexical_times.append(time.perf_counter()-started)
                    started=time.perf_counter();sql_hits=ranked_sql(query);sql_times.append(time.perf_counter()-started)
                    started=time.perf_counter();hits=f.search(pub,query,limit=20)['hits'];fts_times.append(time.perf_counter()-started)
                results[query]={'lexical_ms':round(statistics.median(lexical_times)*1000,2),'fts_ms':round(statistics.median(fts_times)*1000,2),'ranked_sql_ms':round(statistics.median(sql_times)*1000,2),'hits':len(hits)}
                if query=='topic3':
                    assert all(int(h['id'][1:])%20==3 for h in hits)
                    assert all(int(rid[1:])%20==3 for rid in baseline)
                    assert all(int(row['id'][1:])%20==3 for row in sql_hits)
            assert not f.search(pub,'draftsecret')['hits']
            def reader(_):
                start=time.perf_counter();f.search(pub,'evidence',limit=20);return (time.perf_counter()-start)*1000
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:concurrent_times=list(pool.map(reader,range(12)))
            # Rebuild and new publication must invalidate an already paged historical search.
            old=f.search(pub,'evidence',limit=20)
            started=time.perf_counter();request('POST','/api/wiki/search/rebuild',{},admin);rebuild=time.perf_counter()-started
            request('POST','/api/context/search',dict(index='pages',scope=pub['id'],query='evidence',limit=20,offset=20,expectedGeneration=old['generation']),token,409)
            # Publish an equivalent history batch against the indexed database.
            changes=f.run('indexed-history');items=[]
            for i in range(history):
                topic='topic'+str(i%20)
                items.append(post('page_revisions',dict(id=identifier('n',i),run=changes['id'],page=identifier('p',i),base_revision=identifier('h',i),title=topic+' next guide '+str(i),summary='Synthetic '+topic+' summary',body=(topic+' current evidence '+('Historical variant operations text. '*(10+i%30))+' [needs verification]'))))
            batch(items);started=time.perf_counter();f.publish(changes);indexed_publish=time.perf_counter()-started
        after_storage=storage_stats(work/'pb_data');after=after_storage['snapshot_bytes']
    result=dict(pages=args.pages,indexed_revisions_before_measurement=args.pages+history,drafts=history,repeats=args.repeats,initial_ingest_seconds=round(ingest,3),initial_publish_seconds=round(initial_publish,3),history_batch_size=history,legacy_publish_seconds=round(legacy_publish,3),indexed_publish_seconds=round(indexed_publish,3),migration_startup_seconds=round(migration_startup,3),rebuild_seconds=round(rebuild,3),db_before_bytes=before,db_migrated_bytes=migrated_size,db_after_bytes=after,migrated_storage=migrated_storage,final_storage=after_storage,concurrent_4_reader_median_ms=round(statistics.median(concurrent_times),2),concurrent_4_reader_max_ms=round(max(concurrent_times),2),queries=results)
    rendered=json.dumps(result,indent=2)
    if args.output:args.output.write_text(rendered+'\n')
    print(rendered)


if __name__=='__main__':main()
