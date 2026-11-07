
import os
import sys

# Add bundled Python libraries
ADDON_PATH = os.path.dirname(os.path.abspath(__file__))
LIB_PATH = os.path.join(ADDON_PATH, "lib")

if LIB_PATH not in sys.path:
    sys.path.insert(0, LIB_PATH)

import xbmc
import xbmcgui
import xbmcplugin
import urllib.request
import yt_dlp

from urllib.parse import urlencode, parse_qsl
from datetime import datetime
import json
import re
import urllib.request
import urllib.parse
import urllib.error
import xbmcaddon


# ==================================================
# TOUSTELLO YOUTUBE - KODI 22
# ==================================================

ADDON_URL = sys.argv[0]
HANDLE = int(sys.argv[1])

MAX_SEARCH_RESULTS = 20
MAX_CHANNEL_VIDEOS = 40


YDL_BASE = {
    "quiet": True,
    "no_warnings": False,
    "noplaylist": True,
    "ignoreerrors": True,

    # Do not use optional curl_cffi backend.
    "compat_opts": set(),

    # Use standard urllib networking.
    "legacyserverconnect": True,
}


# ==================================================
# YOUTUBE DATA API V3
# ==================================================

ADDON = xbmcaddon.Addon()
API_BASE = "https://www.googleapis.com/youtube/v3"


def transfer_api_key():
    try:
        request = urllib.request.Request(
            "http://127.0.0.1:8766/start",
            method="GET"
        )

        with urllib.request.urlopen(
            request,
            timeout=5
        ) as response:
            data = json.loads(response.read().decode("utf-8"))

        ip = data["ip"]
        port = data["port"]
        pin = data["pin"]

        command = (
            "$k = Read-Host 'YouTube API key'; "
            "Invoke-RestMethod "
            "-Uri 'http://" + ip + ":" + str(port) + "/key' "
            "-Method Post "
            "-ContentType 'application/json' "
            "-Body (@{pin='" + pin +
            "';api_key=$k} | ConvertTo-Json -Compress)"
        )

        message = (
            "Dočasný server je spuštěný.\n\n"
            "IP adresa televize: " + ip + "\n"
            "Port: " + str(port) + "\n"
            "PIN: " + pin + "\n\n"
            "Platnost: 3 minuty.\n\n"
            "Na počítači otevři PowerShell "
            "a spusť následující příkaz:\n\n"
            + command
        )

        xbmcgui.Dialog().ok(
            "Přenos YouTube API klíče",
            message
        )

    except Exception as error:
        xbmcgui.Dialog().ok(
            "Přenos API klíče",
            "Nepodařilo se spustit přenosový server.\n\n"
            + str(error)
            + "\n\nZkontroluj, zda je služba Toustello spuštěná."
        )

def api_request(endpoint, **params):
    api_key = ADDON.getSetting("youtube_api_key").strip()

    if not api_key:
        raise Exception(
            "Chybí YouTube API Key. "
            "Otevři nastavení doplňku Toustello YouTube."
        )

    params["key"] = api_key

    url = API_BASE + "/" + endpoint + "?" + urllib.parse.urlencode(params)

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ToustelloYouTube/1.0",
            "Accept": "application/json"
        }
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    except urllib.error.HTTPError as error:
        try:
            data = json.loads(error.read().decode("utf-8"))
            message = data.get("error", {}).get("message", str(error))
            reason = (
                data.get("error", {})
                .get("errors", [{}])[0]
                .get("reason", "")
            )
            raise Exception(
                "YouTube API: " + message
                + (" (" + reason + ")" if reason else "")
            )
        except (ValueError, IndexError):
            raise Exception("YouTube API HTTP error: " + str(error))

    except urllib.error.URLError as error:
        raise Exception("Síťová chyba: " + str(error))


def parse_duration(value):
    if not value:
        return 0

    match = re.fullmatch(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
        value
    )

    if not match:
        return 0

    hours, minutes, seconds = (
        int(x or 0) for x in match.groups()
    )

    return hours * 3600 + minutes * 60 + seconds


def api_video_to_info(video):
    snippet = video.get("snippet", {})
    content = video.get("contentDetails", {})

    thumbnails = snippet.get("thumbnails", {})

    thumbnail = (
        thumbnails.get("maxres")
        or thumbnails.get("high")
        or thumbnails.get("medium")
        or thumbnails.get("default")
        or {}
    )

    published = snippet.get("publishedAt", "")

    upload_date = ""

    if published:
        upload_date = published[:10].replace("-", "")

    channel_id = snippet.get("channelId", "")

    return {
        "id": video.get("id", ""),
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "thumbnail": thumbnail.get("url", ""),
        "channel": snippet.get("channelTitle", ""),
        "uploader": snippet.get("channelTitle", ""),
        "channel_id": channel_id,
        "channel_url": (
            "https://www.youtube.com/channel/" + channel_id
            if channel_id else ""
        ),
        "webpage_url": (
            "https://www.youtube.com/watch?v=" + video.get("id", "")
        ),
        "upload_date": upload_date,
        "duration": parse_duration(content.get("duration")),
        "categories": [],
        "tags": snippet.get("tags", []),
    }


