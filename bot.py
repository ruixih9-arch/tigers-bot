import os
import threading
import discord
from discord.ext import commands, tasks
import requests
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

# ----------------- Render 免費 Web Service 活體檢測 -----------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# 在背景啟動 Web 伺服器
threading.Thread(target=run_web_server, daemon=True).start()
# ------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

TIGERS_TEAM_ID = 116

# ⚠️ 請將這裡改為你的 Discord 頻道 ID
CHANNEL_ID = 1553769867331633172  

US_EAST_TZ = timezone(timedelta(hours=-4))
TW_TZ = timezone(timedelta(hours=8))

last_notified_game_pk = None

def get_tw_time_str():
    return datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S")

def get_tigers_lineup():
    us_today = datetime.now(US_EAST_TZ).strftime("%Y-%m-%d")
    schedule_url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId={TIGERS_TEAM_ID}&date={us_today}"
    
    try:
        res = requests.get(schedule_url).json()
        dates = res.get("dates", [])
        
        if not dates or not dates[0].get("games"):
            return {"error": "今天老虎隊沒有比賽！"}
        
        game = dates[0]["games"][0]
        game_pk = game["gamePk"]
        
        game_utc_time = datetime.strptime(game["gameDate"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        game_tw_time = game_utc_time.astimezone(TW_TZ).strftime("%Y-%m-%d %H:%M")

        game_url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
        game_data = requests.get(game_url).json()
        
        boxscore = game_data.get("liveData", {}).get("boxscore", {})
        teams = boxscore.get("teams", {})
        
        is_home = teams.get("home", {}).get("team", {}).get("id") == TIGERS_TEAM_ID
        tigers_data = teams.get("home") if is_home else teams.get("away")
        opponent_data = teams.get("away") if is_home else teams.get("home")
        
        opponent_name = opponent_data.get("team", {}).get("name", "對手")
        match_type = "VS" if is_home else "@"
        
        batting_order = tigers_data.get("battingOrder", [])
        players = tigers_data.get("players", {})
        
        if not batting_order:
            return {
                "status": "pending",
                "game_pk": game_pk,
                "title": f"底特律老虎 {match_type} {opponent_name}",
                "game_time": game_tw_time,
                "msg": "官方尚未公布今日先發陣容，請稍後再試！"
            }
        
        lineup_list = []
        for idx, player_id in enumerate(batting_order, 1):
            p_key = f"ID{player_id}"
            player = players.get(p_key, {})
            name = player.get("person", {}).get("fullName", "未知球員")
            
            pos_data = player.get("selectedPosition") or player.get("primaryPosition") or player.get("position") or {}
            pos = pos_data.get("abbreviation", "–")
            
            lineup_list.append(f"**{idx}.** {name} ({pos})")
        
        pitchers = tigers_data.get("pitchers", [])
        sp_name = "尚未確定"
        if pitchers:
            sp_id = f"ID{pitchers[0]}"
            sp_name = players.get(sp_id, {}).get("person", {}).get("fullName", "未知投手")

        return {
            "status": "success",
            "game_pk": game_pk,
            "title": f"🐅 底特律老虎 {match_type} {opponent_name}",
            "game_time": game_tw_time,
            "sp": sp_name,
            "lineup": "\n".join(lineup_list)
        }
        
    except Exception as e:
        return {"error": f"資料抓取失敗：{str(e)}"}

@tasks.loop(minutes=15)
async def auto_check_lineup():
    global last_notified_game_pk
    
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return
        
    data = get_tigers_lineup()
    
    if data.get("status") == "success":
        current_game_pk = data.get("game_pk")
        
        if current_game_pk != last_notified_game_pk:
            embed = discord.Embed(
                title=data["title"],
                color=discord.Color.blue()
            )
            embed.add_field(name="⏰ 比賽時間", value=f"{data['game_time']} (台灣時間)", inline=False)
            embed.add_field(name="⚾ 今日先發投手", value=data["sp"], inline=False)
            embed.add_field(name="📋 先發打線", value=data["lineup"], inline=False)
            embed.set_footer(text="資料來源：MLB Official API")
            
            await channel.send(embed=embed)
            
            last_notified_game_pk = current_game_pk

@bot.event
async def on_ready():
    print(f"[{get_tw_time_str()} 台灣時間] 機器人已成功登入為 {bot.user}")
    if not auto_check_lineup.is_running():
        auto_check_lineup.start()

@bot.command(name="lineup")
async def lineup(ctx):
    data = get_tigers_lineup()
    if "error" in data:
        await ctx.send(data["error"])
        return
    
    embed = discord.Embed(title=data["title"], color=discord.Color.blue())
    if data.get("status") == "pending":
        embed.add_field(name="⏰ 比賽時間", value=f"{data['game_time']} (台灣時間)", inline=False)
        embed.description = data["msg"]
    else:
        embed.add_field(name="⏰ 比賽時間", value=f"{data['game_time']} (台灣時間)", inline=False)
        embed.add_field(name="⚾ 今日先發投手", value=data["sp"], inline=False)
        embed.add_field(name="📋 先發打線", value=data["lineup"], inline=False)
    
    embed.set_footer(text="資料來源：MLB Official API")
    await ctx.send(embed=embed)

TOKEN = os.environ.get("DISCORD_TOKEN") or "YOUR_TOKEN_HERE"
bot.run(TOKEN)