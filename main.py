import queue

from yandex_music import Client
from discord.ext import commands
from hashlib import md5
from asyncio import run
import config
from config import settings
from discord import FFmpegPCMAudio
import urllib.request
import xmltodict


ds_client = commands.Bot(command_prefix=settings['prefix'])
ym_client = Client(config.token).init()

ffmpeg_options = {
    'options': '-vn -loglevel panic',
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
}

voice = None
vc = None
music_queue = queue.Queue(maxsize=0)


@ds_client.command()
async def hello(ctx):
    author = ctx.message.author
    await ctx.send(f'Բարեւ, {author.mention}!')


@ds_client.command()
async def vc_connect(ctx):
    author = ctx.message.author
    vc = author.voice
    if vc:
        voice = await vc.channel.connect()


@ds_client.command()
async def pause(ctx):
    vc = ds_client.voice_clients[0]
    if vc is None or not vc.is_connected() or not vc.is_playing():
        return
    await ctx.send('Paused')
    vc.pause()


@ds_client.command()
async def resume(ctx):
    vc = ds_client.voice_clients[0]
    if vc is None or not vc.is_connected() or vc.is_playing():
        return
    await ctx.send('Resumed')
    vc.resume()


@ds_client.command()
async def skip(ctx):
    vc = ds_client.voice_clients[0]
    if vc is None or not vc.is_connected() or not vc.is_playing():
        return
    await ctx.send('Skipped')
    vc.stop()


@ds_client.command()
async def search(ctx):
    if ym_client.search(ctx.message.content[8::])['tracks'] is None:
        await ctx.send("Can't find anything. Уебись об стену и попробуй ещё раз.")
        return
    track_list = ym_client.search(ctx.message.content[8::])['tracks']['results']
    msg = ''
    n = 5 if len(track_list) > 5 else len(track_list)
    for i in range(n):
        track = track_list[i]
        title = track['title']
        artist = track['artists'][0]['name']
        msg += str(i + 1) + f'. **{artist}** - **{title}** \n'
    await ctx.send(msg)


@ds_client.command()
async def play(ctx):
    author = ctx.message.author

    await parse_message_and_fill_queue(ctx)

    global vc
    if vc is None or not vc.is_connected():
        vc = await author.voice.channel.connect()
        await next_track(ctx)
    else:
        if not vc.is_playing():
            await next_track(ctx)


async def parse_message_and_fill_queue(ctx):
    if 'music.yandex.ru' not in ctx.message.content.split(' ')[1]:
        request = ctx.message.content[6::]
        track = ym_client.search(ctx.message.content[8::])['tracks']['results'][0]
        if track is None:
            await ctx.send("Can't find any tracks.")
            return
        await add_track_to_queue(track)

    elif 'playlist' in ctx.message.content.split(' ')[1]:
        ymlink = ctx.message.content.split(' ')[1]
        user_id = ymlink.split('users/')[1].split('/playlists')[0]
        playlist_id = ymlink.split('playlists/')[1]
        playlist_info = ym_client.users_playlists(playlist_id, user_id=user_id)
        track_list = playlist_info['tracks']
        for track in track_list:
            track_id = f'{track["id"]}:{track["track"]["albums"][0]["id"]}'
            link, track_info = await get_track_info(track_id)
            source = FFmpegPCMAudio(link, **ffmpeg_options, executable=config.ffmpeg)
            music_queue.put([source, track_info])
        await ctx.send(
            f'Successfully added *{playlist_info.track_count}* tracks from **{playlist_info.title}** *playlist* by **{playlist_info.owner.name}** to the queue.')

    elif 'track' in ctx.message.content.split(' ')[1]:
        ymlink = ctx.message.content.split(' ')[1]
        album_id = ymlink.split('album/')[1].split('/track')[0]
        track_id = ymlink.split('track/')[1]
        track = f'{track_id}:{album_id}'

        link, track_info = await get_track_info(track)
        source = FFmpegPCMAudio(link, **ffmpeg_options, executable=config.ffmpeg)
        music_queue.put([source, track_info])

        await ctx.send(
            f'Successfully added **{track_info.title}** by **{track_info.artists[0].name}** to the queue.')
    else:
        ymlink = ctx.message.content.split(' ')[1]
        album_id = ymlink.split('album/')[1]
        track_list = ym_client.albums_with_tracks(album_id).volumes[0]
        album_info = ym_client.albums(album_id)[0]
        for track in track_list:
            track_id = f'{track["id"]}:{album_id}'
            link, track_info = await get_track_info(track_id)
            source = FFmpegPCMAudio(link, **ffmpeg_options, executable=config.ffmpeg)
            music_queue.put([source, track_info])
        await ctx.send(
            f'Successfully added *{album_info.track_count}* tracks from **{album_info.title}** *album* by **{album_info.artists[0].name}** to the queue.')


async def next_track(ctx):
    vc = None
    if len(ds_client.voice_clients) == 0:
        return
    vc = ds_client.voice_clients[0]
    global music_queue
    if music_queue.empty():
        return
    author = ctx.message.author
    track = music_queue.get()
    source = track[0]
    track_info = track[1]
    source.read()
    if vc is None or not vc.is_connected():
        vc = author.voice.channel.connect()
        vc.play(source, after=lambda e: run(next_track(ctx)))
    else:
        vc.play(source, after=lambda e: run(next_track(ctx)))


async def add_track_to_queue(track):
    track_id = f'{track["id"]}:{track["albums"][0]["id"]}'
    link, track_info = await get_track_info(track_id)
    source = FFmpegPCMAudio(link, **ffmpeg_options, executable=config.ffmpeg)
    music_queue.put([source, track_info])


async def get_track_info(track_id: str):
    track_info = ym_client.tracks(track_id)[0]

    url = track_info.get_download_info()[0]['download_info_url']
    response = urllib.request.urlopen(url).read()
    tree = xmltodict.parse(response)
    link = build_direct_link(tree)
    return link, track_info


def build_direct_link(tree: dict) -> str:
    dwinfo = tree['download-info']
    host = dwinfo['host']
    path = dwinfo['path']
    ts = dwinfo['ts']
    s = dwinfo['s']
    sign = md5(('XGRlBW9FXlekgbPrRHuSiA' + path[1::] + s).encode('utf-8')).hexdigest()
    return f'https://{host}/get-mp3/{sign}/{ts}{path}'


@ds_client.event
async def on_ready():
    print('Time to mix drinks and change lives.')


ds_client.run(settings['token'])
