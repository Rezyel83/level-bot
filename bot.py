import discord
from discord.ext import commands, tasks
from discord import app_commands
import os, math, time, asyncio, threading
from datetime import datetime, timedelta
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
import uvicorn
from fastapi import FastAPI

load_dotenv()

# ── FastAPI (Render braucht einen laufenden Port) ──────────────
app = FastAPI()

@app.get("/")
async def root():
    return {"status": "ok", "bot": str(bot.user) if bot.is_ready() else "starting"}

@app.get("/health")
async def health():
    return {"status": "ok"}

def starte_webserver():
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")

async def keep_alive():
    import aiohttp
    url = os.getenv("RENDER_EXTERNAL_URL", "")
    if not url:
        return
    await asyncio.sleep(60)
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                await session.get(f"{url}/health")
                print("🏓 Keep-alive ping gesendet")
        except:
            pass
        await asyncio.sleep(300)

# ── MongoDB ────────────────────────────────────────────────────
mongo = AsyncIOMotorClient(os.getenv("MONGODB_URI"))
db = mongo[os.getenv("MONGODB_DB", "levelbot")]
users_col  = db["users"]
guilds_col = db["guilds"]
logs_col   = db["logs"]

# ── Konstanten ─────────────────────────────────────────────────
XP_NACHRICHT  = int(os.getenv("XP_NACHRICHT",  10))
XP_REAKTION   = int(os.getenv("XP_REAKTION",    5))
XP_VOICE_MIN  = int(os.getenv("XP_VOICE_MIN",   3))
COOLDOWN_SEK  = int(os.getenv("COOLDOWN_SEK",  60))
DAILY_XP      = int(os.getenv("DAILY_XP",     100))
STREAK_BONUS  = int(os.getenv("STREAK_BONUS",  20))

# ── XP Logik ──────────────────────────────────────────────────
def xp_fuer_level(lvl): return math.floor(100 * (lvl ** 1.5))

def berechne_level(xp):
    lvl = 0
    while xp >= xp_fuer_level(lvl + 1):
        xp -= xp_fuer_level(lvl + 1)
        lvl += 1
    return lvl

def xp_im_level(gesamt_xp):
    lvl, xp = 0, gesamt_xp
    while xp >= xp_fuer_level(lvl + 1):
        xp -= xp_fuer_level(lvl + 1)
        lvl += 1
    return xp, xp_fuer_level(lvl + 1)

# ── DB Helfer ──────────────────────────────────────────────────
async def hole_user(gid, uid):
    doc = await users_col.find_one({"guild_id": gid, "user_id": uid})
    if not doc:
        doc = {"guild_id": gid, "user_id": uid, "xp": 0, "level": 0,
               "last_xp": 0, "last_daily": None, "streak": 0, "invites": 0}
        await users_col.insert_one(doc)
    return doc

async def set_user(gid, uid, data):
    await users_col.update_one({"guild_id": gid, "user_id": uid}, {"$set": data}, upsert=True)

async def hole_config(gid):
    doc = await guilds_col.find_one({"guild_id": gid})
    if not doc:
        doc = {"guild_id": gid, "levelup_channel": None, "blacklist_channels": [],
               "role_rewards": {}, "xp_multiplier_roles": {}, "log_channel": None}
        await guilds_col.insert_one(doc)
    return doc

async def log(gid, uid, aktion, xp):
    await logs_col.insert_one({"guild_id": gid, "user_id": uid, "aktion": aktion,
                                "xp": xp, "ts": datetime.utcnow()})

# ── Bot ────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.reactions = True

bot = commands.Bot(command_prefix="?", intents=intents, help_command=None)
cooldowns = {}
voice_times = {}
invite_cache = {}

# ── Level-Up Handler ───────────────────────────────────────────
async def check_levelup(guild, member, old_lvl, new_lvl, cfg):
    if new_lvl <= old_lvl:
        return
    for lvl in range(old_lvl + 1, new_lvl + 1):
        rid = cfg.get("role_rewards", {}).get(str(lvl))
        if rid:
            r = guild.get_role(int(rid))
            if r:
                try: await member.add_roles(r, reason=f"Level {lvl}")
                except: pass

    embed = discord.Embed(title="🎉 Level Up!",
                          description=f"{member.mention} hat **Level {new_lvl}** erreicht!",
                          color=discord.Color.gold())
    embed.set_thumbnail(url=member.display_avatar.url)

    cid = cfg.get("levelup_channel")
    ch = guild.get_channel(int(cid)) if cid else None
    if ch:
        await ch.send(embed=embed)
    try:
        await member.send(embed=embed)
    except:
        pass

