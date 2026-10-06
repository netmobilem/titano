import os, sqlite3, json, uuid, secrets, socket, subprocess, time, shutil
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory, render_template, abort, send_file
from io import BytesIO
import base64
from werkzeug.security import generate_password_hash, check_password_hash

BASE=os.path.dirname(os.path.abspath(__file__)); DATA=os.environ.get('DATA_DIR','/app/data')
try:
 os.makedirs(DATA, exist_ok=True)
except PermissionError:
 DATA=os.path.join(BASE,'data'); os.makedirs(DATA, exist_ok=True)
DB=os.path.join(DATA,'titan.sqlite3'); XRAY_DIR=os.path.join(DATA,'xray'); NGINX_DIR=os.path.join(DATA,'nginx'); os.makedirs(XRAY_DIR,exist_ok=True); os.makedirs(NGINX_DIR,exist_ok=True)
app=Flask(__name__, static_folder='static', template_folder='templates'); app.secret_key=os.environ.get('SECRET_KEY','change-this-in-production-'+secrets.token_hex(16)); app.config['PERMANENT_SESSION_LIFETIME']=timedelta(hours=12)

def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c
def now(): return datetime.utcnow().isoformat(timespec='seconds')+'Z'
def init():
 c=db(); c.executescript('''CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password_hash TEXT,created_at TEXT);
 CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,name TEXT,note TEXT,active INTEGER DEFAULT 1,created_at TEXT);
 CREATE TABLE IF NOT EXISTS nodes(id INTEGER PRIMARY KEY,name TEXT,domain TEXT,city TEXT,country TEXT,country_code TEXT,location TEXT,status TEXT DEFAULT 'offline',latency INTEGER DEFAULT 0,last_check TEXT,created_at TEXT);
 CREATE TABLE IF NOT EXISTS configs(id INTEGER PRIMARY KEY,user_id INTEGER,node_id INTEGER,name TEXT,protocol TEXT,transport TEXT,tls TEXT,fingerprint TEXT,alpn TEXT,path TEXT,service_name TEXT,traffic_limit INTEGER DEFAULT 0,used_traffic INTEGER DEFAULT 0,connection_limit INTEGER DEFAULT 0,active INTEGER DEFAULT 1,uuid TEXT,created_at TEXT,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(node_id) REFERENCES nodes(id) ON DELETE SET NULL);
 CREATE TABLE IF NOT EXISTS subscriptions(id INTEGER PRIMARY KEY,name TEXT,token TEXT UNIQUE,active INTEGER DEFAULT 1,created_at TEXT);
 CREATE TABLE IF NOT EXISTS subscription_configs(subscription_id INTEGER,config_id INTEGER,PRIMARY KEY(subscription_id,config_id),FOREIGN KEY(subscription_id) REFERENCES subscriptions(id) ON DELETE CASCADE,FOREIGN KEY(config_id) REFERENCES configs(id) ON DELETE CASCADE);
 CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE IF NOT EXISTS activities(id INTEGER PRIMARY KEY,kind TEXT,message TEXT,created_at TEXT);
 ''');
 if not c.execute('SELECT 1 FROM admins').fetchone(): c.execute('INSERT INTO admins(username,password_hash,created_at) VALUES(?,?,?)',('admin',generate_password_hash(os.environ.get('ADMIN_PASSWORD','admin123')),now()))
 for k,v in [('app_name','TiTaN'),('public_domain',os.environ.get('RAILWAY_PUBLIC_DOMAIN','')),('theme','midnight')]: c.execute('INSERT OR IGNORE INTO settings VALUES (?,?)',(k,v))
 c.commit(); c.close()
def log(kind,msg):
 c=db(); c.execute('INSERT INTO activities(kind,message,created_at) VALUES(?,?,?)',(kind,msg,now())); c.commit(); c.close()
def q(sql,args=()):
 c=db(); rows=c.execute(sql,args).fetchall(); c.close(); return [dict(x) for x in rows]
def one(sql,args=()):
 c=db(); x=c.execute(sql,args).fetchone(); c.close(); return dict(x) if x else None
def auth(f):
 @wraps(f)
 def w(*a,**kw):
  if not session.get('admin_id'): return jsonify(error='ورود لازم است'),401
  return f(*a,**kw)
 return w

