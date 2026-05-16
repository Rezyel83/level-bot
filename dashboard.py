import os, math, asyncio, hashlib, hmac, time, json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import aiohttp

load_dotenv()

DISCORD_CLIENT_ID     = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI  = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:8000/callback")
BOT_OWNER_ID          = int(os.getenv("BOT_OWNER_ID", "0"))
SECRET_KEY            = os.getenv("SECRET_KEY", "supergeheim123")
GUILD_ID              = int(os.getenv("GUILD_ID", "0"))

mongo      = AsyncIOMotorClient(os.getenv("MONGODB_URI"))
db         = mongo[os.getenv("MONGODB_DB", "levelbot")]
users_col  = db["users"]
guilds_col = db["guilds"]
logs_col   = db["logs"]

def xp_fuer_level(lvl): return math.floor(100 * (lvl ** 1.5))
def berechne_level(xp):
    lvl = 0
    while xp >= xp_fuer_level(lvl + 1): xp -= xp_fuer_level(lvl + 1); lvl += 1
    return lvl
def xp_im_level(gesamt_xp):
    lvl, xp = 0, gesamt_xp
    while xp >= xp_fuer_level(lvl + 1): xp -= xp_fuer_level(lvl + 1); lvl += 1
    return xp, xp_fuer_level(lvl + 1)

def make_token(user_id):
    msg = f"{user_id}:{int(time.time() // 3600)}"
    return hmac.new(SECRET_KEY.encode(), msg.encode(), hashlib.sha256).hexdigest() + ":" + str(user_id)

def verify_token(token):
    try:
        sig, uid = token.rsplit(":", 1)
        for offset in [0, -1]:
            msg = f"{uid}:{int(time.time() // 3600) + offset}"
            expected = hmac.new(SECRET_KEY.encode(), msg.encode(), hashlib.sha256).hexdigest()
            if hmac.compare_digest(sig, expected): return uid
    except: pass
    return None

def get_uid(request: Request):
    token = request.cookies.get("session")
    return verify_token(token) if token else None

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