# ── Events ─────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ {bot.user} online")
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} Commands gesynced")
    except Exception as e:
        print(f"❌ Sync Fehler: {e}")
    voice_xp_loop.start()
    asyncio.ensure_future(keep_alive())
    for g in bot.guilds:
        try: invite_cache[g.id] = {i.code: i.uses for i in await g.invites()}
        except: pass
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name=f"{sum(g.member_count or 0 for g in bot.guilds)} User | /level"))

@bot.event
async def on_message(msg: discord.Message):
    if msg.author.bot or not msg.guild: return
    gid, uid = msg.guild.id, msg.author.id
    cfg = await hole_config(gid)
    if msg.channel.id in cfg.get("blacklist_channels", []):
        await bot.process_commands(msg); return
    key = f"{gid}:{uid}"
    now = time.time()
    if key in cooldowns and now - cooldowns[key] < COOLDOWN_SEK:
        await bot.process_commands(msg); return
    cooldowns[key] = now
    mult = max((float(cfg.get("xp_multiplier_roles", {}).get(str(r.id), 1)) for r in msg.author.roles), default=1.0)  # type: ignore[attr-defined]
    xp_gain = int(XP_NACHRICHT * mult)
    u = await hole_user(gid, uid)
    new_xp = u["xp"] + xp_gain
    new_lvl = berechne_level(new_xp)
    await set_user(gid, uid, {"xp": new_xp, "level": new_lvl, "last_xp": now})
    await log(gid, uid, "msg", xp_gain)
    await check_levelup(msg.guild, msg.author, u["level"], new_lvl, cfg)
    await bot.process_commands(msg)

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot or not reaction.message.guild: return
    emp = reaction.message.author
    if emp.bot: return
    gid = reaction.message.guild.id
    u = await hole_user(gid, emp.id)
    new_xp = u["xp"] + XP_REAKTION
    new_lvl = berechne_level(new_xp)
    cfg = await hole_config(gid)
    await set_user(gid, emp.id, {"xp": new_xp, "level": new_lvl})
    await log(gid, emp.id, "reaction", XP_REAKTION)
    m = reaction.message.guild.get_member(emp.id)
    if m: await check_levelup(reaction.message.guild, m, u["level"], new_lvl, cfg)

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot: return
    key = f"{member.guild.id}:{member.id}"
    if after.channel and not before.channel:
        voice_times[key] = time.time()
    elif not after.channel and before.channel and key in voice_times:
        mins = (time.time() - voice_times.pop(key)) / 60
        xp = int(mins * XP_VOICE_MIN)
        if xp > 0:
            u = await hole_user(member.guild.id, member.id)
            new_xp = u["xp"] + xp
            new_lvl = berechne_level(new_xp)
            cfg = await hole_config(member.guild.id)
            await set_user(member.guild.id, member.id, {"xp": new_xp, "level": new_lvl})
            await log(member.guild.id, member.id, "voice", xp)
            await check_levelup(member.guild, member, u["level"], new_lvl, cfg)

@bot.event
async def on_member_join(member):
    g = member.guild
    try:
        new_inv = {i.code: i.uses for i in await g.invites()}
        for code, uses in new_inv.items():
            if invite_cache.get(g.id, {}).get(code, 0) < uses:
                for inv in await g.invites():
                    if inv.code == code and inv.inviter:
                        u = await hole_user(g.id, inv.inviter.id)
                        new_xp = u["xp"] + 50
                        new_lvl = berechne_level(new_xp)
                        cfg = await hole_config(g.id)
                        await set_user(g.id, inv.inviter.id, {"xp": new_xp, "level": new_lvl, "invites": u.get("invites",0)+1})
                        await log(g.id, inv.inviter.id, "invite", 50)
                        im = g.get_member(inv.inviter.id)
                        if im: await check_levelup(g, im, u["level"], new_lvl, cfg)
                        break
        invite_cache[g.id] = new_inv
    except: pass

