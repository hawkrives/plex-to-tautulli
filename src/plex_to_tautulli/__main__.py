from __future__ import annotations

import argparse
import collections
from pprint import pprint
import sys
from pathlib import Path
from collections.abc import Iterator
from dataclasses import dataclass

import requests
from dotenv import load_dotenv
from os import environ, remove
from sqlite3 import connect

load_dotenv(verbose=True)

TAUTULLI_URL = f"{environ['TAUTULLI_URL']}/api/v2"
PLEX_URL = f"http://{environ['PLEX_URL']}:{environ['PLEX_PORT']}"
PLEX_API_KEY = environ["PLEX_API_KEY"]
PLEX_TOKEN = f"X-Plex-Token={PLEX_API_KEY}"

tautulli = requests.Session()
tautulli.params = {"apikey": environ["TAUTULLI_API_KEY"]}

plex = requests.Session()
plex.headers.update({"Accept": "application/json", "X-Plex-Token": PLEX_API_KEY})


def paginated_get(urlpath: str, search_params: None | dict[str, str] = None) -> Iterator[dict]:
    """Fetches all the items from a paginated GET endpoint from the plex server."""
    # See <https://developer.plex.tv/pms/#tag/Status/operation/statusGetHistoryAll>
    # and <https://developer.plex.tv/pms/#section/API-Info/Pagination>

    assert urlpath.startswith("/"), "urlpath must start with /"

    container_start = 0
    container_size = 500

    while True:
        headers = {"X-Plex-Container-Start": str(container_start), "X-Plex-Container-Size": str(container_size)}
        resp = plex.get(f"{PLEX_URL}{urlpath}", params=search_params, headers=headers)

        body = resp.json()
        yield body

        # If we got back fewer items than we asked for, we're done; otherwise,
        # continue with the next request
        count = body["MediaContainer"]["size"]
        if count < container_size:
            break
        else:
            container_start += count


@dataclass(slots=True, frozen=True, repr=True)
class TautulliUser:
    user_id: int
    username: str

    @staticmethod
    def from_dict(data: dict) -> TautulliUser:
        return TautulliUser(user_id=data["user_id"], username=data["username"])

    @staticmethod
    def fetch() -> Iterator[TautulliUser]:
        """Fetches all the tautulli users in the server."""
        resp = tautulli.get(f"{TAUTULLI_URL}", params={"cmd": "get_users"}).json().get("response", {}).get("data", [])
        return (TautulliUser.from_dict(u) for u in resp)


@dataclass(slots=True, frozen=True, repr=True)
class PlexUser:
    id: int
    key: str
    name: str

    @staticmethod
    def from_dict(data: dict) -> PlexUser:
        return PlexUser(id=data["id"], key=data["key"], name=data["name"])

    @staticmethod
    def fetch() -> Iterator[PlexUser]:
        """Fetches all the plex users in the plex server."""
        for page in paginated_get("/accounts"):
            for a in page["MediaContainer"].get("Account", []):
                yield PlexUser.from_dict(a)


@dataclass(slots=True, frozen=True, repr=True)
class PlexDevice:
    id: int
    name: str
    platform: str
    created_at: int
    client_identifier: str

    @staticmethod
    def from_dict(data: dict) -> PlexDevice:
        return PlexDevice(
            id=data["id"],
            name=data["name"],
            platform=data["platform"],
            created_at=data["createdAt"],
            client_identifier=data["clientIdentifier"],
        )

    @staticmethod
    def fetch() -> Iterator[PlexDevice]:
        """Fetches all the plex devices in the plex server."""
        for page in paginated_get("/devices"):
            for a in page["MediaContainer"].get("Device", []):
                yield PlexDevice.from_dict(a)