CSS = """
:root {
  --bg: #080b14;
  --bg2: #0d1220;
  --card: #111827;
  --card2: #1a2235;
  --border: #1e2d4a;
  --accent: #6c63ff;
  --accent2: #a78bfa;
  --green: #10b981;
  --yellow: #f59e0b;
  --red: #ef4444;
  --text: #e2e8f0;
  --muted: #64748b;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font-family: 'Inter', 'Segoe UI', sans-serif; min-height: 100vh; }
a { text-decoration: none; color: inherit; }

/* NAV */
.nav {
  background: rgba(13,18,32,0.95);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  padding: 0 32px;
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky; top: 0; z-index: 100;
}
.nav-logo { font-size: 1.3rem; font-weight: 800; background: linear-gradient(135deg, var(--accent), var(--accent2)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.nav-user { display: flex; align-items: center; gap: 12px; }
.nav-user img { width: 36px; height: 36px; border-radius: 50%; border: 2px solid var(--accent); }
.nav-logout { color: var(--red); font-size: 13px; padding: 6px 12px; border: 1px solid var(--red); border-radius: 6px; transition: all .2s; }
.nav-logout:hover { background: var(--red); color: white; }

/* LAYOUT */
.layout { display: flex; min-height: calc(100vh - 64px); }
.sidebar {
  width: 220px; background: var(--bg2); border-right: 1px solid var(--border);
  padding: 24px 0; position: sticky; top: 64px; height: calc(100vh - 64px); flex-shrink: 0;
}
.sidebar-item {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 24px; color: var(--muted); font-size: 14px; font-weight: 500;
  cursor: pointer; transition: all .2s; border-left: 3px solid transparent;
}
.sidebar-item:hover { color: var(--text); background: rgba(108,99,255,.08); }
.sidebar-item.active { color: var(--accent2); background: rgba(108,99,255,.12); border-left-color: var(--accent); }
.sidebar-item .icon { font-size: 18px; width: 22px; text-align: center; }

.main { flex: 1; padding: 32px; overflow-y: auto; }
.page { display: none; }
.page.active { display: block; }

/* CARDS */
.card {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 16px; padding: 24px;
}
.card-sm { padding: 16px; }
.grid { display: grid; gap: 16px; }
.grid-4 { grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }
.grid-2 { grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }

/* STAT CARD */
.stat-card {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 16px; padding: 20px 24px;
  position: relative; overflow: hidden;
}
.stat-card::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px;
}
.stat-card.purple::before { background: linear-gradient(90deg, var(--accent), var(--accent2)); }
.stat-card.green::before { background: linear-gradient(90deg, #10b981, #34d399); }
.stat-card.yellow::before { background: linear-gradient(90deg, #f59e0b, #fbbf24); }
.stat-card.red::before { background: linear-gradient(90deg, #ef4444, #f87171); }
.stat-val { font-size: 2.2rem; font-weight: 800; line-height: 1; }
.stat-label { color: var(--muted); font-size: 13px; margin-top: 6px; }
.stat-icon { position: absolute; right: 20px; top: 50%; transform: translateY(-50%); font-size: 2.5rem; opacity: .15; }

/* XP BAR */
.xp-bar { background: var(--border); border-radius: 999px; height: 10px; overflow: hidden; }
.xp-fill { background: linear-gradient(90deg, var(--accent), var(--accent2)); height: 100%; border-radius: 999px; transition: width .6s cubic-bezier(.4,0,.2,1); }
.xp-bar-lg { height: 18px; }

/* BUTTONS */
.btn { padding: 9px 18px; border-radius: 8px; border: none; cursor: pointer; font-weight: 600; font-size: 14px; transition: all .2s; display: inline-flex; align-items: center; gap: 6px; }
.btn-primary { background: var(--accent); color: white; }
.btn-primary:hover { background: #5a52d5; transform: translateY(-1px); }
.btn-danger { background: var(--red); color: white; }
.btn-danger:hover { background: #dc2626; }
.btn-success { background: var(--green); color: white; }
.btn-success:hover { background: #059669; }
.btn-ghost { background: transparent; color: var(--muted); border: 1px solid var(--border); }
.btn-ghost:hover { border-color: var(--accent); color: var(--accent2); }
.btn-discord { background: #5865f2; color: white; padding: 14px 32px; border-radius: 12px; font-size: 16px; font-weight: 700; display: inline-flex; align-items: center; gap: 10px; transition: all .2s; }
.btn-discord:hover { background: #4752c4; transform: translateY(-2px); box-shadow: 0 8px 24px rgba(88,101,242,.4); }

/* INPUTS */
input, select { background: var(--bg2); border: 1px solid var(--border); color: var(--text); border-radius: 8px; padding: 10px 14px; font-size: 14px; transition: border .2s; }
input:focus, select:focus { outline: none; border-color: var(--accent); }

/* TABLE */
.table-row { display: flex; align-items: center; gap: 12px; padding: 12px 16px; border-radius: 10px; transition: background .15s; }
.table-row:hover { background: var(--card2); }
.table-row.me { background: rgba(108,99,255,.1); border: 1px solid rgba(108,99,255,.3); }
.rank-num { width: 36px; text-align: center; font-weight: 700; color: var(--muted); }
.rank-avatar { width: 40px; height: 40px; border-radius: 50%; border: 2px solid var(--border); }
.rank-name { flex: 1; font-weight: 600; }
.rank-info { color: var(--muted); font-size: 13px; }

/* BADGES */
.badge { padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
.badge-purple { background: rgba(108,99,255,.2); color: var(--accent2); }
.badge-green { background: rgba(16,185,129,.2); color: #34d399; }
.badge-yellow { background: rgba(245,158,11,.2); color: #fbbf24; }

/* ROLE CARD */
.role-card { display: flex; align-items: center; gap: 16px; padding: 16px; background: var(--card2); border: 1px solid var(--border); border-radius: 12px; }
.role-lvl { width: 52px; height: 52px; border-radius: 50%; background: linear-gradient(135deg, var(--accent), var(--accent2)); display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 18px; flex-shrink: 0; }

/* LOG ITEM */
.log-item { display: flex; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--border); }
.log-icon { width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 16px; flex-shrink: 0; }

/* TOAST */
.toast { position: fixed; bottom: 24px; right: 24px; padding: 14px 20px; border-radius: 10px; font-weight: 600; font-size: 14px; z-index: 9999; transform: translateY(100px); transition: transform .3s; box-shadow: 0 8px 24px rgba(0,0,0,.4); }
.toast.show { transform: translateY(0); }

/* LOGIN PAGE */
.login-page { min-height: 100vh; display: flex; align-items: center; justify-content: center; background: radial-gradient(ellipse at center, #0d1220 0%, #080b14 70%); }
.login-card { text-align: center; max-width: 420px; padding: 48px; background: var(--card); border: 1px solid var(--border); border-radius: 24px; box-shadow: 0 24px 64px rgba(0,0,0,.5); }
.login-glow { width: 80px; height: 80px; background: linear-gradient(135deg, var(--accent), var(--accent2)); border-radius: 20px; display: flex; align-items: center; justify-content: center; font-size: 36px; margin: 0 auto 24px; box-shadow: 0 8px 32px rgba(108,99,255,.4); }
.login-title { font-size: 2rem; font-weight: 800; margin-bottom: 8px; }
.login-sub { color: var(--muted); margin-bottom: 32px; line-height: 1.6; }

/* SECTION TITLE */
.section-title { font-size: 1.2rem; font-weight: 700; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }

/* PROFILE HEADER */
.profile-header { background: linear-gradient(135deg, #0d1220, #111827); border: 1px solid var(--border); border-radius: 20px; padding: 32px; margin-bottom: 24px; position: relative; overflow: hidden; }
.profile-header::before { content:''; position:absolute; top:-50px; right:-50px; width:200px; height:200px; background: radial-gradient(circle, rgba(108,99,255,.15) 0%, transparent 70%); border-radius:50%; }

@media (max-width: 768px) {
  .sidebar { display: none; }
  .main { padding: 16px; }
  .grid-4 { grid-template-columns: 1fr 1fr; }
}
"""