@tasks.loop(minutes=5)
async def voice_xp_loop():
    now = time.time()
    for key, jt in list(voice_times.items()):
        gid, uid = map(int, key.split(":"))
        xp = int(((now - jt) / 60) * XP_VOICE_MIN)
        if xp > 0:
            voice_times[key] = now
            u = await hole_user(gid, uid)
            new_xp = u["xp"] + xp
            new_lvl = berechne_level(new_xp)
            cfg = await hole_config(gid)
            await set_user(gid, uid, {"xp": new_xp, "level": new_lvl})
            g = bot.get_guild(gid)
            if g:
                m = g.get_member(uid)
                if m: await check_levelup(g, m, u["level"], new_lvl, cfg)

# ── Prefix Commands (?level, ?daily etc) ──────────────────────
async def send_level(ctx_or_interaction, ziel, gid):
    u = await hole_user(gid, ziel.id)
    cur, nxt = xp_im_level(u["xp"])
    bar = "█" * int(cur/nxt*20) + "░" * (20 - int(cur/nxt*20))
    e = discord.Embed(title=f"📊 {ziel.display_name}", color=discord.Color.blue())
    e.add_field(name="Level", value=str(u["level"]), inline=True)
    e.add_field(name="XP", value=str(u["xp"]), inline=True)
    e.add_field(name="🔥 Streak", value=str(u.get("streak", 0)), inline=True)
    e.add_field(name="Fortschritt", value=f"`{bar}` {cur}/{nxt}", inline=False)
    e.add_field(name="📨 Einladungen", value=str(u.get("invites", 0)), inline=True)
    e.set_thumbnail(url=ziel.display_avatar.url)
    return e

@bot.command(name="level")
async def p_level(ctx, user: discord.Member | None = None):
    ziel = user or ctx.author
    e = await send_level(ctx, ziel, ctx.guild.id)
    await ctx.send(embed=e)

@bot.command(name="rangliste")
async def p_rangliste(ctx, seite: int = 1):
    pp = 10
    skip = (seite-1)*pp
    entries = await users_col.find({"guild_id": ctx.guild.id}).sort("xp",-1).skip(skip).limit(pp).to_list(pp)
    total = await users_col.count_documents({"guild_id": ctx.guild.id})
    pages = max(1, math.ceil(total/pp))
    medals = ["🥇","🥈","🥉"]
    desc = ""
    for i, en in enumerate(entries):
        rang = skip+i+1
        prefix = medals[rang-1] if rang<=3 else f"**{rang}.**"
        try: name = (await bot.fetch_user(en["user_id"])).display_name
        except: name = f"User {en['user_id']}"
        desc += f"{prefix} {name} — Level {en['level']} ({en['xp']} XP)\n"
    e = discord.Embed(title=f"🏆 Rangliste – Seite {seite}/{pages}", description=desc or "Leer.", color=discord.Color.gold())
    await ctx.send(embed=e)

@bot.command(name="daily")
async def p_daily(ctx):
    u = await hole_user(ctx.guild.id, ctx.author.id)
    now = datetime.utcnow()
    last = u.get("last_daily")
    if last:
        last_dt = last if isinstance(last, datetime) else datetime.fromisoformat(str(last))
        diff = now - last_dt
        if diff < timedelta(hours=20):
            warte = timedelta(hours=20) - diff
            h, r = divmod(int(warte.total_seconds()), 3600)
            await ctx.send(f"⏰ Warte noch **{h}h {r//60}m**!"); return
        streak = u.get("streak",0)+1 if diff < timedelta(hours=48) else 1
    else:
        streak = 1
    bonus = STREAK_BONUS*(streak-1)
    total = DAILY_XP+bonus
    new_xp = u["xp"]+total
    new_lvl = berechne_level(new_xp)
    cfg = await hole_config(ctx.guild.id)
    await set_user(ctx.guild.id, ctx.author.id, {"xp": new_xp, "level": new_lvl, "last_daily": now, "streak": streak})
    await log(ctx.guild.id, ctx.author.id, "daily", total)
    m = ctx.guild.get_member(ctx.author.id)
    if m: await check_levelup(ctx.guild, m, u["level"], new_lvl, cfg)
    e = discord.Embed(title="✅ Daily!", description=f"**+{total} XP** | 🔥 Streak: **{streak}**{f' (+{bonus} Bonus)' if bonus else ''}", color=discord.Color.green())
    await ctx.send(embed=e)