@dataclass(slots=True, frozen=True, repr=True)
class PlexHub:
    id: str
    name: str
    type: str
    key: str

    @staticmethod
    def from_dict(data: dict) -> PlexHub:
        return PlexHub(id=data["id"], name=data["name"], type=data["type"], key=data["key"])

    @staticmethod
    def fetch(library_type: str | None = None) -> Iterator[PlexHub]:
        """Fetches all the plex hubs in the plex server."""
        for page in paginated_get("/media/providers"):
            for provider in page["MediaContainer"].get("MediaProvider", []):
                if provider["identifier"] != "com.plexapp.plugins.library":
                    # don't know what other provider types exist yet
                    continue

                for f in provider.get("Feature", []):
                    if f["type"] != "content":
                        # things like search, or... yeah, lots of stuff
                        continue

                    for entry in f.get("Directory", []):
                        if entry.get("type") not in ("movie", "show", "artist"):
                            # playlists? also, "hubKey" has no .type field
                            continue

                        if library_type is not None and entry.get("type") != library_type:
                            continue

                        for pivot in entry.get("Pivot", []):
                            if pivot["id"] != "library":
                                # others include "recommended" and "categories"
                                continue

                            yield PlexHub(id=entry["id"], name=entry["title"], type=entry["type"], key=pivot["key"])

    def collect(self) -> Iterator[PlexMedia]:
        """Collects all the media items associated with this hub."""
        for page in paginated_get(self.key):
            for metadata in page["MediaContainer"].get("Metadata", []):
                match metadata["type"]:
                    case "movie" | "show":
                        yield PlexMedia.from_video_dict(metadata)
                    case "artist":
                        yield PlexMedia.from_audio_dict(metadata)
                    case type:
                        print(f"Unknown media type in hub.collect(): {type}", file=sys.stderr)


@dataclass(slots=True, frozen=True, repr=True)
class PlexLibrary:
    key: str
    title: str
    type: str | None

    @staticmethod
    def from_dict(data: dict) -> PlexLibrary:
        return PlexLibrary(key=data["key"], title=data["title"], type=data.get("type"))

    @property
    def section_id(self) -> str:
        return self.key

    @staticmethod
    def fetch(library_type: str | None = None) -> Iterator[PlexLibrary]:
        """Fetches all the plex libraries in the plex server."""
        for page in paginated_get("/library/sections"):
            for a in page["MediaContainer"].get("Directory", []):
                item = PlexLibrary.from_dict(a)
                if library_type is not None and item.type != library_type:
                    continue
                yield item


