#!/usr/bin/env python3
"""Synthetic HTTP tests for publication-scoped FTS maintenance and recovery."""
import argparse
import contextlib
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from integration import ROOT, credentials


@contextlib.contextmanager
def running(binary, work, *, legacy=False, data=None):
    """Start an isolated copied app; legacy mode represents pre-index adoption."""
    work=Path(work);work.mkdir(exist_ok=True,parents=True)
    hooks=work/'pb_hooks'; migrations=work/'pb_migrations'
    shutil.copytree(ROOT/'pb_hooks',hooks,dirs_exist_ok=True)
    shutil.copytree(ROOT/'pb_migrations',migrations,dirs_exist_ok=True)
    cfg=json.loads((ROOT/'pocketcontext.json').read_text())
    if legacy:
        cfg.pop('search',None);cfg['tables'].pop('search_state',None)
        (migrations/'1790500000_search.js').unlink()
        (hooks/'search.pb.js').unlink()
        p=hooks/'integrity.js';p.write_text(p.read_text().replace(" require(`${__hooks}/search.js`).publish(app,revisions);",''))
    (work/'pocketcontext.json').write_text(json.dumps(cfg))
    (hooks/'search_failure_fixture.pb.js').write_text('''
onRecordCreateExecute(e=>{
 if(e.record.getString('record')==='pubfailure00001'&&e.record.getString('action')==='update')throw new Error('Synthetic audit failure');
 e.next();
},'audit_log');
onRecordUpdateExecute(e=>{
 if(e.app.store().get('syntheticSearchFailure'))throw new Error('Synthetic generation write failure');
 e.next();
},'search_state');
routerAdd('GET','/api/test/search-count',e=>{
 const result=new DynamicModel({n:0,unique_ids:0});
 e.app.db().newQuery('SELECT count(*) n,count(DISTINCT record_id) unique_ids FROM published_pages_fts').one(result);
 return e.json(200,result);
},$apis.requireSuperuserAuth());
routerAdd('POST','/api/test/corrupt-manifest',e=>{
 const data=e.requestInfo().body;
 const row=e.app.findRecordById('publications',data.id);row.set('manifest',data.manifest);e.app.saveNoValidate(row);
 return e.json(200,{});
},$apis.requireSuperuserAuth());
routerAdd('POST','/api/test/search-failure',e=>{
 e.app.store().set('syntheticSearchFailure',e.requestInfo().body.fail);
 return e.json(200,{});
},$apis.requireSuperuserAuth());
''')
    data=Path(data or work/'pb_data')
    common=[str(Path(binary).resolve()),'--dir',str(data),'--migrationsDir',str(migrations),'--hooksDir',str(hooks)]
    setup=subprocess.run(common+['superuser','upsert','admin@example.com','SyntheticAdminPassword123!'],cwd=work,capture_output=True,text=True)
    assert setup.returncode==0,setup.stdout+setup.stderr
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    with (work/'server.log').open('w+') as log:
        proc=subprocess.Popen(common+['serve','--http',f'127.0.0.1:{port}'],cwd=work,stdout=log,stderr=log)
        def request(method,path,body=None,token=None,expected=200):
            headers={'Content-Type':'application/json'}
            if token:headers['Authorization']=token
            req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=None if body is None else json.dumps(body).encode(),headers=headers,method=method)
            try:
                with urllib.request.urlopen(req,timeout=60) as response:status,raw=response.status,response.read()
            except urllib.error.HTTPError as e:status,raw=e.code,e.read()
            assert status in (expected if isinstance(expected,tuple) else (expected,)),(method,path,status,raw.decode())
            return json.loads(raw) if raw else None
        request.data_dir=data
        try:
            for _ in range(150):
                try:request('GET','/api/health');break
                except (OSError,AssertionError):
                    if proc.poll() is not None:log.seek(0);raise AssertionError(log.read())
                    time.sleep(.1)
            else:raise AssertionError('startup timeout')
            yield request
        finally:proc.terminate();proc.wait(timeout=15)