@bot.command(name="stats")
async def p_stats(ctx):
    total_u = await users_col.count_documents({"guild_id": ctx.guild.id})
    res = await users_col.aggregate([
        {"$match": {"guild_id": ctx.guild.id}},
        {"$group": {"_id": None, "xp": {"$sum": "$xp"}, "max_lvl": {"$max": "$level"}}}
    ]).to_list(1)
    xp = res[0]["xp"] if res else 0
    ml = res[0]["max_lvl"] if res else 0
    e = discord.Embed(title="📈 Server-Stats", color=discord.Color.purple())
    e.add_field(name="👥 User", value=str(total_u), inline=True)
    e.add_field(name="⭐ XP gesamt", value=str(xp), inline=True)
    e.add_field(name="🏆 Max Level", value=str(ml), inline=True)
    await ctx.send(embed=e)

@bot.command(name="help")
async def p_help(ctx):
    e = discord.Embed(title="📖 Level Bot – Commands", color=discord.Color.blurple())
    e.add_field(name="👤 User Commands", value="""
`/level` oder `?level` – Dein Level, XP & Fortschritt
`/rangliste` oder `?rangliste` – Top-User nach XP
`/daily` oder `?daily` – Täglicher XP-Bonus
`/stats` oder `?stats` – Serverweite Statistiken
`/help` oder `?help` – Diese Übersicht
""", inline=False)
    e.add_field(name="⚙️ Admin Commands", value="""
`/xp-add @user menge` – XP hinzufügen
`/xp-remove @user menge` – XP entfernen
`/level-set @user level` – Level setzen
`/level-reset @user` – User zurücksetzen
`/server-reset` – Alle XP löschen
`/levelup-kanal #kanal` – Level-Up Kanal
`/blacklist-kanal #kanal` – Kein XP Kanal
`/rolle-bei-level level @rolle` – Rolle bei Level
`/xp-multiplikator @rolle 2.0` – XP Boost
""", inline=False)
    e.add_field(name="⭐ XP-Quellen", value="💬 Nachrichten · 🎤 Sprachkanal · 👍 Reaktionen · 📨 Einladungen (+50 XP)", inline=False)
    e.set_footer(text="Tipp: /daily jeden Tag holen für den Streak-Bonus!")
    await ctx.send(embed=e)

# ── Slash Commands ─────────────────────────────────────────────
@bot.tree.command(name="level", description="Zeigt dein Level und XP.")
async def level_cmd(interaction: discord.Interaction, user: discord.Member | None = None):
    ziel = user or interaction.user
    e = await send_level(interaction, ziel, interaction.guild_id)
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="rangliste", description="Top-User nach XP (mit Seiten).")
async def rangliste_cmd(interaction: discord.Interaction, seite: int = 1):
    pp = 10
    skip = (seite-1)*pp
    entries = await users_col.find({"guild_id": interaction.guild_id}).sort("xp",-1).skip(skip).limit(pp).to_list(pp)
    total = await users_col.count_documents({"guild_id": interaction.guild_id})
    pages = max(1, math.ceil(total/pp))
    medals = ["🥇","🥈","🥉"]
    desc = ""
    for i, en in enumerate(entries):
        rang = skip+i+1
        prefix = medals[rang-1] if rang<=3 else f"**{rang}.**"
        try: name = (await bot.fetch_user(en["user_id"])).display_name
        except: name = f"User {en['user_id']}"
        desc += f"{prefix} {name} — Level {en['level']} ({en['xp']} XP)\n"
    e = discord.Embed(title=f"🏆 Rangliste – Seite {seite}/{pages}", description=desc or "Leer.", color=discord.Color.gold())
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="daily", description="Täglicher XP-Bonus.")
async def daily_cmd(interaction: discord.Interaction):
    u = await hole_user(interaction.guild_id, interaction.user.id)
    now = datetime.utcnow()
    last = u.get("last_daily")
    if last:
        last_dt = last if isinstance(last, datetime) else datetime.fromisoformat(str(last))
        diff = now - last_dt
        if diff < timedelta(hours=20):
            warte = timedelta(hours=20) - diff
            h, r = divmod(int(warte.total_seconds()), 3600)
            await interaction.response.send_message(f"⏰ Warte noch **{h}h {r//60}m**!", ephemeral=True); return
        streak = u.get("streak",0)+1 if diff < timedelta(hours=48) else 1
    else:
        streak = 1
    bonus = STREAK_BONUS*(streak-1)
    total = DAILY_XP+bonus
    new_xp = u["xp"]+total
    new_lvl = berechne_level(new_xp)
    cfg = await hole_config(interaction.guild_id)
    await set_user(interaction.guild_id, interaction.user.id, {"xp": new_xp, "level": new_lvl, "last_daily": now, "streak": streak})
    await log(interaction.guild_id, interaction.user.id, "daily", total)
    if interaction.guild:
        m = interaction.guild.get_member(interaction.user.id)
        if m: await check_levelup(interaction.guild, m, u["level"], new_lvl, cfg)
    e = discord.Embed(title="✅ Daily!", description=f"**+{total} XP** | 🔥 Streak: **{streak}**{f' (+{bonus} Bonus)' if bonus else ''}", color=discord.Color.green())
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="stats", description="Serverweite XP-Statistiken.")
async def stats_cmd(interaction: discord.Interaction):
    total_u = await users_col.count_documents({"guild_id": interaction.guild_id})
    res = await users_col.aggregate([
        {"$match": {"guild_id": interaction.guild_id}},
        {"$group": {"_id": None, "xp": {"$sum": "$xp"}, "max_lvl": {"$max": "$level"}}}
    ]).to_list(1)
    xp = res[0]["xp"] if res else 0
    ml = res[0]["max_lvl"] if res else 0
    e = discord.Embed(title="📈 Server-Stats", color=discord.Color.purple())
    e.add_field(name="👥 User", value=str(total_u), inline=True)
    e.add_field(name="⭐ XP gesamt", value=str(xp), inline=True)
    e.add_field(name="🏆 Max Level", value=str(ml), inline=True)
    await interaction.response.send_message(embed=e)

