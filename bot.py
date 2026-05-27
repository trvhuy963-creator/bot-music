import discord
from discord.ext import commands
import datetime
import os
import zoneinfo

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

TOKEN = os.getenv("TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", 0))

VN_TZ = zoneinfo.ZoneInfo("Asia/Ho_Chi_Minh")

@bot.event
async def on_ready():
    guild = bot.get_guild(GUILD_ID)
    server_name = guild.name if guild else "Unknown Server"
    print(f"✅ Bot đã online trên server: {server_name}")
    print(f"   Guild ID: {GUILD_ID}")
    if GUILD_ID == 0:
        print("⚠️ Chưa set GUILD_ID! Bot sẽ không hoạt động đúng.")

@bot.event
async def on_voice_state_update(member, before, after):
    if GUILD_ID == 0 or member.guild.id != GUILD_ID:
        return

    now = datetime.datetime.now(VN_TZ)
    time_str = now.strftime("%H:%M")
    footer_text = f".gg/hassta • {time_str}"

    if before.channel is None and after.channel:        # Vào voice
        embed = discord.Embed(
            title="🔊 Tham Gia Voice",
            description=f"{member.mention} **đã tham gia** {after.channel.mention}",
            color=0x00ff00
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=footer_text)
        
        try:
            await after.channel.send(embed=embed)
            print(f"✅ [JOIN] {member.name} → {after.channel.name}")
        except:
            pass

    elif before.channel and after.channel is None:      # Rời voice
        embed = discord.Embed(
            title="🔇 Rời Voice",
            description=f"{member.mention} **đã rời** {before.channel.mention}",
            color=0xff0000
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=footer_text)
        
        try:
            await before.channel.send(embed=embed)
            print(f"✅ [LEAVE] {member.name} ← {before.channel.name}")
        except:
            pass


if not TOKEN:
    print("❌ Lỗi: Không tìm thấy TOKEN!")
else:
    bot.run(TOKEN)