JS = """
const ME_UID = '{UID}';
const IS_OWNER = {IS_OWNER};

function showPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.sidebar-item').forEach(s => s.classList.remove('active'));
  document.getElementById('page-' + name).classList.add('active');
  document.getElementById('nav-' + name).classList.add('active');
  if (name === 'leaderboard' && !leaderboardLoaded) loadLeaderboard(1);
  if (name === 'admin' && IS_OWNER && !adminLoaded) loadAdmin();
}

async function api(url, method='GET', body=null) {
  const opts = { method, headers: {'Content-Type':'application/json'} };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(url, opts);
  return r.json();
}

function toast(msg, type='success') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.background = type === 'success' ? '#10b981' : type === 'error' ? '#ef4444' : '#6c63ff';
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3000);
}

// LEADERBOARD
let leaderboardLoaded = false, lbPage = 1;
async function loadLeaderboard(page) {
  lbPage = Math.max(1, page);
  const data = await api('/api/leaderboard?page=' + lbPage);
  leaderboardLoaded = true;
  if (!data.entries) return;
  const medals = ['🥇','🥈','🥉'];
  document.getElementById('lb-list').innerHTML = data.entries.map((e, i) => {
    const rank = i + 1 + (lbPage-1)*10;
    const isMe = e.user_id === ME_UID;
    const prefix = rank <= 3 ? `<span style="font-size:22px;">${medals[rank-1]}</span>` : `<span class="rank-num" style="color:var(--muted);">#${rank}</span>`;
    return `<div class="table-row ${isMe ? 'me' : ''}">
      ${prefix}
      <img class="rank-avatar" src="${e.avatar}" onerror="this.src='https://cdn.discordapp.com/embed/avatars/0.png'">
      <div style="flex:1;">
        <div class="rank-name">${e.username}${isMe ? ' <span class="badge badge-purple">Du</span>' : ''}</div>
        <div class="rank-info">Level ${e.level} · ${e.xp.toLocaleString()} XP</div>
      </div>
      <div style="text-align:right;">
        <div style="font-weight:700;color:var(--accent2);">${e.xp.toLocaleString()}</div>
        <div style="font-size:12px;color:var(--muted);">XP</div>
      </div>
    </div>`;
  }).join('');
  document.getElementById('lb-page').textContent = 'Seite ' + lbPage;
}

// ADMIN
let adminLoaded = false;
async function loadAdmin() {
  adminLoaded = true;
  loadRoleRewards();
  const data = await api('/api/admin/stats');
  document.getElementById('admin-total-users').textContent = data.total_users;
  document.getElementById('admin-total-xp').textContent = data.total_xp?.toLocaleString();
  document.getElementById('admin-max-level').textContent = data.max_level;
  loadAdminLogs();
}

async function loadAdminLogs() {
  const data = await api('/api/admin/logs');
  const emojis = {msg:'💬',voice:'🎤',reaction:'👍',daily:'📅',invite:'📨',admin_add:'👑',admin_remove:'🔧'};
  const colors = {msg:'rgba(108,99,255,.2)',voice:'rgba(16,185,129,.2)',reaction:'rgba(245,158,11,.2)',daily:'rgba(99,179,237,.2)',invite:'rgba(248,113,113,.2)',admin_add:'rgba(167,139,250,.2)',admin_remove:'rgba(252,165,165,.2)'};
  document.getElementById('admin-logs').innerHTML = (data.logs || []).map(l => `
    <div class="log-item">
      <div class="log-icon" style="background:${colors[l.aktion]||'var(--card2)'};">${emojis[l.aktion]||'⭐'}</div>
      <div style="flex:1;"><div style="font-size:13px;font-weight:600;">${l.aktion}</div><div style="font-size:12px;color:var(--muted);">User ${l.user_id}</div></div>
      <div style="text-align:right;"><div style="color:var(--green);font-weight:700;">+${l.xp} XP</div><div style="font-size:12px;color:var(--muted);">${l.ts}</div></div>
    </div>`).join('') || '<div style="color:var(--muted);text-align:center;padding:24px;">Keine Logs</div>';
}

async function adminAction(action) {
  const uid = document.getElementById('admin-uid').value.trim();
  const amount = parseInt(document.getElementById('admin-amount').value) || 0;
  if (!uid) { toast('User ID eingeben!', 'error'); return; }
  const r = await api('/api/admin/xp', 'POST', {user_id: uid, action, amount});
  if (r.ok) { toast('✅ Erledigt!'); loadAdmin(); }
  else toast('❌ ' + (r.error || 'Fehler'), 'error');
}

async function loadGuildRoles() {
  const data = await api('/api/admin/guild-roles');
  if (!data.roles) return;
  const sel = document.getElementById('role-id');
  sel.innerHTML = '<option value="">Rolle auswählen...</option>' + 
    data.roles.map(r => {
      const color = r.color ? '#' + r.color.toString(16).padStart(6,'0') : '#99aab5';
      return `<option value="${r.id}" style="color:${color};">@${r.name}</option>`;
    }).join('');
}

async function loadRoleRewards() {
  loadGuildRoles();
  const data = await api('/api/admin/role-rewards');
  if (!data.rewards) return;
  const entries = Object.entries(data.rewards);
  if (entries.length === 0) {
    document.getElementById('role-rewards-list').innerHTML = '<div style="color:var(--muted);">Noch keine Rollen konfiguriert</div>';
    return;
  }
  document.getElementById('role-rewards-list').innerHTML = entries
    .sort((a,b) => parseInt(a[0]) - parseInt(b[0]))
    .map(([lvl, rid]) => {
      const roleEl = document.querySelector(`#role-id option[value="${rid}"]`);
      const roleName = roleEl ? roleEl.text : `ID: ${rid}`;
      return `
      <div style="display:flex;align-items:center;gap:12px;padding:10px;background:var(--card2);border-radius:8px;margin-bottom:8px;">
        <div style="background:var(--accent);border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-weight:700;">${lvl}</div>
        <div style="flex:1;"><div style="font-weight:600;">Level ${lvl}</div><div style="color:var(--muted);font-size:13px;">${roleName}</div></div>
        <button class="btn btn-danger" onclick="removeRoleReward('${lvl}')" style="padding:6px 12px;font-size:13px;">Entfernen</button>
      </div>`;
    }).join('');
}

async function addRoleReward() {
  const level = parseInt(document.getElementById('role-level').value);
  const sel = document.getElementById('role-id');
  const roleId = sel.value;
  const roleName = sel.options[sel.selectedIndex]?.text || roleId;
  if (!level || !roleId) { toast('Level und Rolle auswählen!', 'error'); return; }
  const r = await api('/api/admin/role-rewards', 'POST', {level, role_id: roleId});
  if (r.ok) { toast('✅ ' + roleName + ' bei Level ' + level + ' hinzugefügt!'); loadRoleRewards(); document.getElementById('role-level').value=''; }
  else toast('❌ ' + (r.error || 'Fehler'), 'error');
}

async function removeRoleReward(level) {
  const r = await api('/api/admin/role-rewards/' + level, 'DELETE');
  if (r.ok) { toast('✅ Rolle entfernt!'); loadRoleRewards(); }
  else toast('❌ Fehler', 'error');
}

async function serverReset() {
  if (!confirm('WIRKLICH alle XP löschen? Das kann nicht rückgängig gemacht werden!')) return;
  const r = await api('/api/admin/reset', 'POST');
  if (r.ok) toast('✅ Server zurückgesetzt!');
  else toast('❌ Fehler', 'error');
}
"""