# ── Admin ──────────────────────────────────────────────────────
def admin_check():
    async def pred(i): return i.user.guild_permissions.administrator
    return app_commands.check(pred)

@bot.tree.command(name="xp-add", description="[Admin] XP hinzufügen.")
@admin_check()
async def xp_add(i: discord.Interaction, user: discord.Member, menge: int):
    u = await hole_user(i.guild_id, user.id)
    nx = u["xp"]+menge; nl = berechne_level(nx)
    cfg = await hole_config(i.guild_id)
    await set_user(i.guild_id, user.id, {"xp": nx, "level": nl})
    await log(i.guild_id, user.id, "admin_add", menge)
    await check_levelup(i.guild, user, u["level"], nl, cfg)
    await i.response.send_message(f"✅ +{menge} XP für {user.mention}. Gesamt: {nx}")

@bot.tree.command(name="xp-remove", description="[Admin] XP entfernen.")
@admin_check()
async def xp_remove(i: discord.Interaction, user: discord.Member, menge: int):
    u = await hole_user(i.guild_id, user.id)
    nx = max(0, u["xp"]-menge); nl = berechne_level(nx)
    await set_user(i.guild_id, user.id, {"xp": nx, "level": nl})
    await log(i.guild_id, user.id, "admin_remove", -menge)
    await i.response.send_message(f"✅ -{menge} XP von {user.mention}. Gesamt: {nx}")

@bot.tree.command(name="level-set", description="[Admin] Level setzen.")
@admin_check()
async def level_set(i: discord.Interaction, user: discord.Member, level: int):
    xp = sum(xp_fuer_level(l+1) for l in range(level))
    await set_user(i.guild_id, user.id, {"xp": xp, "level": level})
    await i.response.send_message(f"✅ {user.mention} → Level {level}")

@bot.tree.command(name="level-reset", description="[Admin] User zurücksetzen.")
@admin_check()
async def level_reset(i: discord.Interaction, user: discord.Member):
    await set_user(i.guild_id, user.id, {"xp": 0, "level": 0, "streak": 0, "invites": 0})
    await i.response.send_message(f"✅ {user.mention} wurde zurückgesetzt.")

@bot.tree.command(name="server-reset", description="[Admin] Alle XP zurücksetzen.")
@admin_check()
async def server_reset(i: discord.Interaction, bestaetigung: str):
    if bestaetigung != "JA ICH BIN SICHER":
        await i.response.send_message("❌ Schreib `JA ICH BIN SICHER` als Bestätigung.", ephemeral=True); return
    await users_col.delete_many({"guild_id": i.guild_id})
    await i.response.send_message("✅ Alle Daten gelöscht.")

@bot.tree.command(name="levelup-kanal", description="[Admin] Level-Up Kanal setzen.")
@admin_check()
async def levelup_kanal(i: discord.Interaction, kanal: discord.TextChannel):
    await guilds_col.update_one({"guild_id": i.guild_id}, {"$set": {"levelup_channel": kanal.id}}, upsert=True)
    await i.response.send_message(f"✅ Level-Ups → {kanal.mention}")