@dataclass(slots=True, frozen=True, repr=True)
class PlexMedia:
    """Represents either a Movie, or an episode from a TV season from a TV show"""

    # Universal
    key: str
    rating_key: str
    type: str
    title: str
    thumb: str
    art: str
    duration: str
    year: str
    originally_available_at: str
    added_at: str
    updated_at: str
    content_rating: str
    summary: str
    rating: str
    guid: str
    directors: list[str]
    writers: list[str]
    actors: list[str]
    genres: list[str]
    studio: str
    bitrate: str
    container: str
    width: str
    height: str
    aspect_ratio: str
    # video_resolution: str
    # video_frame_rate: str
    # video_codec: str

    # Movies only
    tagline: str

    # Shows only
    index: str
    last_viewed_at: str
    parent_index: str
    parent_title: str
    parent_thumb: str
    parent_rating_key: str
    grandparent_index: str
    grandparent_title: str
    grandparent_thumb: str
    grandparent_rating_key: str

    # Music?
    # don't know of any, yet

    @staticmethod
    def from_video_dict(video: dict) -> PlexMedia:
        media_dict = {**video}

        if media := video.get("Media", []):
            media_dict.update(media[0])

        media_dict["genres"] = [g["tag"] for g in video.get("Genre", [])]
        media_dict["directors"] = [g["tag"] for g in video.get("Director", [])]
        media_dict["writers"] = [g["tag"] for g in video.get("Writer", [])]
        media_dict["actors"] = [g["tag"] for g in video.get("Role", [])]

        return PlexMedia.from_dict(media_dict)

    @staticmethod
    def from_audio_dict(audio: dict) -> PlexMedia:
        media_dict = {**audio}

        if media := audio.get("Media", []):
            media_dict.update(media[0])

        media_dict["genres"] = [g["tag"] for g in audio.get("Genre", [])]
        media_dict["actors"] = [g["tag"] for g in audio.get("Role", [])]

        return PlexMedia.from_dict(media_dict)

    @staticmethod
    def from_dict(data: dict) -> PlexMedia:
        return PlexMedia(
            # Universal
            key=data.get("key", ""),
            rating_key=data.get("ratingKey", ""),
            type=data.get("type", ""),
            title=data.get("title", ""),
            thumb=data.get("thumb", ""),
            art=data.get("art", ""),
            duration=data.get("duration", ""),
            year=data.get("year", ""),
            originally_available_at=data.get("originallyAvailableAt", ""),
            added_at=data.get("addedAt", ""),
            updated_at=data.get("updatedAt", ""),
            content_rating=data.get("contentRating", ""),
            summary=data.get("summary", ""),
            rating=data.get("rating", ""),
            guid=data.get("guid", ""),
            directors=data.get("directors", []),
            writers=data.get("writers", []),
            actors=data.get("actors", []),
            genres=data.get("genres", []),
            studio=data.get("studio", ""),
            bitrate=data.get("bitrate", ""),
            container=data.get("container", ""),
            width=data.get("width", ""),
            height=data.get("height", ""),
            aspect_ratio=data.get("aspectRatio", ""),
            # video_resolution=data.get('videoResolution'),
            # video_frame_rate=data.get('videoFrameRate'),
            # video_codec=data.get('videoCodec'),
            # Movies only
            tagline=data.get("tagline", ""),
            # Shows only
            index=data.get("index", ""),
            last_viewed_at=data.get("lastViewedAt", ""),
            parent_index=data.get("parentIndex", ""),
            parent_title=data.get("parentTitle", ""),
            parent_thumb=data.get("parentThumb", ""),
            parent_rating_key=data.get("parentRatingKey", ""),
            grandparent_index=data.get("grandparentIndex", ""),
            grandparent_title=data.get("grandparentTitle", ""),
            grandparent_thumb=data.get("grandparentThumb", ""),
            grandparent_rating_key=data.get("grandparentRatingKey", ""),
        )

    def tree(self) -> Iterator[PlexMedia]:
        """Fetches the entire tree of media items under this media item, if any."""
        yield self
        for child in self.children():
            yield from child.tree()

    def children(self) -> Iterator[PlexMedia]:
        """Fetches the child media items of this media item, if any."""
        match self.type:
            case "movie" | "episode" | "track":
                # these have no children
                pass
            case "show" | "season":
                # video collection items
                for page in paginated_get(self.key):
                    for metadata in page["MediaContainer"].get("Metadata", []):
                        yield PlexMedia.from_video_dict(metadata)
            case "artist" | "album":
                # audio collection items
                for page in paginated_get(self.key):
                    for metadata in page["MediaContainer"].get("Metadata", []):
                        yield PlexMedia.from_audio_dict(metadata)
            case type:
                print(f"Unknown media type in PlexMedia.children(): {type}", file=sys.stderr)

    # def __repr__(self) -> str:
    #     return f"PlexMedia(key={self.key}, title={self.title})"