def api_get_video_details(video_ids):
    if not video_ids:
        return []

    result = api_request(
        "videos",
        part="snippet,contentDetails",
        id=",".join(video_ids[:50])
    )

    videos = result.get("items", [])

    by_id = {
        video.get("id"): api_video_to_info(video)
        for video in videos
    }

    # Preserve the original search order.
    return [
        by_id[video_id]
        for video_id in video_ids
        if video_id in by_id
    ]


def api_search_videos(query):
    result = api_request(
        "search",
        part="snippet",
        type="video",
        q=query,
        maxResults=20,
        order="relevance"
    )

    video_ids = [
        item.get("id", {}).get("videoId")
        for item in result.get("items", [])
        if item.get("id", {}).get("videoId")
    ]

    return api_get_video_details(video_ids)


def api_search_channels(query):
    result = api_request(
        "search",
        part="snippet",
        type="channel",
        q=query,
        maxResults=20,
        order="relevance"
    )

    channels = []

    for item in result.get("items", []):
        snippet = item.get("snippet", {})
        channel_id = item.get("id", {}).get("channelId")

        if not channel_id:
            continue

        thumbnails = snippet.get("thumbnails", {})
        thumbnail = (
            thumbnails.get("high")
            or thumbnails.get("medium")
            or thumbnails.get("default")
            or {}
        )

        channels.append({
            "id": channel_id,
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "thumbnail": thumbnail.get("url", ""),
        })

    return channels


def api_channel_videos(channel_id):
    channel_result = api_request(
        "channels",
        part="contentDetails",
        id=channel_id
    )

    channels = channel_result.get("items", [])

    if not channels:
        return []

    uploads_id = (
        channels[0]
        .get("contentDetails", {})
        .get("relatedPlaylists", {})
        .get("uploads")
    )

    if not uploads_id:
        return []

    playlist = api_request(
        "playlistItems",
        part="contentDetails",
        playlistId=uploads_id,
        maxResults=50
    )

    video_ids = [
        item.get("contentDetails", {}).get("videoId")
        for item in playlist.get("items", [])
        if item.get("contentDetails", {}).get("videoId")
    ]

    return api_get_video_details(video_ids)

def get_adaptive_manifest(info):
    formats = info.get("formats", [])

    # Prefer HLS master manifest.
    for fmt in formats:
        protocol = fmt.get("protocol") or ""
        manifest = fmt.get("manifest_url")

        if manifest and "m3u8" in protocol:
            return {
                "url": manifest,
                "mime": "application/vnd.apple.mpegurl",
                "headers": fmt.get("http_headers") or info.get("http_headers") or {},
                "type": "HLS",
            }

    # Otherwise try MPEG-DASH.
    for fmt in formats:
        protocol = fmt.get("protocol") or ""
        manifest = fmt.get("manifest_url")

        if manifest and "dash" in protocol:
            return {
                "url": manifest,
                "mime": "application/dash+xml",
                "headers": fmt.get("http_headers") or info.get("http_headers") or {},
                "type": "DASH",
            }

    return None


# ==================================================
# LOGGING
# ==================================================

def log(message, level=xbmc.LOGINFO):
    xbmc.log("[TOUSTELLO] " + str(message), level)


# ==================================================
# YT-DLP
# ==================================================

def extract(url, extra=None):
    options = dict(YDL_BASE)

    if extra:
        options.update(extra)

    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(url, download=False)


def search_videos(query):
    log("Searching videos: " + query)

    result = extract(
        "ytsearch" + str(MAX_SEARCH_RESULTS) + ":" + query,
        {"noplaylist": False}
    )

    return result.get("entries", []) if result else []


def get_channel_url(info):
    url = info.get("channel_url") or info.get("uploader_url")

    if url:
        return url

    channel_id = info.get("channel_id")

    if channel_id:
        return "https://www.youtube.com/channel/" + channel_id

    return None


# ==================================================
# METADATA
# ==================================================

def format_date(value):
    if not value:
        return ""

    try:
        return datetime.strptime(
            str(value), "%Y%m%d"
        ).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return ""