def render_page(content: str, uid: str = "", is_owner: bool = False, username: str = "", avatar: str = "") -> str:
    js = JS.replace('{UID}', uid).replace('{IS_OWNER}', 'true' if is_owner else 'false')
    admin_nav = '<div class="sidebar-item" id="nav-admin" onclick="showPage(\'admin\')"><span class="icon">👑</span> Admin</div>' if is_owner else ''
    admin_page = '<div class="page" id="page-admin">' + ADMIN_HTML + '</div>' if is_owner else ''
    
    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Level Bot Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<nav class="nav">
  <div class="nav-logo">🎮 Level Bot</div>
  <div class="nav-user">
    {'<img src="' + avatar + '" alt="avatar">' if avatar else ''}
    <span style="font-weight:600;">{username}</span>
    <a href="/logout" class="nav-logout">Ausloggen</a>
  </div>
</nav>
<div class="layout">
  <aside class="sidebar">
    <div class="sidebar-item active" id="nav-profil" onclick="showPage('profil')"><span class="icon">👤</span> Mein Profil</div>
    <div class="sidebar-item" id="nav-leaderboard" onclick="showPage('leaderboard')"><span class="icon">🏆</span> Rangliste</div>
    <div class="sidebar-item" id="nav-roadmap" onclick="showPage('roadmap')"><span class="icon">🗺️</span> Rollen Roadmap</div>
    <div class="sidebar-item" id="nav-logs" onclick="showPage('logs')"><span class="icon">📋</span> Meine Logs</div>
    {admin_nav}
  </aside>
  <main class="main">
    {content}
    {admin_page}
  </main>
</div>
<div class="toast" id="toast"></div>
<script>{js}</script>
</body>
</html>"""

ADMIN_HTML = """
<div class="section-title">👑 Admin Panel</div>
<div class="grid grid-4" style="margin-bottom:24px;">
  <div class="stat-card purple"><div class="stat-val" id="admin-total-users">…</div><div class="stat-label">Aktive User</div><div class="stat-icon">👥</div></div>
  <div class="stat-card green"><div class="stat-val" id="admin-total-xp">…</div><div class="stat-label">XP gesamt</div><div class="stat-icon">⭐</div></div>
  <div class="stat-card yellow"><div class="stat-val" id="admin-max-level">…</div><div class="stat-label">Max Level</div><div class="stat-icon">🏆</div></div>
</div>

