import discord
from discord.ext import commands, tasks
import aiohttp
import os
import json
import logging
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Configure logging
logging.basicConfig(level=logging.INFO)

intents = discord.Intents.all()
client = commands.Bot(command_prefix="B!", intents=intents)

# Store the currently looping surah and looping status
looping_surahs = {}

@client.event
async def on_ready():
    await client.change_presence(activity=discord.Game(name="🌲linktr.ee/Stying"))
    await client.tree.sync()
    logging.info(f'We have logged in as {client.user.name}')
    if not check_looping.is_running():
        check_looping.start()

# Load Quran chapters data
with open("Quran_chapters.json", "r") as file:
    quran_chapters = json.load(file)

async def get_audio_surah_url(surah_number, edition="ar.alafasy", bitrate="128"):
    return f"https://cdn.islamic.network/quran/audio-surah/{bitrate}/{edition}/{surah_number}.mp3"

async def get_quran_data(chapter_number):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.alquran.cloud/v1/surah/{chapter_number}/en.asad") as response:
            if response.status == 200:
                return await response.json()
            else:
                logging.error(f"Error fetching Quran data: {response.status}")
                return None

ffmpeg_options = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 'options': '-vn'}

class QuranReadingView(discord.ui.View):
    def __init__(self):
        super().__init__()
        chapter_groups = [
            list(quran_chapters.items())[i:i + 25] for i in range(0, 114, 25)
        ]
        for group in chapter_groups:
            self.add_item(QuranReadingSelect(group))

class QuranListeningView(discord.ui.View):
    def __init__(self):
        super().__init__()
        chapter_groups = [
            list(quran_chapters.items())[i:i + 25] for i in range(0, 114, 25)
        ]
        for group in chapter_groups:
            self.add_item(QuranListeningSelect(group))