def make_item(info, path, playable=False):
    title = info.get("title") or "Neznámé video"

    description = (
        info.get("description")
        or info.get("description_snippet")
        or ""
    )

    thumbnail = info.get("thumbnail") or ""

    channel = (
        info.get("channel")
        or info.get("uploader")
        or ""
    )

    duration = int(info.get("duration") or 0)

    release_date = (
        format_date(info.get("release_date"))
        or format_date(info.get("upload_date"))
    )

    year = info.get("release_year")

    if not year and release_date:
        year = int(release_date[:4])

    item = xbmcgui.ListItem(
        label=title,
        path=path
    )

    item.setInfo("video", {
        "title": title,
        "originaltitle": title,
        "plot": description,
        "plotoutline": description[:250],
        "studio": channel,
        "duration": duration,
        "premiered": release_date,
        "year": int(year) if year else 0,
        "date": release_date,
        "genre": info.get("categories") or [],
        "tag": info.get("tags") or [],
        "mediatype": "video",
    })

    item.setArt({
        "thumb": thumbnail,
        "icon": thumbnail,
        "poster": thumbnail,
        "fanart": thumbnail,
    })

    if playable:
        item.setProperty("IsPlayable", "true")

    return item


def plugin_url(action, **kwargs):
    params = {"action": action}
    params.update(kwargs)

    return ADDON_URL + "?" + urlencode(params)


def playback_url(video_url):
    """
    Use yt-dlp Cast as the playback engine when installed.
    Keep the original Toustello player as a fallback.
    """
    if xbmc.getCondVisibility(
        "System.HasAddon(plugin.video.ytdlpcast)"
    ):
        return (
            "plugin://plugin.video.ytdlpcast/?"
            + urlencode({"url": video_url})
        )

    return plugin_url("play", video_url=video_url)


# ==================================================
# MAIN MENU
# ==================================================

def show_main_menu():
    xbmcplugin.setContent(HANDLE, "videos")

    entries = [
        ("Vyhledat videa", "search_videos"),
        ("Vyhledat kanály", "search_channels"),
        ("Přenést API klíč z PC", "transfer_api_key"),
        ("Nastavení", "settings"),
    ]

    for title, action in entries:
        item = xbmcgui.ListItem(label=title)

        xbmcplugin.addDirectoryItem(
            HANDLE,
            plugin_url(action),
            item,
            True
        )

    xbmcplugin.endOfDirectory(HANDLE)


# ==================================================
# SEARCH
# ==================================================

def ask_search():
    return xbmcgui.Dialog().input(
        "Vyhledávání YouTube",
        type=xbmcgui.INPUT_ALPHANUM
    ).strip()



def search_video_page():
    query = ask_search()

    if not query:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    try:
        results = api_search_videos(query)

        xbmcplugin.setContent(HANDLE, "videos")


        for info in results:
            video_url = info["webpage_url"]
            target_url = playback_url(video_url)

            item = make_item(
                info,
                target_url,
                True
            )

            xbmcplugin.addDirectoryItem(
                HANDLE,
                target_url,
                item,
                False
            )


        log("API video results: " + str(len(results)))

        xbmcplugin.endOfDirectory(HANDLE)

    except Exception as error:
        log("API search error: " + str(error), xbmc.LOGERROR)

        xbmcgui.Dialog().ok(
            "YouTube API – chyba",
            str(error)
        )

        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)

# ==================================================
# CHANNEL SEARCH
# ==================================================


def search_channel_page():
    query = ask_search()

    if not query:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    try:
        channels = api_search_channels(query)

        xbmcplugin.setContent(HANDLE, "videos")

        for channel in channels:
            item = xbmcgui.ListItem(label=channel["title"])

            item.setInfo("video", {
                "title": channel["title"],
                "plot": channel["description"],
                "studio": channel["title"],
            })

            item.setArt({
                "thumb": channel["thumbnail"],
                "icon": channel["thumbnail"],
                "poster": channel["thumbnail"],
            })

            xbmcplugin.addDirectoryItem(
                HANDLE,
                plugin_url(
                    "channel",
                    channel_id=channel["id"]
                ),
                item,
                True
            )

        log("API channel results: " + str(len(channels)))

        xbmcplugin.endOfDirectory(HANDLE)

    except Exception as error:
        log("API channel search error: " + str(error), xbmc.LOGERROR)

        xbmcgui.Dialog().ok(
            "YouTube API – chyba",
            str(error)
        )

        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


# ==================================================
# CHANNEL VIDEOS
# ==================================================