<div class="grid grid-2" style="margin-bottom:24px;">
  <div class="card">
    <div class="section-title">🔧 XP bearbeiten</div>
    <div style="display:flex;flex-direction:column;gap:12px;">
      <input id="admin-uid" placeholder="Discord User ID">
      <input id="admin-amount" type="number" placeholder="Menge (XP oder Level)">
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <button class="btn btn-success" onclick="adminAction('add')">+ XP hinzufügen</button>
        <button class="btn btn-danger" onclick="adminAction('remove')">− XP entfernen</button>
        <button class="btn btn-primary" onclick="adminAction('set_level')">Level setzen</button>
        <button class="btn btn-ghost" onclick="adminAction('reset')">User reset</button>
      </div>
    </div>
  </div>
  <div class="card">
    <div class="section-title">⚠️ Gefährliche Aktionen</div>
    <p style="color:var(--muted);font-size:14px;margin-bottom:16px;">Diese Aktionen können nicht rückgängig gemacht werden.</p>
    <button class="btn btn-danger" onclick="serverReset()">🗑️ Server komplett zurücksetzen</button>
  </div>
</div>

<div class="card" style="margin-bottom:24px;">
  <div class="section-title">🎭 Rollen-Belohnungen</div>
  <p style="color:var(--muted);font-size:14px;margin-bottom:16px;">Welche Rolle wird bei welchem Level vergeben?</p>
  <div id="role-rewards-list" style="margin-bottom:16px;">Lädt…</div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
    <input id="role-level" type="number" placeholder="Level" style="max-width:100px;">
    <select id="role-id" style="flex:1;min-width:200px;"><option value="">Lade Rollen...</option></select>
    <button class="btn btn-success" onclick="addRoleReward()">+ Hinzufügen</button>
  </div>
</div>

<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <div class="section-title" style="margin:0;">📋 Letzte Aktivitäten</div>
    <button class="btn btn-ghost" onclick="loadAdminLogs()" style="font-size:13px;">🔄 Aktualisieren</button>
  </div>
  <div id="admin-logs">Lädt…</div>
</div>
"""

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if get_uid(request):
        return RedirectResponse("/dashboard")
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Level Bot</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>{CSS}
.particles {{ position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;overflow:hidden;z-index:0; }}
.particle {{ position:absolute;border-radius:50%;animation:float linear infinite; }}
@keyframes float {{ 0%{{transform:translateY(100vh) rotate(0deg);opacity:0}} 10%{{opacity:1}} 90%{{opacity:1}} 100%{{transform:translateY(-100px) rotate(720deg);opacity:0}} }}
</style></head>
<body class="login-page">
<div class="particles" id="particles"></div>
<div class="login-card" style="position:relative;z-index:1;">
  <div class="login-glow">🎮</div>
  <h1 class="login-title">Level Bot</h1>
  <p class="login-sub">Schau dein Profil an, verfolge deinen Fortschritt und verwalte deinen Server.</p>
  <a href="https://discord.com/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&redirect_uri={DISCORD_REDIRECT_URI}&response_type=code&scope=identify" class="btn-discord">
    <svg width="20" height="20" viewBox="0 0 71 55" fill="white"><path d="M60.1 4.9A58.5 58.5 0 0045.6 1a40 40 0 00-1.8 3.6 54.2 54.2 0 00-16.2 0A40 40 0 0025.8 1 58.3 58.3 0 0011.3 5C1.6 19.7-1 34 .3 48a59 59 0 0017.9 9 42.4 42.4 0 003.7-5.9 38.3 38.3 0 01-5.8-2.8l1.4-1.1a42 42 0 0036 0l1.4 1.1a38.4 38.4 0 01-5.8 2.8 42 42 0 003.6 6 58.8 58.8 0 0018-9.1C72.2 32 68.4 17.7 60.1 4.9zM23.8 39.3c-3.5 0-6.4-3.2-6.4-7.1s2.8-7.1 6.4-7.1c3.5 0 6.4 3.2 6.3 7.1 0 3.9-2.8 7.1-6.3 7.1zm23.4 0c-3.5 0-6.4-3.2-6.4-7.1s2.8-7.1 6.4-7.1c3.5 0 6.4 3.2 6.3 7.1 0 3.9-2.8 7.1-6.3 7.1z"/></svg>
    Mit Discord einloggen
  </a>
</div>
<script>
const p = document.getElementById('particles');
for(let i=0;i<20;i++){{
  const d = document.createElement('div');
  d.className='particle';
  const size = Math.random()*6+2;
  d.style.cssText=`width:${{size}}px;height:${{size}}px;left:${{Math.random()*100}}%;background:rgba(${{Math.random()>.5?'108,99,255':'167,139,250'}},${{Math.random()*.4+.1}});animation-duration:${{Math.random()*15+10}}s;animation-delay:${{Math.random()*10}}s;`;
  p.appendChild(d);
}}
</script>
</body></html>""")

