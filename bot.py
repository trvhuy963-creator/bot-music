import asyncio
import os
import re
import traceback
from collections import deque

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp

load_dotenv()
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
COMMAND_PREFIX = "!"
EMBED_COLOR = 0x1DB954
BOT_STATUS = "/bé bo"

# ========== CẤU HÌNH YT-DLP ==========
YTDL_OPTIONS = {
    "format": "best",  # Tải video+audio, FFmpeg tự tách âm thanh
    "noplaylist": False,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "cookiefile": "cookies.txt",
    "http_headers": {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.youtube.com/",
    },
    "extractor_args": {
        "youtube": {
            "player_client": ["web", "android"],
        }
    },
    "retries": 5,
    "fragment_retries": 5,
    "skip_unavailable_fragments": True,
}

FFMPEG_OPTIONS = {
    "before_options": (
        "-reconnect 1 "
        "-reconnect_streamed 1 "
        "-reconnect_delay_max 5 "
        "-hide_banner "
        "-loglevel error"
    ),
    "options": "-vn -bufsize 512k",  # -vn để bỏ video stream, chỉ phát âm thanh
}


class YTDLSource(discord.PCMVolumeTransformer):
    ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title", "Unknown")
        self.url = data.get("webpage_url", "")
        self.duration = data.get("duration", 0)
        self.thumbnail = data.get("thumbnail", "")
        self.uploader = data.get("uploader", "Unknown")

    @classmethod
    async def from_url(cls, url, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, lambda: cls.ytdl.extract_info(url, download=False)
        )
        if data is None:
            raise ValueError("Không thể lấy thông tin bài hát.")
        if "entries" in data:
            entries = [e for e in data["entries"] if e]
            if not entries:
                raise ValueError("Playlist trống.")
            return [cls._make(e) for e in entries]
        return [cls._make(data)]

    @classmethod
    def _make(cls, data):
        return cls(
            discord.FFmpegPCMAudio(data["url"], **FFMPEG_OPTIONS),
            data=data,
        )

    @staticmethod
    def fmt_dur(sec):
        if not sec:
            return "Live"
        m, s = divmod(int(sec), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class MusicPlayer:
    def __init__(self, guild_id):
        self.guild_id = guild_id
        self.queue = deque()
        self.current = None
        self.loop = False
        self.loop_queue = False
        self.volume = 0.5

    def add(self, sources):
        self.queue.extend(sources)

    def next(self):
        if self.loop and self.current:
            return self.current
        if self.loop_queue and self.current:
            self.queue.append(self.current)
        if self.queue:
            self.current = self.queue.popleft()
            return self.current
        self.current = None
        return None

    def clear(self):
        self.queue.clear()
        self.current = None


class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.players = {}

    def get_player(self, guild_id):
        if guild_id not in self.players:
            self.players[guild_id] = MusicPlayer(guild_id)
        return self.players[guild_id]

    def _after(self, guild, error=None):
        if error:
            print(f"[ERROR] {error}")
        player = self.get_player(guild.id)
        source = player.next()
        if source and guild.voice_client and guild.voice_client.is_connected():
            guild.voice_client.play(source, after=lambda e: self._after(guild, e))
            guild.voice_client.source.volume = player.volume

    @app_commands.command(name="play", description="Phát nhạc từ link hoặc tên bài")
    @app_commands.describe(query="Link YouTube hoặc tên bài hát")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer(thinking=True)

        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.followup.send(
                embed=discord.Embed(description="Bạn cần vào kênh thoại trước!", color=0xFF4444)
            )

        vc_channel = interaction.user.voice.channel
        guild = interaction.guild
        vc = guild.voice_client

        try:
            if vc is None:
                vc = await vc_channel.connect(timeout=15, reconnect=True)
            elif vc.channel != vc_channel:
                await vc.move_to(vc_channel)
        except Exception as e:
            return await interaction.followup.send(
                embed=discord.Embed(description=f"Lỗi kết nối: {e}", color=0xFF4444)
            )

        player = self.get_player(guild.id)

        if not re.match(r"https?://", query):
            query = f"ytsearch:{query}"

        try:
            sources = await YTDLSource.from_url(query, loop=self.bot.loop)
        except yt_dlp.utils.DownloadError as e:
            msg = str(e)
            if "403" in msg or "Sign in" in msg:
                tip = "🔒 YouTube yêu cầu xác thực. Kiểm tra lại file cookies.txt."
            elif "Private" in msg:
                tip = "Video này bị đặt chế độ riêng tư."
            else:
                tip = f"Không tải được: {msg[:200]}"
            return await interaction.followup.send(
                embed=discord.Embed(description=tip, color=0xFF4444)
            )
        except Exception as e:
            return await interaction.followup.send(
                embed=discord.Embed(description=f"Lỗi: {e}", color=0xFF4444)
            )

        player.add(sources)

        if not vc.is_playing() and not vc.is_paused():
            source = player.next()
            if source:
                vc.play(source, after=lambda e: self._after(guild, e))
                vc.source.volume = player.volume
                embed = discord.Embed(
                    title="🎶 Now Playing",
                    description=f"[{source.title}]({source.url})",
                    color=EMBED_COLOR,
                )
                embed.add_field(name="⏱ Thời lượng", value=YTDLSource.fmt_dur(source.duration))
                embed.add_field(name="📢 Kênh", value=source.uploader)
                if source.thumbnail:
                    embed.set_thumbnail(url=source.thumbnail)
                embed.set_footer(text=f"Yêu cầu bởi {interaction.user.display_name}")
                return await interaction.followup.send(embed=embed)

        added = sources[0]
        embed = discord.Embed(
            title="✅ Đã thêm vào hàng chờ",
            description=f"[{added.title}]({added.url})",
            color=EMBED_COLOR,
        )
        embed.add_field(name="⏱ Thời lượng", value=YTDLSource.fmt_dur(added.duration))
        embed.add_field(name="📌 Vị trí", value=f"#{len(player.queue)}")
        if len(sources) > 1:
            embed.add_field(name="📋 Playlist", value=f"Đã thêm {len(sources)} bài", inline=False)
        if added.thumbnail:
            embed.set_thumbnail(url=added.thumbnail)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="join", description="Bot tham gia kênh thoại của bạn")
    async def join(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message(
                embed=discord.Embed(description="Bạn cần vào kênh thoại trước!", color=0xFF4444), ephemeral=True
            )
        vc_channel = interaction.user.voice.channel
        guild = interaction.guild
        vc = guild.voice_client
        try:
            if vc is None:
                await vc_channel.connect(timeout=15, reconnect=True)
                await interaction.response.send_message(embed=discord.Embed(description="✅ Bot đã tham gia kênh thoại!", color=EMBED_COLOR))
            elif vc.channel != vc_channel:
                await vc.move_to(vc_channel)
                await interaction.response.send_message(embed=discord.Embed(description="✅ Bot đã chuyển sang kênh của bạn!", color=EMBED_COLOR))
            else:
                await interaction.response.send_message(embed=discord.Embed(description="Bot đã ở trong kênh thoại của bạn rồi.", color=EMBED_COLOR), ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(embed=discord.Embed(description=f"Lỗi khi join: {e}", color=0xFF4444), ephemeral=True)

    @app_commands.command(name="loop", description="Bật/tắt lặp lại bài hiện tại")
    async def loop(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild.id)
        player.loop = not player.loop
        if player.loop:
            player.loop_queue = False
        status = "🔁 Đã bật treo bài hiện tại" if player.loop else "❌ Đã tắt treo bài"
        await interaction.response.send_message(embed=discord.Embed(description=status, color=EMBED_COLOR))

    @app_commands.command(name="loopqueue", description="Bật/tắt lặp toàn bộ hàng chờ")
    async def loopqueue(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild.id)
        player.loop_queue = not player.loop_queue
        if player.loop_queue:
            player.loop = False
        status = "🔁 Đã bật treo hàng chờ" if player.loop_queue else "❌ Đã tắt treo hàng chờ"
        await interaction.response.send_message(embed=discord.Embed(description=status, color=EMBED_COLOR))

    @app_commands.command(name="skip", description="Bỏ qua bài hiện tại")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc or not vc.is_playing():
            return await interaction.response.send_message(embed=discord.Embed(description="Không có bài nào đang phát.", color=0xFF4444), ephemeral=True)
        vc.stop()
        await interaction.response.send_message(embed=discord.Embed(description="⏭ Đã skip!", color=EMBED_COLOR))

    @app_commands.command(name="stop", description="Dừng nhạc và rời kênh")
    async def stop(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild.id)
        player.clear()
        vc = interaction.guild.voice_client
        if vc:
            vc.stop()
            await vc.disconnect()
        await interaction.response.send_message(embed=discord.Embed(description="⏹ Đã dừng và rời kênh.", color=EMBED_COLOR))

    @app_commands.command(name="pause", description="Tạm dừng nhạc")
    async def pause(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await interaction.response.send_message(embed=discord.Embed(description="⏸ Đã tạm dừng.", color=EMBED_COLOR))
        else:
            await interaction.response.send_message(embed=discord.Embed(description="Không có gì đang phát.", color=0xFF4444), ephemeral=True)

    @app_commands.command(name="resume", description="Tiếp tục phát nhạc")
    async def resume(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await interaction.response.send_message(embed=discord.Embed(description="▶ Đã tiếp tục!", color=EMBED_COLOR))
        else:
            await interaction.response.send_message(embed=discord.Embed(description="Bot không đang tạm dừng.", color=0xFF4444), ephemeral=True)

    @app_commands.command(name="queue", description="Xem hàng chờ")
    async def queue_cmd(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild.id)
        embed = discord.Embed(title="📋 Hàng chờ", color=EMBED_COLOR)
        if player.current:
            loop_status = ""
            if player.loop:
                loop_status = " | 🔁 Treo bài"
            elif player.loop_queue:
                loop_status = " | 🔁 Treo hàng chờ"
            embed.add_field(name="🎶 Đang phát", value=f"[{player.current.title}]({player.current.url}) `{YTDLSource.fmt_dur(player.current.duration)}`{loop_status}", inline=False)
        if player.queue:
            lines = []
            for i, s in enumerate(list(player.queue)[:15], 1):
                lines.append(f"`{i}.` [{s.title}]({s.url}) `{YTDLSource.fmt_dur(s.duration)}`")
            if len(player.queue) > 15:
                lines.append(f"...và {len(player.queue) - 15} bài nữa")
            embed.add_field(name="⏩ Tiếp theo", value="\n".join(lines), inline=False)
        if not player.current and not player.queue:
            embed.description = "Hàng chờ trống."
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="volume", description="Chỉnh âm lượng (0-200)")
    @app_commands.describe(level="Âm lượng từ 0 đến 200")
    async def volume(self, interaction: discord.Interaction, level: int):
        if not (0 <= level <= 200):
            return await interaction.response.send_message(embed=discord.Embed(description="Âm lượng phải từ 0 đến 200.", color=0xFF4444), ephemeral=True)
        player = self.get_player(interaction.guild.id)
        player.volume = level / 100
        vc = interaction.guild.voice_client
        if vc and vc.source:
            vc.source.volume = player.volume
        await interaction.response.send_message(embed=discord.Embed(description=f"🔊 Âm lượng: {level}%", color=EMBED_COLOR))

    @app_commands.command(name="nowplaying", description="Xem bài đang phát")
    async def nowplaying(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild.id)
        if not player.current:
            return await interaction.response.send_message(embed=discord.Embed(description="Không có bài nào đang phát.", color=0xFF4444), ephemeral=True)
        s = player.current
        embed = discord.Embed(title="🎵 Đang phát", description=f"[{s.title}]({s.url})", color=EMBED_COLOR)
        embed.add_field(name="⏱ Thời lượng", value=YTDLSource.fmt_dur(s.duration))
        embed.add_field(name="📢 Kênh", value=s.uploader)
        if player.loop:
            embed.add_field(name="🔄 Loop", value="Treo bài hiện tại", inline=False)
        elif player.loop_queue:
            embed.add_field(name="🔄 Loop", value="Treo hàng chờ", inline=False)
        if s.thumbnail:
            embed.set_thumbnail(url=s.thumbnail)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leave", description="Bot rời kênh thoại")
    async def leave(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc:
            self.get_player(interaction.guild.id).clear()
            await vc.disconnect()
        await interaction.response.send_message(embed=discord.Embed(description="👋 Đã rời kênh.", color=EMBED_COLOR))


intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)


@bot.event
async def on_ready():
    print(f"✅ Bot đã online: {bot.user}")
    try:
        await bot.add_cog(MusicCog(bot))
        synced = await bot.tree.sync()
        print(f"📌 Đã đồng bộ {len(synced)} slash commands.")
    except Exception as e:
        print(f"❌ Lỗi đồng bộ: {e}")
        traceback.print_exc()

    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.listening, name=BOT_STATUS)
    )


if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ Thiếu DISCORD_TOKEN trong file .env!")
        exit(1)
    bot.run(BOT_TOKEN)