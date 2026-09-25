#!/usr/bin/env python3
"""Portable commands against a synthetic isolated server."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from integration import ROOT, server, credentials


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--binary',required=True);parser.add_argument('--write-schema',action='store_true');args=parser.parse_args()
    with server(args.binary) as request, tempfile.TemporaryDirectory(prefix='wikicontext-portable-') as tmp:
        admin,user,token=credentials(request)
        schema=request('GET','/api/context/schema',token=token)
        snapshot=ROOT/'skills/wikicontext/references/schema.json'
        if args.write_schema:snapshot.write_text(json.dumps(schema,indent=2)+'\n')
        assert json.loads(snapshot.read_text())==schema,'Review and regenerate SQL schema snapshot'
        skill=Path(tmp)/'portable';shutil.copytree(ROOT/'skills/wikicontext',skill)
        env={**os.environ,'HOME':tmp,'XDG_CACHE_HOME':str(Path(tmp)/'cache'),'WIKICONTEXT_URL':request.base_url,'WIKICONTEXT_USER_EMAIL':'agent@example.com','WIKICONTEXT_USER_PASSWORD':'SyntheticUserPassword123!'}
        def cli(*argv,expected=0):
            result=subprocess.run(['python3',str(skill/'scripts/wc.py'),*argv],env=env,cwd=tmp,capture_output=True,text=True)
            assert env['WIKICONTEXT_USER_PASSWORD'] not in result.stdout+result.stderr and token not in result.stdout+result.stderr
            assert result.returncode==expected,(argv,result.stdout,result.stderr)
            return json.loads(result.stdout) if result.stdout.startswith(('{','[')) else result.stdout
        cli('whoami');cli('check')
        assert cli('search','anything')['pages']==[]
        source=Path(tmp)/'source.md';source.write_text('The synthetic launch is on Tuesday.\n')
        ingested=cli('ingest',str(source));cli('ingest',str(source))
        pages=[]
        run=cli('create','ingestion_runs',json.dumps({'key':'portable','status':'staging','description':'Synthetic CLI publication'}))
        page=cli('create','pages',json.dumps({'slug':'synthetic-launch','kind':'concept'}))
        revision=cli('create','page_revisions',json.dumps({'run':run['id'],'page':page['id'],'title':'Synthetic launch','summary':'A synthetic test','body':'A launch on Tuesday [needs verification].'}))
        cli('publish',run['id'],'--expected-revision','1')
        assert cli('search','Tuesday')['pages'][0]['id']==revision['id']
        assert cli('lint')['findings']
        result=cli('export-obsidian',str(Path(tmp)/'vault'))
        assert result['sequence']==1 and (Path(tmp)/'vault/wiki/synthetic-launch.md').is_file()
        assert cli('get','page_revisions',revision['id'])['body'].startswith('A launch')
        cli('publish',run['id'],'--expected-revision','1',expected=4)
        cli('update','ingestion_runs',run['id'],'{"status":"cancelled"}',expected=2)
        cli('batch',json.dumps([{'method':'POST','url':'/api/collections/users/records','body':{}}]),expected=2)
        cache=list((Path(tmp)/'cache/wikicontext').glob('*.json'))
        assert cache and all(p.stat().st_mode & 0o077 == 0 for p in cache)
        cli('logout')
    print('PASS: copied skill, schema, ingestion, published queries, lint, export, conflicts and private cache')

if __name__=='__main__':main()
