"""Optional SSH provisioning; registration secrets remain on the Matrix host."""

import asyncio
import json
import re

from hardline.runtime import STATE, private_write, settings

REMOTE = r"""
import json,sys,os,secrets,hmac,hashlib,urllib.request,urllib.error,yaml,subprocess
from pathlib import Path
job=json.loads(sys.argv[1]);slug=job['slug']
import re
assert re.fullmatch('[a-z][a-z0-9-]{0,40}',slug)
net=json.loads(subprocess.check_output(['docker','inspect',job.get('synapse_container','matrix-synapse')]))[0]['NetworkSettings']['Networks']
ip=next(v['IPAddress'] for v in net.values() if v.get('IPAddress'));base='http://'+ip+':8008'
cfg=yaml.safe_load(open(job.get('synapse_config','/matrix/synapse/config/homeserver.yaml')))
store=Path(job.get('staging_directory','/var/lib/hardline/provisioning'));store.mkdir(mode=0o700,exist_ok=True);os.chmod(store,0o700);p=store/(slug+'.json')
def save(d):
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
 with os.fdopen(fd,'w')as f:json.dump(d,f)
def req(path,data=None,token=None):
 headers={'Content-Type':'application/json'}
 if token:headers['Authorization']='Bearer '+token
 return json.load(urllib.request.urlopen(urllib.request.Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers),timeout=30))
if p.exists():record=json.load(open(p))
else:
 record={'password':secrets.token_urlsafe(32),'registered':False};save(record)
if not record['registered']:
 nonce=req('/_synapse/admin/v1/register')['nonce'];pw=record['password'];mac=hmac.new(cfg['registration_shared_secret'].encode(),('\0'.join([nonce,slug,pw,'notadmin'])).encode(),hashlib.sha1).hexdigest()
 try:req('/_synapse/admin/v1/register',{'nonce':nonce,'username':slug,'password':pw,'admin':False,'mac':mac})
 except urllib.error.HTTPError as e:
  if e.code!=400:raise
  # Login with the privately staged password reconciles a response lost after creation.
  req('/_matrix/client/v3/login',{'type':'m.login.password','identifier':{'type':'m.id.user','user':slug},'password':pw})
 record['registered']=True;save(record)
if 'credential' not in record:
 login=req('/_matrix/client/v3/login',{'type':'m.login.password','identifier':{'type':'m.id.user','user':slug},'password':record['password'],'initial_device_display_name':'Hardline '+slug})
 record['credential']={'homeserver':job['homeserver'],'user_id':login['user_id'],'device_id':login['device_id'],'access_token':login['access_token']};save(record)
# Existing human-approved pilot room. Administrator login is ephemeral and local to this host.
admin=json.load(open(job['admin_credentials_file']))
a=req('/_matrix/client/v3/login',{'type':'m.login.password','identifier':{'type':'m.id.user','user':admin['username']},'password':admin['password'],'initial_device_display_name':'Hardline provisioning'})['access_token']
from urllib.parse import quote
try:
 for room in job['rooms']:
  try:req('/_matrix/client/v3/rooms/'+quote(room,safe='')+'/invite',{'user_id':record['credential']['user_id']},a)
  except urllib.error.HTTPError as e:
   if e.code!=403:raise
  req('/_matrix/client/v3/join/'+quote(room,safe=''),{},record['credential']['access_token'])
finally:req('/_matrix/client/v3/logout',{},a)
print(json.dumps(record['credential']))
"""


async def provision(slug):
    if not re.fullmatch("[a-z][a-z0-9-]{0,40}", slug):
        raise ValueError("Invalid slug")
    cfg = settings()
    mode = cfg.get("provisioning", {})
    if mode.get("mode") != "ssh":
        return {"status": "awaiting_credentials"}
    import shlex

    if not mode.get("admin_credentials_file"):
        raise ValueError(
            "SSH provisioning requires admin_credentials_file on the remote host"
        )
    job = {"slug": slug, "homeserver": cfg["homeserver"], "rooms": cfg["rooms"]}
    for key in [
        "admin_credentials_file",
        "staging_directory",
        "synapse_container",
        "synapse_config",
    ]:
        if key in mode:
            job[key] = mode[key]
    cmd = "sudo python3 - " + shlex.quote(json.dumps(job))
    p = await asyncio.create_subprocess_exec(
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "UserKnownHostsFile=" + mode["known_hosts"],
        mode["host"],
        cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _err = await p.communicate(REMOTE.encode())
    if p.returncode:
        raise RuntimeError("SSH provisioning failed; credential output suppressed")
    c = json.loads(out)
    private_write(STATE / "credentials" / f"{slug}.json", c)
    return {"status": "provisioned", "matrix_user": c["user_id"]}