@app.get("/callback")
async def callback(code: str):
    uid = None
    avatar = ""
    username = ""
    try:
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            # Token holen
            async with session.post("https://discord.com/api/oauth2/token", data={
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": DISCORD_REDIRECT_URI,
            }) as r:
                data = await r.json()
            
            token = data.get("access_token")
            if not token:
                print("❌ Kein access_token:", data)
                return HTMLResponse("<h1>Login fehlgeschlagen - kein Token</h1>")
            
            # User info holen
            async with session.get("https://discord.com/api/users/@me", 
                                   headers={"Authorization": f"Bearer {token}"}) as r2:
                user = await r2.json()
            
            uid = user.get("id")
            if not uid:
                return HTMLResponse("<h1>Fehler - keine User ID</h1>")
            
            avatar_hash = user.get("avatar")
            avatar = f"https://cdn.discordapp.com/avatars/{uid}/{avatar_hash}.png" if avatar_hash else ""
            username = user.get("global_name") or user.get("username", "")
            print(f"✅ Login: {username} ({uid})")
    except Exception as e:
        print(f"❌ OAuth Fehler: {e}")
        return HTMLResponse(f"<h1>Fehler: {e}</h1>")

    session_token = make_token(uid)
    resp = RedirectResponse("/dashboard", status_code=302)
    resp.set_cookie("session", session_token, max_age=86400*7, httponly=True, samesite="lax", secure=True)
    resp.set_cookie("uid", uid, max_age=86400*7, samesite="lax", secure=True)
    resp.set_cookie("avatar", avatar, max_age=86400*7, samesite="lax", secure=True)
    resp.set_cookie("username", username, max_age=86400*7, samesite="lax", secure=True)
    return resp

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    uid = get_uid(request)
    if not uid: return RedirectResponse("/")
    is_owner = int(uid) == BOT_OWNER_ID
    username = request.cookies.get("username", "User")
    avatar = request.cookies.get("avatar", "")

    u = await users_col.find_one({"guild_id": GUILD_ID, "user_id": int(uid)}) or {"xp":0,"level":0,"streak":0,"invites":0}
    cur, nxt = xp_im_level(u["xp"])
    pct = int((cur/nxt)*100) if nxt > 0 else 0
    rang = await users_col.count_documents({"guild_id": GUILD_ID, "xp": {"$gt": u["xp"]}}) + 1
    total_users = await users_col.count_documents({"guild_id": GUILD_ID})

    cfg = await guilds_col.find_one({"guild_id": GUILD_ID}) or {}
    role_rewards = cfg.get("role_rewards", {})
    level_names = cfg.get("level_names", {})

    # Roadmap
    future_roles = sorted([(int(l), r) for l, r in role_rewards.items() if int(l) > u["level"]])[:6]
    roadmap_html = ""
    for lvl, rid in future_roles:
        xp_target = sum(xp_fuer_level(l+1) for l in range(lvl))
        xp_needed = max(0, xp_target - u["xp"])
        prog = min(100, max(0, int((u["xp"] / max(1, xp_target)) * 100)))
        name = level_names.get(str(lvl), f"Level {lvl} Rolle")
        roadmap_html += f"""
        <div class="role-card">
          <div class="role-lvl">{lvl}</div>
          <div style="flex:1;">
            <div style="font-weight:700;margin-bottom:4px;">{name}</div>
            <div style="color:var(--muted);font-size:13px;margin-bottom:8px;">{'✅ Erreicht!' if xp_needed == 0 else f'Noch {xp_needed:,} XP'}</div>
            <div class="xp-bar"><div class="xp-fill" style="width:{prog}%;"></div></div>
          </div>
          <div style="text-align:right;font-size:13px;color:var(--muted);">Level {lvl}</div>
        </div>"""
    if not roadmap_html:
        roadmap_html = '<div class="card" style="text-align:center;color:var(--muted);padding:48px;">Keine Rollen konfiguriert – Admin kann /rolle-bei-level nutzen</div>'

    # Logs
    raw_logs = await logs_col.find({"guild_id": GUILD_ID, "user_id": int(uid)}).sort("ts", -1).limit(15).to_list(15)
    emojis = {"msg":"💬","voice":"🎤","reaction":"👍","daily":"📅","invite":"📨","admin_add":"👑","admin_remove":"🔧"}
    colors = {"msg":"rgba(108,99,255,.2)","voice":"rgba(16,185,129,.2)","reaction":"rgba(245,158,11,.2)","daily":"rgba(99,179,237,.2)","invite":"rgba(248,113,113,.2)"}
    logs_html = ""
    for l in raw_logs:
        ts = l.get("ts", datetime.utcnow())
        ts_str = ts.strftime("%d.%m %H:%M") if isinstance(ts, datetime) else "?"
        act = l.get("aktion","?")
        xp = l.get("xp", 0)
        logs_html += f"""<div class="log-item">
          <div class="log-icon" style="background:{colors.get(act, 'var(--card2)')};">{emojis.get(act,'⭐')}</div>
          <div style="flex:1;"><div style="font-size:13px;font-weight:600;">{act}</div></div>
          <div style="color:var(--green);font-weight:700;">+{xp} XP</div>
          <div style="color:var(--muted);font-size:12px;min-width:70px;text-align:right;">{ts_str}</div>
        </div>"""

    content = f"""
    <!-- PROFIL -->
    <div class="page active" id="page-profil">
      <div class="profile-header">
        <div style="display:flex;align-items:center;gap:20px;flex-wrap:wrap;">
          {'<img src="' + avatar + '" style="width:80px;height:80px;border-radius:50%;border:3px solid var(--accent);">' if avatar else '<div style="width:80px;height:80px;border-radius:50%;background:var(--accent);display:flex;align-items:center;justify-content:center;font-size:32px;">👤</div>'}
          <div>
            <h2 style="font-size:1.6rem;font-weight:800;">{username}</h2>
            <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap;">
              <span class="badge badge-purple">Level {u["level"]}</span>
              <span class="badge badge-green">Rang #{rang}</span>
              <span class="badge badge-yellow">🔥 {u.get("streak",0)} Streak</span>
            </div>
          </div>
        </div>
      </div>

      <div class="grid grid-4" style="margin-bottom:24px;">
        <div class="stat-card purple"><div class="stat-val">{u["level"]}</div><div class="stat-label">Level</div><div class="stat-icon">⚡</div></div>
        <div class="stat-card green"><div class="stat-val">#{rang}</div><div class="stat-label">Rang von {total_users}</div><div class="stat-icon">🏆</div></div>
        <div class="stat-card yellow"><div class="stat-val">{u["xp"]:,}</div><div class="stat-label">XP gesamt</div><div class="stat-icon">⭐</div></div>
        <div class="stat-card red"><div class="stat-val">🔥{u.get("streak",0)}</div><div class="stat-label">Streak Tage</div><div class="stat-icon">🔥</div></div>
      </div>

      <div class="card" style="margin-bottom:24px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
          <div style="font-weight:700;">Fortschritt zu Level {u["level"]+1}</div>
          <div style="color:var(--muted);font-size:14px;">{cur:,} / {nxt:,} XP <span class="badge badge-purple">{pct}%</span></div>
        </div>
        <div class="xp-bar xp-bar-lg"><div class="xp-fill" style="width:{pct}%;"></div></div>
        <div style="color:var(--muted);font-size:13px;margin-top:8px;">Noch {nxt-cur:,} XP bis zum nächsten Level</div>
      </div>

      <div class="card">
        <div class="section-title">📊 Weitere Stats</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
          <div style="background:var(--card2);border-radius:10px;padding:16px;"><div style="color:var(--muted);font-size:13px;">📨 Einladungen</div><div style="font-size:1.4rem;font-weight:700;">{u.get("invites",0)}</div></div>
          <div style="background:var(--card2);border-radius:10px;padding:16px;"><div style="color:var(--muted);font-size:13px;">🎯 XP bis nächstes Level</div><div style="font-size:1.4rem;font-weight:700;">{nxt-cur:,}</div></div>
        </div>
      </div>
    </div>

    <!-- LEADERBOARD -->
    <div class="page" id="page-leaderboard">
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">
          <div class="section-title" style="margin:0;">🏆 Rangliste</div>
          <span id="lb-page" style="color:var(--muted);font-size:14px;">Seite 1</span>
        </div>
        <div id="lb-list" style="display:flex;flex-direction:column;gap:4px;">Lädt…</div>
        <div style="display:flex;gap:8px;margin-top:16px;">
          <button class="btn btn-ghost" onclick="loadLeaderboard(lbPage-1)">← Zurück</button>
          <button class="btn btn-ghost" onclick="loadLeaderboard(lbPage+1)">Weiter →</button>
        </div>
      </div>
    </div>

    <!-- ROADMAP -->
    <div class="page" id="page-roadmap">
      <div class="section-title">🗺️ Deine Rollen Roadmap</div>
      <p style="color:var(--muted);font-size:14px;margin-bottom:20px;">Diese Rollen bekommst du automatisch wenn du das Level erreichst.</p>
      <div style="display:flex;flex-direction:column;gap:12px;">{roadmap_html}</div>
    </div>

    <!-- LOGS -->
    <div class="page" id="page-logs">
      <div class="card">
        <div class="section-title">📋 Deine XP-Historie</div>
        {logs_html or '<div style="color:var(--muted);text-align:center;padding:48px;">Noch keine Aktivität</div>'}
      </div>
    </div>
    """
    return HTMLResponse(render_page(content, uid, is_owner, username, avatar))