class QuranReadingSelect(discord.ui.Select):
    def __init__(self, chapters):
        options = [
            discord.SelectOption(label=f"{chapter_number}: {chapter_name}", value=str(chapter_number))
            for chapter_number, chapter_name in chapters
        ]
        super().__init__(placeholder="Select a Chapter to Read", options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_value = int(interaction.data["values"][0])
        
        if 1 <= selected_value <= 114:
            data = await get_quran_data(selected_value)
            chapter_name = data["data"]["name"]
            verses = data["data"]["ayahs"]

            # Extract and concatenate verses
            verse_texts = [f"{verse['text']} ({verse['numberInSurah']})" for verse in verses]
            verse_text = "\n".join(verse_texts)

            # Split verses into messages based on Discord's character limit
            messages = []

            while verse_text:
                message_part = verse_text[:1985]  # 2000 - 15 for the "**Chapter**" text
                split_index = message_part.rfind('\n')
                
                if split_index != -1:
                    message_part = message_part[:split_index].strip()
                    verse_text = verse_text[split_index:].strip()
                else:
                    verse_text = ""

                messages.append(message_part)

            # Send the messages
            for i, message in enumerate(messages):
                if i == 0:
                    await interaction.response.send_message(content=f"**Chapter {chapter_name}**\n\n**Verses:**\n{message}", ephemeral=True)
                else:
                    await interaction.followup.send(content=message, ephemeral=True)
        else:
            await interaction.response.send_message(content="Invalid selection.", ephemeral=True)

class QuranListeningSelect(discord.ui.Select):
    def __init__(self, chapters):
        options = [
            discord.SelectOption(label=f"{chapter_number}: {chapter_name}", value=str(chapter_number))
            for chapter_number, chapter_name in chapters
        ]
        super().__init__(placeholder="Select a Chapter to Listen", options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_surah_number = int(interaction.data["values"][0])
        audio_url = await get_audio_surah_url(selected_surah_number)
        
        voice_state = interaction.user.voice
        guild = interaction.guild
        
        if voice_state and voice_state.channel:
            voice_client = guild.voice_client
            
            if voice_client:  # If bot is already connected to a voice channel
                voice_client.stop()  # Stop the current audio playback
                voice_client.play(discord.FFmpegOpusAudio(audio_url, **ffmpeg_options))  # Play the new surah with ffmpeg_options
                chapter_name = [chapter_name for chapter_number, chapter_name in quran_chapters.items() if chapter_number == str(selected_surah_number)][0]
                await interaction.response.send_message(content=f"Playing {chapter_name}...", ephemeral=True)
                looping_surahs[guild.id] = (voice_client, audio_url, False)  # Save looping info with looping status
            else:  # If bot is not connected to a voice channel
                await voice_state.channel.connect()  # Connect to the user's voice channel
                voice_client = guild.voice_client
                voice_client.play(discord.FFmpegOpusAudio(audio_url, **ffmpeg_options))  # Play the selected surah with ffmpeg_options
                chapter_name = [chapter_name for chapter_number, chapter_name in quran_chapters.items() if chapter_number == str(selected_surah_number)][0]
                await interaction.response.send_message(content=f"Playing {chapter_name}...", ephemeral=True)
                looping_surahs[guild.id] = (voice_client, audio_url, False)  # Save looping info with looping status
        else:
            await interaction.response.send_message(content="You need to be in a voice channel to use this command.", ephemeral=True)

@client.hybrid_command(name='leave', help='Make the Bot leave the voice channel.')
async def leave(ctx):
    voice_client = ctx.guild.voice_client
    if voice_client:
        await voice_client.disconnect()
        await ctx.send("Left the voice channel.")
        if ctx.guild.id in looping_surahs:
            del looping_surahs[ctx.guild.id]  # Remove from looping_surahs if it exists
    else:
        await ctx.send("I'm not in a voice channel.")

@client.hybrid_command(name='pause', help='Pause the currently playing recitation.')
async def pause(ctx):
    voice_client = ctx.guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.pause()
        await ctx.send("Paused the audio.")
    else:
        await ctx.send("No audio is playing.")

@client.hybrid_command(name='resume', help='Resume the paused recitation.')
async def resume(ctx):
    voice_client = ctx.guild.voice_client
    if voice_client and voice_client.is_paused():
        voice_client.resume()
        await ctx.send("Resumed the audio.")
    else:
        await ctx.send("Audio is not paused.")

@client.hybrid_command(name='loop', help='Loop the currently playing recitation.')
async def loop(ctx):
    voice_client = ctx.guild.voice_client
    if voice_client and voice_client.is_playing():
        # Ensure audio_url is correctly captured
        current_audio_url = next((url for vc, url, is_looping in looping_surahs.values() if vc == voice_client), None)
        if current_audio_url:
            looping_surahs[ctx.guild.id] = (voice_client, current_audio_url, True)  # Enable looping
            await ctx.send("Looping the current recitation.")
        else:
            await ctx.send("Error: Could not determine the current audio URL.")
    else:
        await ctx.send("No audio is playing to loop.")

@client.hybrid_command(name='stoploop', help='Stop looping the current recitation.')
async def stoploop(ctx):
    if ctx.guild.id in looping_surahs:
        voice_client, audio_url, _ = looping_surahs[ctx.guild.id]
        looping_surahs[ctx.guild.id] = (voice_client, audio_url, False)  # Disable looping
        await ctx.send("Stopped looping the current recitation.")
    else:
        await ctx.send("No recitation is currently being looped.")

@tasks.loop(seconds=1.0)
async def check_looping():
    for guild_id, (voice_client, audio_url, is_looping) in list(looping_surahs.items()):
        if is_looping and not voice_client.is_playing():
            new_audio = discord.FFmpegOpusAudio(audio_url, **ffmpeg_options)
            voice_client.play(new_audio)

@client.hybrid_command(name='read', help='Read the English translated Quran.')
async def read(ctx):
    view = QuranReadingView()
    await ctx.send("Select which Quran chapter would you like to read:", view=view)

@client.hybrid_command(name='recite', help='Make the Bot recite the Quran.')
async def recite(ctx):
    view = QuranListeningView()
    await ctx.send("Select which Surah would you like to listen to:", view=view)

# Run the bot
client.run(TOKEN)