class Fixture:
    def __init__(self,request,token):self.request=request;self.token=token
    def create(self,table,body):return self.request('POST','/api/collections/'+table+'/records',body,self.token)
    def query(self,sql):
        data=self.request('POST','/api/context/query',{'sql':sql},self.token)
        assert not data['truncated'];return [dict(zip(data['columns'],row)) for row in data['rows']]
    def run(self,key,**kwargs):return self.create('ingestion_runs',dict(key=key,status='staging',description='Synthetic search '+key,**kwargs))
    def page(self,slug):return self.create('pages',dict(slug=slug,kind='concept'))
    def revision(self,run,page,base='',**kwargs):
        return self.create('page_revisions',dict(dict(run=run['id'],page=page['id'],base_revision=base,title='Orchid guide',summary='Synthetic botanical research',body='Orchid evidence [needs verification].'),**kwargs))
    def publish(self,run,expected=200):
        result=self.request('PATCH','/api/collections/ingestion_runs/records/'+run['id'],{'status':'published','expected_revision':run['revision']},self.token,expected)
        if result.get('status')=='published':return self.query('SELECT id,sequence FROM publications ORDER BY sequence DESC LIMIT 1')[0]
        return result
    def search(self,pub,query='orchid',**kwargs):
        return self.request('POST','/api/context/search',dict(index='pages',scope=pub['id'],query=query,**kwargs),self.token)
    def generation(self):return self.query("SELECT generation FROM search_state WHERE id='pagesindexstate'")[0]['generation']


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--binary',required=True);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='wikicontext-search-') as tmp:
        work=Path(tmp)/'app'
        # Existing publications predate the migration; drafts and archives exist too.
        with running(args.binary,work,legacy=True) as request:
            admin,user,token=credentials(request);f=Fixture(request,token)
            p=f.page('orchid-one');q=f.page('orchid-two');first=f.run('first')
            r1=f.revision(first,p);r2=f.revision(first,q);pub1=f.publish(first)
            second=f.run('second');r3=f.revision(second,p,r1['id']);pub2=f.publish(second)
            archive=f.run('archive');r4=f.revision(archive,q,r2['id'],archived=True);pub3=f.publish(archive)
            draft=f.run('draft');r5=f.revision(draft,p,r3['id'])
        with running(args.binary,work) as request:
            admin=request('POST','/api/collections/_superusers/auth-with-password',{'identity':'admin@example.com','password':'SyntheticAdminPassword123!'})['token']
            f=Fixture(request,token)
            assert {x['id'] for x in f.search(pub1)['hits']}=={r1['id'],r2['id']}
            assert {x['id'] for x in f.search(pub2)['hits']}=={r3['id'],r2['id']}
            assert {x['id'] for x in f.search(pub3)['hits']}=={r3['id']}
            first=f.search(pub2,limit=1)
            assert first['hasMore'] and len(first['hits'])==1
            second=f.search(pub2,limit=1,offset=1,expectedGeneration=first['generation'])
            assert not second['hasMore'] and first['hits'][0]['id']!=second['hits'][0]['id']
            for identity in (token,admin):
                for method,path,body in [('POST','',{'generation':'tamper'}),('PATCH','/pagesindexstate',{'generation':'tamper'}),('DELETE','/pagesindexstate',None)]:
                    request(method,'/api/collections/search_state/records'+path,body,identity,(400,403,404))
            request('POST','/api/context/query',{'sql':'SELECT * FROM published_pages_fts'},token,400)
            request('POST','/api/context/query',{'sql':'SELECT * FROM published_pages_fts_content'},token,400)
            request('POST','/api/wiki/search/rebuild',{},token,(401,403))
            request('POST','/api/wiki/search/rebuild',{},None,(401,403))
            assert request('GET','/api/test/search-count',token=admin)=={'n':3,'unique_ids':3}
            before=f.generation()
            failed=f.run('audit-failure',id='pubfailure00001');failedrev=f.revision(failed,p,r3['id'])
            f.publish(failed,(400,500));assert f.generation()==before
            assert f.search(pub3)['hits'][0]['id']==r3['id']
            # A failed generation write rolls back rebuilt contents and preserves paging.
            request('POST','/api/test/search-failure',{'fail':True},admin)
            request('POST','/api/wiki/search/rebuild',{},admin,(400,500))
            assert f.generation()==before
            assert request('GET','/api/test/search-count',token=admin)=={'n':3,'unique_ids':3}
            assert f.search(pub2,limit=1,offset=1,expectedGeneration=first['generation'])['hits']==second['hits']
            request('POST','/api/test/search-failure',{'fail':False},admin)
            original_manifest=f.query("SELECT manifest FROM publications WHERE id='%s'"%pub3['id'])[0]['manifest']
            for corrupt in [None,[],{p['id']:'missing00000000'},{q['id']:r3['id']}, '{"'+p['id']+'":"'+r3['id']+'","'+p['id']+'":"'+r3['id']+'"}']:
                request('POST','/api/test/corrupt-manifest',dict(id=pub3['id'],manifest=corrupt),admin)
                request('POST','/api/wiki/search/rebuild',{},admin,(400,500))
                assert f.generation()==before
                assert request('GET','/api/test/search-count',token=admin)=={'n':3,'unique_ids':3}
                request('POST','/api/test/corrupt-manifest',dict(id=pub3['id'],manifest=original_manifest),admin)
            rebuilt=request('POST','/api/wiki/search/rebuild',{},admin)
            assert rebuilt['stateGeneration']!=before and f.generation()==rebuilt['stateGeneration']
            request('POST','/api/context/search',dict(index='pages',scope=pub2['id'],query='orchid',limit=1,offset=1,expectedGeneration=first['generation']),token,409)
            assert {x['id'] for x in f.search(pub2)['hits']}=={r3['id'],r2['id']}
            # New publication changes global rank generation even for historical scopes.
            old=f.search(pub1,limit=1);final=f.run('final');r6=f.revision(final,p,r3['id']);pub4=f.publish(final)
            assert f.generation()!=old['generation']
            request('POST','/api/context/search',dict(index='pages',scope=pub1['id'],query='orchid',limit=1,offset=1,expectedGeneration=old['generation']),token,409)
            expected=f.search(pub4)
            # Snapshot includes the index and generation; restore on a separate server.
            spec=importlib.util.spec_from_file_location('backup',ROOT/'docker/backup.py');backup=importlib.util.module_from_spec(spec);spec.loader.exec_module(backup)
            backup.snapshot(request.data_dir,Path(tmp)/'restored_data')
        with running(args.binary,Path(tmp)/'restore_app',data=Path(tmp)/'restored_data') as request:
            f=Fixture(request,token);restored=f.search(pub4)
            assert restored==expected,(restored,expected)
            assert {x['id'] for x in f.search(pub1)['hits']}=={r1['id'],r2['id']}
    print('PASS: scoped search, legacy backfill, draft/archive exclusion, atomic publication/rebuild, generation conflicts, protected maintenance and populated restore')


if __name__=='__main__':main()