@bot.tree.command(name="blacklist-kanal", description="[Admin] Kanal ohne XP.")
@admin_check()
async def blacklist_kanal(i: discord.Interaction, kanal: discord.TextChannel):
    await guilds_col.update_one({"guild_id": i.guild_id}, {"$addToSet": {"blacklist_channels": kanal.id}}, upsert=True)
    await i.response.send_message(f"✅ {kanal.mention} ist jetzt auf der Blacklist.")

@bot.tree.command(name="rolle-bei-level", description="[Admin] Rolle für Level vergeben.")
@admin_check()
async def rolle_bei_level(i: discord.Interaction, level: int, rolle: discord.Role):
    await guilds_col.update_one({"guild_id": i.guild_id}, {"$set": {f"role_rewards.{level}": rolle.id}}, upsert=True)
    await i.response.send_message(f"✅ Bei Level {level} → {rolle.mention}")

@bot.tree.command(name="xp-multiplikator", description="[Admin] XP-Multiplikator für Rolle.")
@admin_check()
async def xp_mult(i: discord.Interaction, rolle: discord.Role, multiplikator: float):
    await guilds_col.update_one({"guild_id": i.guild_id}, {"$set": {f"xp_multiplier_roles.{rolle.id}": multiplikator}}, upsert=True)
    await i.response.send_message(f"✅ {rolle.mention} → {multiplikator}x XP")

@bot.tree.command(name="help", description="Zeigt alle Commands.")
async def help_cmd(interaction: discord.Interaction):
    e = discord.Embed(title="📖 Level Bot – Commands", color=discord.Color.blurple())
    e.add_field(name="👤 User Commands", value="""
`/level` oder `?level` – Dein Level, XP & Fortschritt
`/rangliste` oder `?rangliste` – Top-User nach XP
`/daily` oder `?daily` – Täglicher XP-Bonus
`/stats` oder `?stats` – Serverweite Statistiken
`/help` oder `?help` – Diese Übersicht
""", inline=False)
    e.add_field(name="⚙️ Admin Commands", value="""
`/xp-add @user menge` – XP hinzufügen
`/xp-remove @user menge` – XP entfernen
`/level-set @user level` – Level setzen
`/level-reset @user` – User zurücksetzen
`/server-reset` – Alle XP löschen
`/levelup-kanal #kanal` – Level-Up Kanal
`/blacklist-kanal #kanal` – Kein XP Kanal
`/rolle-bei-level level @rolle` – Rolle bei Level
`/xp-multiplikator @rolle 2.0` – XP Boost
""", inline=False)
    e.add_field(name="⭐ XP-Quellen", value="💬 Nachrichten · 🎤 Sprachkanal · 👍 Reaktionen · 📨 Einladungen (+50 XP)", inline=False)
    e.set_footer(text="Tipp: /daily jeden Tag holen für den Streak-Bonus!")
    await interaction.response.send_message(embed=e)

# ── Error Handler & Debug ─────────────────────────────────────
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    import traceback
    cmd_name = interaction.command.name if interaction.command else "unbekannt"
    tb = traceback.format_exc()
    err_str = str(error)
    user_str = str(interaction.user)
    user_id = interaction.user.id
    guild_str = str(interaction.guild)
    guild_id = interaction.guild_id
    print("❌ SLASH CMD FEHLER [" + cmd_name + "]")
    print("   User: " + user_str + " (" + str(user_id) + ")")
    print("   Guild: " + guild_str + " (" + str(guild_id) + ")")
    print("   Fehler: " + err_str)
    print("   Traceback:\n" + tb)
    if isinstance(error, app_commands.CheckFailure):
        msg = "❌ Du hast keine Berechtigung für diesen Command!"
    else:
        msg = "❌ Fehler: `" + err_str + "`"
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except:
        pass

@bot.event
async def on_command_error(ctx, error):
    import traceback
    tb = traceback.format_exc()
    err_str = str(error)
    print("❌ PREFIX CMD FEHLER [" + str(ctx.command) + "]")
    print("   User: " + str(ctx.author) + " (" + str(ctx.author.id) + ")")
    print("   Fehler: " + err_str)
    print("   Traceback:\n" + tb)
    if isinstance(error, commands.CommandNotFound):
        return
    await ctx.send("❌ Fehler: `" + err_str + "`")

# ── Start ──────────────────────────────────────────────────────
async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token: raise ValueError("DISCORD_TOKEN fehlt!")
    threading.Thread(target=starte_webserver, daemon=True).start()
    await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())