def regenerate():
 configs=q('SELECT c.*,n.domain FROM configs c LEFT JOIN nodes n ON n.id=c.node_id WHERE c.active=1')
 inbounds=[]
 for x in configs:
  proto=x['protocol'].lower(); settings={};
  if proto in ('vless','vmess'): settings={'clients':[{'id':x['uuid'],'email':x['name']}],'decryption':'none'} if proto=='vless' else {'clients':[{'id':x['uuid'],'email':x['name']}],'decryption':'none'}
  elif proto=='trojan': settings={'clients':[{'password':x['uuid'],'email':x['name']}],'fallbacks':[]}
  elif proto=='shadowsocks': settings={'clients':[{'password':x['uuid'],'email':x['name']}],'method':'aes-128-gcm'}
  else: settings={'clients':[{'password':x['uuid'],'email':x['name']}]}
  stream={'network': {'httpupgrade':'httpupgrade','xhttp':'xhttp'}.get(x['transport'].lower(),x['transport'].lower()),'security':'none'}
  if stream['network'] in ('ws','httpupgrade','xhttp'): stream['sockopt']={'tcpFastOpen':True}
  inbound={'tag':'titan-'+str(x['id']),'port':int(os.environ.get('XRAY_PORT','10000')),'listen':'127.0.0.1','protocol':proto,'settings':settings,'streamSettings':stream}
  if stream['network']=='ws': stream['wsSettings']={'path':'/xray/'+str(x['id']),'headers':{'Host':x.get('domain') or ''}}
  elif stream['network']=='grpc': stream['grpcSettings']={'serviceName':x.get('service_name') or 'titan'}
  elif stream['network']=='httpupgrade': stream['httpupgradeSettings']={'path':'/xray/'+str(x['id']),'host':x.get('domain') or ''}
  elif stream['network']=='xhttp': stream['xhttpSettings']={'path':'/xray/'+str(x['id']),'mode':'auto'}
  inbounds.append(inbound)
 cfg={'log':{'loglevel':'warning'},'inbounds':inbounds,'outbounds':[{'protocol':'freedom','tag':'direct'},{'protocol':'blackhole','tag':'block'}]}
 path=os.path.join(XRAY_DIR,'config.json'); open(path,'w').write(json.dumps(cfg,ensure_ascii=False,indent=2));
 domain=os.environ.get('RAILWAY_PUBLIC_DOMAIN',''); public_port=os.environ.get('PORT','8080'); app_port=os.environ.get('APP_PORT','5000'); xray_port=os.environ.get('XRAY_PORT','10000'); open(os.path.join(NGINX_DIR,'default.conf'),'w').write(f'''server {{ listen {public_port}; server_name _; location /xray/ {{ proxy_pass http://127.0.0.1:{xray_port}; proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; proxy_set_header Host $host; }} location / {{ proxy_pass http://127.0.0.1:{app_port}; proxy_set_header Host $host; proxy_set_header X-Forwarded-Proto $scheme; proxy_set_header X-Real-IP $remote_addr; }} }}\n''')
 return path

def xray_validate():
 path=os.path.join(XRAY_DIR,'config.json')
 if not os.path.exists('/usr/local/bin/xray') and not shutil.which('xray'): return True,'xray binary unavailable in development environment'
 try:
  r=subprocess.run(['xray','run','-test','-config',path],capture_output=True,text=True,timeout=15)
  return r.returncode==0,(r.stderr or r.stdout)[-1000:]
 except Exception as e: return False,str(e)
def xray_reload():
 try: subprocess.run(['pkill','-HUP','-x','xray'],capture_output=True,timeout=3)
 except Exception: pass