@dataclass(slots=True, frozen=True, repr=True)
class PlexHistory:
    history_key: str | None
    key: str
    rating_key: str
    library_section_id: str | None
    parent_key: str | None
    grandparent_key: str | None
    title: str | None
    grandparent_title: str | None
    type: str | None
    thumb: str | None
    parent_thumb: str | None
    grandparent_thumb: str | None
    grandparent_art: str | None
    index: str | None
    parent_index: str | None
    originally_available_at: str | None
    viewed_at: str | None
    account_id: int
    device_id: int

    @staticmethod
    def from_dict(data: dict) -> PlexHistory:
        return PlexHistory(
            history_key=data.get("historyKey"),
            key=data["key"],
            rating_key=data["ratingKey"],
            library_section_id=data.get("librarySectionID"),
            parent_key=data.get("parentKey"),
            grandparent_key=data.get("grandparentKey"),
            title=data.get("title"),
            grandparent_title=data.get("grandparentTitle"),
            type=data.get("type"),
            thumb=data.get("thumb"),
            parent_thumb=data.get("parentThumb"),
            grandparent_thumb=data.get("grandparentThumb"),
            grandparent_art=data.get("grandparentArt"),
            index=data.get("index"),
            parent_index=data.get("parentIndex"),
            originally_available_at=data.get("originallyAvailableAt"),
            viewed_at=data.get("viewedAt"),
            account_id=data["accountID"],
            device_id=data["deviceID"],
        )

    @staticmethod
    def fetch(library_type: str | None = None) -> Iterator["PlexHistory"]:
        """Fetches all the plex history in the plex server."""
        skipped_items = collections.Counter()
        for page in paginated_get("/status/sessions/history/all"):
            print(f"Fetched history page with {page['MediaContainer'].get('size', 0)} items")
            for history_item in page["MediaContainer"].get("Metadata", []):
                match (library_type, history_item["type"]):
                    case (None, _):
                        pass
                    case ("artist", "artist" | "album" | "track"):
                        pass
                    case ("movie", "movie"):
                        pass
                    case ("show", "show" | "season" | "episode"):
                        pass
                    case (lib_type, hist_type):
                        skipped_items[(lib_type, hist_type)] += 1
                        continue

                if "ratingKey" not in history_item:
                    print(
                        f"Missing ratingKey in PlexHistory entry; this likely means that the original item was deleted. Skipping: {history_item!r}",
                        file=sys.stderr,
                    )
                    continue

                yield PlexHistory.from_dict(history_item)

        print("Skipped history items by (library_type, history_type):")
        for (lib_type, hist_type), count in skipped_items.items():
            print(f"- {count} for library type {lib_type} and history type {hist_type}")


