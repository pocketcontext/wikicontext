#!/usr/bin/env python3
"""Actual container S3 uploads and Litestream fresh-volume recovery, synthetic only."""
import argparse
import importlib.util, pathlib, tempfile, secrets, time
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--image', required=True)
parser.add_argument('--minio-image', required=True, help='Local MinIO fixture image including mc')
args = parser.parse_args()
root=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('smoke',root/'docker/smoke.py');s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
run_id=secrets.token_hex(4);network='wiki-s3-'+run_id;minio=network+'-minio'
failed=True
try:
 s.docker('network','create',network);s.networks.append(network)
 access='synthetic'+run_id;secret=s.secret(secrets.token_hex(24));mc={'MC_HOST_test':s.secret(f'http://{access}:{secret}@127.0.0.1:9000')}
 s.containers.append(minio)
 s.docker('run','-d','--name',minio,'--network',network,'-e','MINIO_ROOT_USER','-e','MINIO_ROOT_PASSWORD',args.minio_image,'server','/data',env={'MINIO_ROOT_USER':access,'MINIO_ROOT_PASSWORD':secret})
 for _ in range(30):
  status,_=s.docker('exec','-e','MC_HOST_test',minio,'mc','mb','--ignore-existing','test/files','test/replica',env=mc,ok=False)
  if status==0:break
  time.sleep(1)
 else:raise RuntimeError('MinIO fixture failed')
 env=s.once_env({'WIKICONTEXT_S3_BUCKET':'files','WIKICONTEXT_S3_ENDPOINT':f'http://{minio}:9000','WIKICONTEXT_S3_REGION':'us-east-1','WIKICONTEXT_S3_ACCESS_KEY_ID':access,'WIKICONTEXT_S3_SECRET_ACCESS_KEY':secret,'LITESTREAM_BUCKET':'replica','LITESTREAM_PATH':'test/data','LITESTREAM_ENDPOINT':f'http://{minio}:9000','LITESTREAM_REGION':'us-east-1','LITESTREAM_ACCESS_KEY_ID':access,'LITESTREAM_SECRET_ACCESS_KEY':secret,'LITESTREAM_SYNC_INTERVAL':'1h'})
 with tempfile.TemporaryDirectory(prefix='wiki-image-s3-') as td:
  tmp=pathlib.Path(td);first=network+'-a';second=network+'-b'
  s.run_app(args.image,first,first,env,network);base=s.wait_up(first)
  admin=s.superuser_token(base,env['WIKICONTEXT_SUPERUSER_EMAIL'],env['WIKICONTEXT_SUPERUSER_PASSWORD'])
  password=s.secret(secrets.token_urlsafe(24));user=s.provision_user(base,admin,'restore@example.test',password)
  client=s.Client(base,'restore@example.test',password,tmp/'home-a')
  doc,meta=s.write_record(client,user);s.check_records(client,doc,meta)
  s.check(s.docker('exec',first,'sh','-c','find /storage/pb_data/storage -type f 2>/dev/null || true')[1].strip()=='','no local originals')
  s.stop(first)
  s.check('uploaded verified database and originals' not in s.logs(first),'no complete archive supervisor used')
  s.docker('rm',first);s.docker('volume','rm',first);s.volumes.remove(first)
  s.run_app(args.image,second,second,env,network);base=s.wait_up(second)
  client=s.Client(base,'restore@example.test',password,tmp/'home-b');s.check_records(client,doc,meta)
  s.check('restored verified database and originals' not in s.logs(second),'no old archive restore')
  s.check('database present after the restore step' in s.logs(second),'Litestream restored DB')
  s.stop(second);s.check_logs(second)
  s.check('full-backups/' not in s.docker('exec','-e','MC_HOST_test',minio,'mc','ls','--recursive','test/replica',env=mc)[1],'no complete archives emitted')
 failed=False
 print('PASS actual image entrypoint S3 upload + Litestream final sync + destroy source volume + fresh-volume restore')
finally:s.report_and_clean(failed)