def public_config(x):
 domain=x.get('domain') or os.environ.get('RAILWAY_PUBLIC_DOMAIN') or request.host.split(':')[0]; port=443; proto=x['protocol'].upper(); transport=x['transport'].lower(); path=x.get('path') or '/xray/'+str(x['id']); path=('/xray/'+str(x['id'])) if path=='/' and transport in ('ws','httpupgrade','xhttp') else path
 if proto=='VLESS': return f"vless://{x['uuid']}@{domain}:{port}?encryption=none&security=tls&type={transport}&host={domain}&path={path}#{x['name']}"
 if proto=='VMESS':
  raw=json.dumps({'v':'2','ps':x['name'],'add':domain,'port':str(port),'id':x['uuid'],'aid':'0','scy':'auto','net':transport,'type':'none','host':domain,'path':path,'tls':'tls'},separators=(',',':')); return 'vmess://'+base64.b64encode(raw.encode()).decode()
 if proto=='TROJAN': return f"trojan://{x['uuid']}@{domain}:{port}?security=tls&type={transport}&host={domain}&path={path}#{x['name']}"
 if proto=='SHADOWSOCKS': return 'ss://'+base64.b64encode(f"2022-blake3-aes-128-gcm:{x['uuid']}@{domain}:{port}".encode()).decode()+'#'+x['name']
 if proto=='HYSTERIA2': return f"hysteria2://{x['uuid']}@{domain}:{port}/?sni={domain}#"+x['name']
 return f"# WireGuard config for {x['name']}\\n# Endpoint: {domain}:{port}\\n# Private key: {x['uuid']}"

@app.get('/health')
def health(): return jsonify(status='ok',database=os.path.exists(DB),xray_config=os.path.exists(os.path.join(XRAY_DIR,'config.json')))
@app.route('/')
def index(): return render_template('index.html')
@app.get('/api/me')
def me(): return jsonify(authenticated=bool(session.get('admin_id')),username=session.get('username'))
@app.post('/api/login')
def login():
 d=request.json or {}; a=one('SELECT * FROM admins WHERE username=?',(d.get('username',''),))
 if not a or not check_password_hash(a['password_hash'],d.get('password','')): return jsonify(error='نام کاربری یا رمز عبور نادرست است'),401
 session.permanent=True; session['admin_id']=a['id']; session['username']=a['username']; log('login','ورود مدیر به پنل'); return jsonify(ok=True)
@app.post('/api/logout')
def logout(): session.clear(); return jsonify(ok=True)
@app.get('/api/dashboard')
@auth
def dashboard():
 return jsonify(users=one('SELECT COUNT(*) n FROM users')['n'],configs=one('SELECT COUNT(*) n FROM configs WHERE active=1')['n'],nodes=one('SELECT COUNT(*) n FROM nodes')['n'],subscriptions=one('SELECT COUNT(*) n FROM subscriptions')['n'],traffic=one('SELECT COALESCE(SUM(used_traffic),0) n FROM configs')['n'],recent_users=q('SELECT * FROM users ORDER BY id DESC LIMIT 5'),activities=q('SELECT * FROM activities ORDER BY id DESC LIMIT 6'),nodes_list=q('SELECT * FROM nodes ORDER BY id DESC LIMIT 5'))