def insert_history(histories: list[tuple[PlexHistory, PlexMedia, PlexDevice, TautulliUser]]):
    """Inserts the histories into the plex_to_tautulli.db file"""
    db = connect("plex_to_tautulli.db", isolation_level=None, autocommit=True)
    for i, (history, media, device, user) in enumerate(histories, start=1):
        db.execute(
            """
			insert into session_history_metadata (
                rating_key,        parent_rating_key,       grandparent_rating_key, title,                parent_title, 
                grandparent_title, original_title,          full_title,             media_index,          parent_media_index,
                thumb,             parent_thumb,            grandparent_thumb,      art,                  media_type, 
                year,              originally_available_at, added_at,               updated_at,           last_viewed_at, 
                content_rating,    summary,                 tagline,                rating,               duration, 
                guid,              directors,               writers,                actors,               genres,
                studio,            live,                    channel_call_sign,      channel_id,           channel_identifier, 
                channel_title,     channel_thumb,           channel_vcn,            marker_credits_first, marker_credits_final
            )
            values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
			""",
            (
                history.rating_key,
                media.parent_rating_key,
                media.grandparent_rating_key,
                media.title,
                media.parent_title,
                media.grandparent_title,
                "",  # original title
                media.title if media.type == "movie" else f"{media.grandparent_title} - {media.title}",
                media.index,
                media.parent_index,
                media.thumb,
                media.parent_thumb,
                media.grandparent_thumb,
                media.art,
                media.type,
                media.year,
                media.originally_available_at,
                media.added_at,
                media.updated_at,
                media.last_viewed_at,
                media.content_rating,
                media.summary,
                media.tagline,
                media.rating,
                media.duration,
                media.guid,
                ";".join(media.directors),
                ";".join(media.writers),
                ";".join(media.actors),
                ";".join(media.genres),
                media.studio,
                0,  # Never live for me
                "",
                "",
                "",
                "",
                "",
                "",
                None,
                None,  # channel and marker data is going to be null here
            ),
        )
        db.execute(
            """
			insert into session_history_media_info (rating_key, duration, container, bitrate, width, height, 
			aspect_ratio) values (?,?,?,?,?,?,?);
			""",
            (media.rating_key, media.duration, media.container, media.bitrate, media.width, media.height, media.aspect_ratio),
        )
        db.execute(
            """
			insert into session_history (reference_id, started, stopped, rating_key, user_id, user, paused_counter,
			player, platform, parent_rating_key, grandparent_rating_key, media_type, section_id, view_offset) values 
			(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
			""",
            (
                i,
                history.viewed_at,
                # media duration is in milliseconds, viewed at is epoch time in seconds
                int(history.viewed_at or "0") + (int(media.duration) // 1000),
                media.rating_key,
                user.user_id,
                user.username,
                0,
                device.name,
                device.platform,
                media.parent_rating_key,
                media.grandparent_rating_key,
                media.type,
                history.library_section_id,
                0,
            ),
        )
    db.close()


def init_db():
    remove("plex_to_tautulli.db")
    db = connect("plex_to_tautulli.db", isolation_level=None, autocommit=True)
    db.execute(
        """
        CREATE TABLE if not exists session_history (
        	id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference_id INTEGER,
            started INTEGER,
			stopped INTEGER,
			rating_key INTEGER,
			user_id INTEGER,
			user TEXT,
			ip_address TEXT,
			paused_counter INTEGER DEFAULT 0,
			player TEXT,
			product TEXT,
			product_version TEXT,
			platform TEXT,
			platform_version TEXT,
			profile TEXT,
			machine_id TEXT,
			bandwidth INTEGER,
			location TEXT,
			quality_profile TEXT,
			secure INTEGER,
			relayed INTEGER,
			parent_rating_key INTEGER,
			grandparent_rating_key INTEGER,
			media_type TEXT,
			section_id INTEGER,
			view_offset INTEGER DEFAULT 0
        );
        """,
        (),
    )
    db.execute("CREATE INDEX if not exists idx_session_history_media_type ON session_history (media_type);", ())
    db.execute("CREATE INDEX if not exists idx_session_history_media_type_stopped ON session_history (media_type, stopped ASC);", ())
    db.execute("CREATE INDEX if not exists idx_session_history_rating_key ON session_history (rating_key);", ())
    db.execute("CREATE INDEX if not exists idx_session_history_parent_rating_key ON session_history (parent_rating_key);", ())
    db.execute("CREATE INDEX if not exists idx_session_history_grandparent_rating_key ON session_history (grandparent_rating_key);", ())
    db.execute("CREATE INDEX if not exists idx_session_history_user ON session_history (user);", ())
    db.execute("CREATE INDEX if not exists idx_session_history_user_id ON session_history (user_id);", ())
    db.execute("CREATE INDEX if not exists idx_session_history_user_id_stopped ON session_history (user_id, stopped ASC);", ())
    db.execute("CREATE INDEX if not exists idx_session_history_section_id ON session_history (section_id);", ())
    db.execute("CREATE INDEX if not exists idx_session_history_section_id_stopped ON session_history (section_id, stopped ASC);", ())
    db.execute("CREATE INDEX if not exists idx_session_history_reference_id ON session_history (reference_id ASC);", ())
    db.execute(
        """
        CREATE TABLE if not exists session_history_metadata (
        	id INTEGER PRIMARY KEY,
            rating_key INTEGER, 
			parent_rating_key INTEGER, 
			grandparent_rating_key INTEGER, 
			title TEXT, 
			parent_title TEXT,
			grandparent_title TEXT,
			original_title TEXT,
			full_title TEXT,
			media_index INTEGER,
			parent_media_index INTEGER,
			thumb TEXT,
			parent_thumb TEXT,
			grandparent_thumb TEXT,
			art TEXT,
			media_type TEXT,
			year INTEGER,
			originally_available_at TEXT,
			added_at INTEGER,
			updated_at INTEGER,
			last_viewed_at INTEGER,
			content_rating TEXT,
			summary TEXT,
			tagline TEXT,
			rating TEXT,
			duration INTEGER DEFAULT 0,
			guid TEXT,
			directors TEXT,
			writers TEXT,
			actors TEXT,
			genres TEXT,
			studio TEXT,
			labels TEXT,
			live INTEGER DEFAULT 0,
			channel_call_sign TEXT,
			channel_id TEXT,
			channel_identifier TEXT,
			channel_title TEXT,
			channel_thumb TEXT,
			channel_vcn TEXT,
			marker_credits_first INTEGER DEFAULT NULL,
			marker_credits_final INTEGER DEFAULT NULL
        );
        """,
        (),
    )
    db.execute("CREATE INDEX if not exists idx_session_history_metadata_rating_key ON session_history_metadata (rating_key);", ())
    db.execute("CREATE INDEX if not exists idx_session_history_metadata_guid ON session_history_metadata (guid);", ())
    db.execute("CREATE INDEX if not exists idx_session_history_metadata_live ON session_history_metadata (live);", ())
    db.execute(
        """CREATE TABLE if not exists session_history_media_info (
			id INTEGER PRIMARY KEY,
			rating_key INTEGER,
			video_decision TEXT,
			audio_decision TEXT,
			transcode_decision TEXT,
			duration INTEGER DEFAULT 0,
			container TEXT,
			bitrate INTEGER,
			width INTEGER,
			height INTEGER,
			video_bitrate INTEGER,
			video_bit_depth INTEGER,
			video_codec TEXT,
			video_codec_level TEXT,
			video_width INTEGER,
			video_height INTEGER,
			video_resolution TEXT,
			video_framerate TEXT,
			video_scan_type TEXT,
			video_full_resolution TEXT,
			video_dynamic_range TEXT,
			aspect_ratio TEXT,
			audio_bitrate INTEGER,
			audio_codec TEXT,
			audio_channels INTEGER,
			audio_language TEXT,
			audio_language_code TEXT,
			subtitles INTEGER,
			subtitle_codec TEXT,
			subtitle_forced,
			subtitle_language TEXT,transcode_protocol TEXT,
			transcode_container TEXT,
			transcode_video_codec TEXT,
			transcode_audio_codec TEXT,
			transcode_audio_channels INTEGER,
			transcode_width INTEGER,
			transcode_height INTEGER,
			transcode_hw_requested INTEGER,
			transcode_hw_full_pipeline INTEGER,
			transcode_hw_decode TEXT,
			transcode_hw_decode_title TEXT,
			transcode_hw_decoding INTEGER,
			transcode_hw_encode TEXT,
			transcode_hw_encode_title TEXT,
			transcode_hw_encoding INTEGER,
			stream_container TEXT,
			stream_container_decision TEXT,
			stream_bitrate INTEGER,
			stream_video_decision TEXT,
			stream_video_bitrate INTEGER,
			stream_video_codec TEXT,
			stream_video_codec_level TEXT,
			stream_video_bit_depth INTEGER,
			stream_video_height INTEGER,
			stream_video_width INTEGER,
			stream_video_resolution TEXT,
			stream_video_framerate TEXT,
			stream_video_scan_type TEXT,
			stream_video_full_resolution TEXT,
			stream_video_dynamic_range TEXT,
			stream_audio_decision TEXT,
			stream_audio_codec TEXT,
			stream_audio_bitrate INTEGER,
			stream_audio_channels INTEGER,
			stream_audio_language TEXT,
			stream_audio_language_code TEXT,
			stream_subtitle_decision TEXT,
			stream_subtitle_codec TEXT,
			stream_subtitle_container TEXT,
			stream_subtitle_forced INTEGER,
			stream_subtitle_language TEXT,
			synced_version INTEGER,
			synced_version_profile TEXT,
			optimized_version INTEGER,
			optimized_version_profile TEXT,
            optimized_version_title TEXT
        );
        """,
        (),
    )
    db.execute(
        "CREATE INDEX if not exists idx_session_history_media_info_transcode_decision ON session_history_media_info (transcode_decision);",
        (),
    )
    db.execute("CREATE TABLE if not exists version_info (key TEXT UNIQUE, value TEXT);")
    db.execute("insert into version_info (key, value) values (?, ?)", ("version", "v2.15.2"))
    db.close()


def main(library_type: str | None = None):
    print("Fetch all plex users for easy lookup")
    plex_users = {u.id: u for u in PlexUser.fetch()}

    print("Fetch all the tautulli users to map plex users")
    tautulli_users = TautulliUser.fetch()
    tautulli_users_by_username = {t.username: t for t in tautulli_users}
    tautulli_users_by_user_id = {t.user_id: t for t in tautulli_users}

    print("Fetch all plex devices for easy lookup")
    devices = {d.id: d for d in PlexDevice.fetch()}

    media_items: dict[str, PlexMedia] = {}
    for hub in PlexHub.fetch(library_type):
        print(f"Hub [{hub.type}]: {hub.name!r}")
        for item in hub.collect():
            for m in item.tree():
                match m.type:
                    case "movie":
                        print(f"  {m.type}: {m.title!r} [rating_key={m.rating_key}]")
                    case "show":
                        print(f"  {m.type}: {m.title!r} [rating_key={m.rating_key}]")
                    case "season":
                        print(f"    {m.type}: {m.title!r} [rating_key={m.rating_key}]")
                    case "episode":
                        print(f"      {m.type}: {m.title!r} [rating_key={m.rating_key}]")
                    case "artist":
                        print(f"    {m.type}: {m.title!r} [rating_key={m.rating_key}]")
                    case "album":
                        print(f"      {m.type}: {m.title!r} [rating_key={m.rating_key}]")
                    case "track":
                        print(f"        {m.type}: {m.title!r} [rating_key={m.rating_key}]")
                media_items[m.rating_key] = m

    # For each session history entry
    inserts: list[tuple[PlexHistory, PlexMedia, PlexDevice, TautulliUser]] = []
    for hist in PlexHistory.fetch(library_type):
        match (library_type, hist.type):
            case (None, _):
                pass
            case ("artist", "artist" | "album" | "track"):
                pass
            case ("movie", "movie"):
                pass
            case ("show", "show" | "season" | "episode"):
                pass
            case (lib_type, hist_type):
                print(f"Skipping history item of type {hist_type} for library type {lib_type}")
                continue

        media = media_items.get(hist.rating_key)
        if media is None:
            print(f"Unable to find media for history entry {hist.key!r}, trying a fetch:")
            for page in paginated_get(hist.key):
                for item in page["MediaContainer"].get("Metadata", []):
                    match item["type"]:
                        case "movie" | "show":
                            m = PlexMedia.from_video_dict(item)
                        case "artist" | "album" | "track":
                            m = PlexMedia.from_audio_dict(item)
                        case type:
                            print(f"Unknown media type in fetched history item: {type}", file=sys.stderr)
                            continue
                    print(f"  Fetched media item: {m!r}")
                    media_items[m.rating_key] = m
                    if m.rating_key == hist.rating_key:
                        media = m

            if media is None:
                print("Still unable to find media, dumping info:")
                pprint(hist)
                print(sorted(media_items.keys(), key=int))
                resp = plex.get(f"{PLEX_URL}{hist.key}").json()
                if "MediaContainer" not in resp:
                    print("No MediaContainer in response!")
                    pprint(resp)
                    sys.exit(1)
                if resp["MediaContainer"].get("Metadata") is not None:
                    print("Media info from Plex:")
                    pprint(resp["MediaContainer"]["Metadata"][0])
                sys.exit(0)
        assert media is not None, f"Unable to find media for history {hist.history_key!r} with rating key {hist.rating_key!r}"

        # Find the matching device
        device = devices.get(hist.device_id)
        assert device is not None, f"Unable to find device for history {hist.history_key!r} with device ID {hist.device_id!r}"

        # Find the matching user and map to tautulli ID
        user = tautulli_users_by_user_id.get(hist.account_id)
        if user is None:
            plex_user = plex_users.get(hist.account_id)
            assert plex_user is not None, f"Unable to find plex user for history {hist.history_key!r} with account ID {hist.account_id!r}"
            tautulli_user = tautulli_users_by_username.get(plex_user.name)
            if tautulli_user is None:
                print(f"Unable to find user for {hist.title}, skipping")
                continue
            user = tautulli_user

        inserts.append((hist, media, device, user))

    print("Inserting history into database...")
    insert_history(inserts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert Plex watch history to Tautulli database import format")
    parser.add_argument(
        "--type",
        dest="library_type",
        choices=["movie", "show", "artist"],
        default=None,
        help="Filter libraries by type (movie, show, or artist). If not specified, all types are processed.",
    )
    args = parser.parse_args()

    print("Initializing database...")
    init_db()
    print("Initialized database.")
    main(library_type=args.library_type)