@app.get("/api/leaderboard")
async def api_leaderboard(request: Request, page: int = 1):
    if not get_uid(request): raise HTTPException(401)
    pp = 10
    entries = await users_col.find({"guild_id": GUILD_ID}).sort("xp",-1).skip((page-1)*pp).limit(pp).to_list(pp)
    result = []
    async with aiohttp.ClientSession() as s:
        for e in entries:
            try:
                r = await s.get(f"https://discord.com/api/users/{e['user_id']}", headers={"Authorization": f"Bot {os.getenv('DISCORD_TOKEN')}"})
                u = await r.json()
                ah = u.get("avatar")
                avatar = f"https://cdn.discordapp.com/avatars/{e['user_id']}/{ah}.png" if ah else f"https://cdn.discordapp.com/embed/avatars/{int(e['user_id'])%5}.png"
                name = u.get("global_name") or u.get("username","?")
            except:
                avatar = "https://cdn.discordapp.com/embed/avatars/0.png"; name = "?"
            result.append({"user_id":str(e["user_id"]),"username":name,"avatar":avatar,"level":e["level"],"xp":e["xp"]})
    return {"entries": result, "page": page}

@app.get("/api/admin/stats")
async def api_admin_stats(request: Request):
    uid = get_uid(request)
    if not uid or int(uid) != BOT_OWNER_ID: raise HTTPException(403)
    total = await users_col.count_documents({"guild_id": GUILD_ID})
    res = await users_col.aggregate([{"$match":{"guild_id":GUILD_ID}},{"$group":{"_id":None,"xp":{"$sum":"$xp"},"max_lvl":{"$max":"$level"}}}]).to_list(1)
    return {"total_users":total,"total_xp":res[0]["xp"] if res else 0,"max_level":res[0]["max_lvl"] if res else 0}