def show_channel():
    channel_id = params.get("channel_id")

    if not channel_id:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    try:
        results = api_channel_videos(channel_id)

        xbmcplugin.setContent(HANDLE, "videos")


        for info in results:
            video_url = info["webpage_url"]
            target_url = playback_url(video_url)

            item = make_item(
                info,
                target_url,
                True
            )

            xbmcplugin.addDirectoryItem(
                HANDLE,
                target_url,
                item,
                False
            )


        log("API channel videos: " + str(len(results)))

        xbmcplugin.endOfDirectory(HANDLE)

    except Exception as error:
        log("API channel error: " + str(error), xbmc.LOGERROR)

        xbmcgui.Dialog().ok(
            "YouTube API – chyba kanálu",
            str(error)
        )

        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


# ==================================================
# QUALITY SELECTION
# ==================================================

def get_progressive_formats(info):
    formats = []

    for fmt in info.get("formats", []):
        if not fmt.get("url"):
            continue

        if fmt.get("vcodec") in (None, "none"):
            continue

        if fmt.get("acodec") in (None, "none"):
            continue

        formats.append(fmt)

    formats.sort(
        key=lambda f: (
            f.get("height") or 0,
            f.get("fps") or 0,
            f.get("tbr") or 0
        ),
        reverse=True
    )

    return formats


def format_label(fmt):
    height = fmt.get("height")

    resolution = (
        str(height) + "p"
        if height else
        fmt.get("resolution", "Neznámé rozlišení")
    )

    fps = fmt.get("fps")
    ext = fmt.get("ext", "")

    label = resolution

    if fps:
        label += " / " + str(int(fps)) + " FPS"

    if ext:
        label += " / " + ext.upper()

    return label


def choose_quality(info):
    formats = get_progressive_formats(info)

    if not formats:
        raise Exception(
            "Video nemá dostupný progresivní stream "
            "obsahující obraz i zvuk."
        )

    options = [
        "Automaticky – nejlepší dostupná kvalita"
    ]

    options.extend(
        format_label(fmt)
        for fmt in formats
    )

    selected = xbmcgui.Dialog().select(
        "Vyber kvalitu videa",
        options
    )

    if selected < 0:
        return None

    if selected == 0:
        return formats[0]

    return formats[selected - 1]


# ==================================================
# PLAYBACK
# ==================================================


def play_video():
    video_url = params.get("video_url")

    if not video_url:
        xbmcplugin.setResolvedUrl(
            HANDLE, False, xbmcgui.ListItem()
        )
        return

    try:
        info = extract(video_url)

        if not info:
            raise Exception("yt-dlp nevrátil informace o videu.")

        adaptive = get_adaptive_manifest(info)

        if adaptive and xbmc.getCondVisibility(
            "System.HasAddon(inputstream.adaptive)"
        ):
            log("Using " + adaptive["type"] + " adaptive manifest")

            item = make_item(info, adaptive["url"])

            item.setMimeType(adaptive["mime"])
            item.setContentLookup(False)

            item.setProperty(
                "inputstream",
                "inputstream.adaptive"
            )

            headers = adaptive["headers"]

            if headers:
                item.setProperty(
                    "inputstream.adaptive.common_headers",
                    urlencode(headers)
                )

            xbmcplugin.setResolvedUrl(
                HANDLE,
                True,
                item
            )

            return

        # Fallback: progressive stream with audio and video.
        log("No adaptive manifest found; using progressive fallback")

        selected_format = choose_quality(info)

        if selected_format is None:
            xbmcplugin.setResolvedUrl(
                HANDLE, False, xbmcgui.ListItem()
            )
            return

        stream_url = selected_format["url"]

        headers = (
            selected_format.get("http_headers")
            or info.get("http_headers")
            or {}
        )

        if headers:
            stream_url += "|" + urlencode(headers)

        item = make_item(info, stream_url)

        xbmcplugin.setResolvedUrl(
            HANDLE,
            True,
            item
        )

    except Exception as error:
        log("Playback error: " + str(error), xbmc.LOGERROR)

        xbmcgui.Dialog().ok(
            "Chyba přehrávání",
            str(error)
        )

        xbmcplugin.setResolvedUrl(
            HANDLE,
            False,
            xbmcgui.ListItem()
        )

# ==================================================
# ROUTER
# ==================================================

params = dict(
    parse_qsl(
        sys.argv[2][1:]
        if len(sys.argv) > 2 else ""
    )
)

action = params.get("action")

if action == "search_videos":
    search_video_page()

elif action == "search_channels":
    search_channel_page()

elif action == "channel":
    show_channel()

elif action == "play":
    play_video()

elif action == "transfer_api_key":
    transfer_api_key()
    xbmcplugin.endOfDirectory(HANDLE)

elif action == "settings":  
    ADDON.openSettings()
    xbmcplugin.endOfDirectory(HANDLE)

else:
    show_main_menu()