@app.get('/api/dashboard/stats')
@auth
def dashboard_stats(): return dashboard()
@app.get('/api/users')
@auth
def users(): return jsonify(items=q('SELECT u.*,COUNT(c.id) configs,COALESCE(SUM(c.used_traffic),0) traffic FROM users u LEFT JOIN configs c ON c.user_id=u.id GROUP BY u.id ORDER BY u.id DESC'))
@app.post('/api/users')
@auth
def add_user():
 d=request.json or {}; name=(d.get('name') or '').strip()
 if not name:return jsonify(error='نام کاربر الزامی است'),400
 c=db(); cur=c.execute('INSERT INTO users(name,note,created_at) VALUES(?,?,?)',(name,d.get('note',''),now())); uid=cur.lastrowid
 proto=d.get('protocol','VLESS').upper(); tr=d.get('transport','WS').upper()
 if proto not in {'VLESS','VMESS','TROJAN','SHADOWSOCKS'}: return jsonify(error='این Protocol در Core فعلی پشتیبانی نمی‌شود'),400
 if tr not in {'WS','GRPC','TCP','HTTPUPGRADE','XHTTP'}: return jsonify(error='Transport نامعتبر است'),400
 c.execute('INSERT INTO configs(user_id,node_id,name,protocol,transport,tls,fingerprint,alpn,path,service_name,traffic_limit,connection_limit,uuid,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(uid,d.get('node_id') or None,name,proto,tr,d.get('tls','TLS'),d.get('fingerprint','chrome'),d.get('alpn','h2,http/1.1'),d.get('path','/'),d.get('service_name',''),int(d.get('traffic_limit') or 0),int(d.get('connection_limit') or 0),str(uuid.uuid4()),now())); c.commit(); c.close(); regenerate(); valid,detail=xray_validate();
 if not valid:
  c=db(); c.execute('UPDATE configs SET active=0 WHERE user_id=?',(uid,)); c.commit(); c.close(); log('error',f'کانفیگ کاربر {name} نامعتبر است: {detail}'); return jsonify(error='Xray configuration invalid؛ کانفیگ غیرفعال شد',detail=detail),400
 xray_reload(); log('user',f'کاربر {name} ایجاد شد'); return jsonify(ok=True)
@app.get('/api/configs')
@auth
def configs(): return jsonify(items=q('SELECT c.*,u.name user_name,n.name node_name FROM configs c JOIN users u ON u.id=c.user_id LEFT JOIN nodes n ON n.id=c.node_id ORDER BY c.id DESC'))
@app.get('/api/configs/<int:i>/link')
@auth
def config_link(i):
 x=one('SELECT c.*,n.domain FROM configs c LEFT JOIN nodes n ON n.id=c.node_id WHERE c.id=?',(i,))
 if not x:return jsonify(error='کانفیگ پیدا نشد'),404
 return jsonify(link=public_config(x))
@app.get('/api/configs/<int:i>/qr')
@auth
def config_qr(i):
 import qrcode
 x=one('SELECT c.*,n.domain FROM configs c LEFT JOIN nodes n ON n.id=c.node_id WHERE c.id=?',(i,))
 if not x: return jsonify(error='کانفیگ پیدا نشد'),404
 img=qrcode.make(public_config(x)); out=BytesIO(); img.save(out,format='PNG'); out.seek(0); return send_file(out,mimetype='image/png',download_name='titan-config-'+str(i)+'.png')
@app.patch('/api/configs/<int:i>')
@auth
def toggle(i):
 d=request.json or {}; wanted=1 if d.get('active') else 0; c=db(); c.execute('UPDATE configs SET active=? WHERE id=?',(wanted,i)); c.commit(); c.close(); regenerate(); valid,detail=xray_validate();
 if wanted and not valid:
  c=db(); c.execute('UPDATE configs SET active=0 WHERE id=?',(i,)); c.commit(); c.close(); regenerate(); return jsonify(error='Xray configuration invalid؛ فعال نشد',detail=detail),400
 xray_reload(); log('config','وضعیت کانفیگ تغییر کرد'); return jsonify(ok=True)
@app.delete('/api/configs/<int:i>')
@auth
def del_config(i):
 c=db(); c.execute('DELETE FROM configs WHERE id=?',(i,)); c.commit(); c.close(); regenerate(); return jsonify(ok=True)
@app.get('/api/nodes')
@auth
def nodes(): return jsonify(items=q('SELECT * FROM nodes ORDER BY id DESC'))
def probe_node(host, port=443):
 started=time.perf_counter(); ip=''
 try:
  ip=socket.gethostbyname(host)
  with socket.create_connection((host,port),timeout=4): pass
  return {'ip':ip,'reachable':True,'latency':round((time.perf_counter()-started)*1000)}
 except Exception as e: return {'ip':ip,'reachable':False,'latency':None,'error':str(e)}
@app.post('/api/nodes/detect')
@auth
def detect():
 d=request.json or {}; host=d.get('domain','').strip(); result={'domain':host,'city':'','country':'','country_code':'','location':'','flag':''}; probe=probe_node(host) if host else {'reachable':False,'latency':None,'ip':''}; result.update(probe)
 try:
  if probe.get('ip'):
   import requests
   geo=requests.get('https://ipwho.is/'+probe['ip'],timeout=5).json()
   if geo.get('success'): result.update(city=geo.get('city',''),country=geo.get('country',''),country_code=geo.get('country_code',''),location=', '.join([str(geo.get('latitude','')),str(geo.get('longitude',''))]),flag=geo.get('flag',{}).get('emoji',''))
 except Exception: pass
 return jsonify(result)
@app.post('/api/nodes/<int:i>/check')
@auth
def check_node(i):
 n=one('SELECT * FROM nodes WHERE id=?',(i,))
 if not n:return jsonify(error='نود پیدا نشد'),404
 p=probe_node(n['domain']); status='online' if p['reachable'] else 'offline'; c=db(); c.execute('UPDATE nodes SET status=?,latency=?,last_check=? WHERE id=?',(status,p.get('latency'),now(),i)); c.commit(); c.close(); log('node',f'بررسی نود {n["name"]}: {status}'); return jsonify(status=status,latency=p.get('latency'),ip=p.get('ip'))
@app.post('/api/nodes')
@auth
def add_node():
 d=request.json or {}; name=d.get('name','').strip(); domain=d.get('domain','').strip()
 if not name or not domain:return jsonify(error='نام و دامنه الزامی است'),400
 probe=probe_node(domain); status='online' if probe['reachable'] else 'offline'; c=db(); c.execute('INSERT INTO nodes(name,domain,city,country,country_code,location,status,latency,last_check,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(name,domain,d.get('city',''),d.get('country',''),d.get('country_code',''),d.get('location',''),status,probe.get('latency'),now(),now())); c.commit(); c.close(); log('node',f'سرور {name} اضافه شد؛ وضعیت {status}'); return jsonify(ok=True,status=status)
@app.delete('/api/nodes/<int:i>')
@auth
def del_node(i):
 c=db(); c.execute('DELETE FROM nodes WHERE id=?',(i,)); c.commit(); c.close(); return jsonify(ok=True)
@app.get('/api/subscriptions')
@auth
def subs(): return jsonify(items=q('SELECT s.*,COUNT(sc.config_id) configs FROM subscriptions s LEFT JOIN subscription_configs sc ON sc.subscription_id=s.id GROUP BY s.id ORDER BY s.id DESC'))
@app.post('/api/subscriptions')
@auth
def add_sub():
 d=request.json or {}; name=d.get('name','اشتراک جدید'); token=secrets.token_urlsafe(18); ids=d.get('config_ids',[]); c=db(); cur=c.execute('INSERT INTO subscriptions(name,token,created_at) VALUES(?,?,?)',(name,token,now())); sid=cur.lastrowid; c.executemany('INSERT INTO subscription_configs VALUES (?,?)',[(sid,int(i)) for i in ids]); c.commit(); c.close(); log('subscription',f'اشتراک {name} ساخته شد'); return jsonify(ok=True)
@app.delete('/api/subscriptions/<int:i>')
@auth
def del_sub(i):
 c=db(); c.execute('DELETE FROM subscriptions WHERE id=?',(i,)); c.commit(); c.close(); return jsonify(ok=True)
@app.get('/sub/<token>')
def subscription(token):
 s=one('SELECT * FROM subscriptions WHERE token=? AND active=1',(token,));
 if not s:return 'Subscription not found',404
 xs=q('SELECT c.* FROM configs c JOIN subscription_configs sc ON sc.config_id=c.id WHERE sc.subscription_id=? AND c.active=1',(s['id'],)); return '\n'.join(public_config(x) for x in xs),200,{'Content-Type':'text/plain; charset=utf-8'}
@app.get('/api/reports')
@auth
def reports(): return jsonify(items=q('SELECT * FROM activities ORDER BY id DESC LIMIT 100'))
@app.get('/api/settings')
@auth
def get_settings(): return jsonify(items={x['key']:x['value'] for x in q('SELECT * FROM settings')})
@app.put('/api/settings')
@auth
def put_settings():
 d=request.json or {}; c=db(); c.executemany('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',d.items()); c.commit(); c.close(); log('settings','تنظیمات به‌روزرسانی شد'); return jsonify(ok=True)
@app.post('/api/admin/password')
@auth
def password():
 p=(request.json or {}).get('password','');
 if len(p)<8:return jsonify(error='رمز باید حداقل ۸ کاراکتر باشد'),400
 c=db(); c.execute('UPDATE admins SET password_hash=? WHERE id=?',(generate_password_hash(p),session['admin_id'])); c.commit(); c.close(); return jsonify(ok=True)
@app.get('/api/xray/config')
@auth
def xray_config(): return jsonify(path=regenerate(),exists=os.path.exists(os.path.join(XRAY_DIR,'config.json')))

if __name__=='__main__': init(); regenerate(); app.run(host='0.0.0.0',port=int(os.environ.get('PORT','8080')))
else: init(); regenerate()