@app.post("/api/admin/xp")
async def api_admin_xp(request: Request):
    uid = get_uid(request)
    if not uid or int(uid) != BOT_OWNER_ID: raise HTTPException(403)
    body = await request.json()
    tid = int(body.get("user_id",0)); action = body.get("action"); amount = int(body.get("amount",0))
    u = await users_col.find_one({"guild_id":GUILD_ID,"user_id":tid})
    if not u: return {"ok":False,"error":"User nicht gefunden"}
    nx = {"add":u["xp"]+amount,"remove":max(0,u["xp"]-amount),"set_level":sum(xp_fuer_level(l+1) for l in range(amount)),"reset":0}.get(action)
    if nx is None: return {"ok":False,"error":"Unbekannte Aktion"}
    await users_col.update_one({"guild_id":GUILD_ID,"user_id":tid},{"$set":{"xp":nx,"level":berechne_level(nx)}})
    return {"ok":True}

@app.post("/api/admin/reset")
async def api_admin_reset(request: Request):
    uid = get_uid(request)
    if not uid or int(uid) != BOT_OWNER_ID: raise HTTPException(403)
    await users_col.delete_many({"guild_id": GUILD_ID})
    return {"ok": True}

@app.get("/api/admin/logs")
async def api_admin_logs(request: Request):
    uid = get_uid(request)
    if not uid or int(uid) != BOT_OWNER_ID: raise HTTPException(403)
    logs = await logs_col.find({"guild_id":GUILD_ID}).sort("ts",-1).limit(50).to_list(50)
    return {"logs":[{"user_id":str(l.get("user_id")),"aktion":l.get("aktion"),"xp":l.get("xp",0),"ts":l["ts"].strftime("%d.%m %H:%M") if isinstance(l.get("ts"),datetime) else "?"} for l in logs]}

@app.get("/api/admin/guild-roles")
async def api_guild_roles(request: Request):
    uid = get_uid(request)
    if not uid or int(uid) != BOT_OWNER_ID: raise HTTPException(403)
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"https://discord.com/api/guilds/{GUILD_ID}/roles",
            headers={"Authorization": f"Bot {os.getenv('DISCORD_TOKEN')}"}
        ) as r:
            roles = await r.json()
    # Sortieren nach Position, @everyone rausfiltern
    roles = [{"id": str(r["id"]), "name": r["name"], "color": r.get("color", 0)} 
             for r in sorted(roles, key=lambda x: x.get("position", 0), reverse=True)
             if r["name"] != "@everyone"]
    return {"roles": roles}

@app.get("/api/admin/role-rewards")
async def api_get_role_rewards(request: Request):
    uid = get_uid(request)
    if not uid or int(uid) != BOT_OWNER_ID: raise HTTPException(403)
    cfg = await guilds_col.find_one({"guild_id": GUILD_ID}) or {}
    return {"rewards": cfg.get("role_rewards", {})}

@app.post("/api/admin/role-rewards")
async def api_add_role_reward(request: Request):
    uid = get_uid(request)
    if not uid or int(uid) != BOT_OWNER_ID: raise HTTPException(403)
    body = await request.json()
    level = str(body.get("level"))
    role_id = str(body.get("role_id"))
    if not level or not role_id: return {"ok": False, "error": "Level und Rollen-ID erforderlich"}
    await guilds_col.update_one(
        {"guild_id": GUILD_ID},
        {"$set": {f"role_rewards.{level}": int(role_id)}},
        upsert=True
    )
    return {"ok": True}

@app.delete("/api/admin/role-rewards/{level}")
async def api_remove_role_reward(level: str, request: Request):
    uid = get_uid(request)
    if not uid or int(uid) != BOT_OWNER_ID: raise HTTPException(403)
    await guilds_col.update_one(
        {"guild_id": GUILD_ID},
        {"$unset": {f"role_rewards.{level}": ""}}
    )
    return {"ok": True}

@app.get("/logout")
async def logout():
    r = RedirectResponse("/")
    for c in ["session","uid","avatar","username"]: r.delete_cookie(c)
    return r

@app.get("/health")
async def health(): return {"status":"ok"}