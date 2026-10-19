from typing import Callable, Dict, List, Optional, Set, Tuple

from collections import defaultdict, OrderedDict
from functools import partial
from json import load
from time import sleep, time
from urllib.request import urlopen

from picard.mbjson import artist_credit_from_node
from picard.plugin3.api import (
    Album,
    Metadata,
    PluginApi,
    Track,
)
from picard.webservice import WSRequest


from .ui import FETCH_ALL_ARTISTS, USE_MBZ_TAG_NAMING, register_options

# Note that MBZ does one request per second limit. Add 20% extra time
# To be careful not to get close
MBZ_REQUEST_DELAY = 1.2

PERFORMER_KEY = "performer"

# Adapted from picard/mbjson.py (release-2.12.3, 2c1c30e6ccba886270cb49aed6d0329e114763da)
ARTIST_REL_TYPES = {
    "arranger": "arranger",
    "audio": "engineer",
    "composer": "composer",
    "conductor": "conductor",
    "engineer": "engineer",
    "instrument arranger": "arranger",
    "librettist": "lyricist",
    "live sound": "engineer",
    "lyricist": "lyricist",
    "mix-DJ": "djmixer",
    "mix": "mixer",
    "orchestrator": "arranger",
    "producer": "producer",
    "remixer": "remixer",
    "sound": "engineer",
    "audio director": "director",
    "video director": "director",
    "vocal arranger": "arranger",
    "writer": "writer",
    # Additional fields
    "mastering": "mastering",
}


PERFORMER_MAP = {
    "chorus master": "chorus master",
    "concertmaster": "concertmaster",
    "performing orchestra": "orchestra",
}
PERFORMER_PREFIX = {"additional", "guest", "minor", "solo"}


MAPPED_KEYS = {"instrument": "instrument", "performer": "performer", "vocal": "vocals"}


ARTIST_CACHE: Dict[str, str] = {}


def process_relations(
    relations: Dict[str, Dict[str, Optional[str]]],
    performers: Dict[str, List[str]],
    data: List[dict],
) -> None:
    """
    Process a list of relations in order of their appearance, and fill in the
    role:mbid mapping, in the order of appearance in the MusicBrainz data.

    Additionally, because Picard normally maps multiple performer credits
    to one field (e.g., "vocals and guitar"), the performer is split into
    sub role:artist names. Great effort is done to preserve translations
    as they are done in Picard, normally.

    Arguments:
    - relations: a persistent mapping of roles to their mbids. mbids is an ordered dict (to be an ordered set)
    - performers: a persistent mapping of performer subroles to artist names
    - data: the JSON relations to be parsed. A list of "relations" (of interest, artist or work)
    """

    for relation in data:
        if relation["target-type"] == "artist" and "artist" in relation:
            reltype = relation["type"]
            attributes = relation.get("attributes", [])

            id = relation["artist"]["id"]
            name = ARTIST_CACHE.get(id, relation["artist"]["name"])

            if reltype in MAPPED_KEYS:
                # This is a type which may have multiple attributes (roles)
                # for the same artist. In this case, append each one in order
                # If no special attribute, used the mapped key name

                performer_map = relations[PERFORMER_KEY]

                prefixes = []

                if attributes:
                    # If we have attributes, they may be augmenting the role
                    # In this case, remove all prefix attributes from the list
                    # and save it as a prefix to append to each key
                    for word in attributes[:]:
                        if word in PERFORMER_PREFIX:
                            attributes.remove(word)
                            prefixes.append(word)

                if not attributes:
                    if reltype == "performer":
                        if id not in performer_map:
                            performers[""].append(name)
                            performer_map[id] = None
                        continue

                    attributes = [MAPPED_KEYS[reltype]]

                prefix_string = ", ".join(prefixes) + " " if prefixes else ""

                for attribute in attributes:
                    role = prefix_string + attribute
                    id_role = f"{id} ({role})"

                    if id_role not in performer_map:
                        performers[role].append(name)
                        performer_map[id_role] = None

            elif reltype in PERFORMER_MAP:
                # These are also of type performer, but no special attribute
                # Still, put them in the performer key
                mapped_name = PERFORMER_MAP[reltype]
                id_role = f"{id} ({mapped_name})"

                if id_role not in relations[PERFORMER_KEY]:
                    relations[PERFORMER_KEY][id_role] = None
                    performers[mapped_name].append(name)
            else:
                # A standard key (hopefully). If it doesn't exist, don't
                # include it.
                key = ARTIST_REL_TYPES.get(reltype)
                if key and id not in relations[key]:
                    relations[key][id] = name
        elif (
            relation["target-type"] == "work"
            and "work" in relation
            # This is what Picard does internally. Not sure why, but I'll keep it for now.
            and relation["type"] == "performance"
        ):
            if "relations" in relation["work"]:
                process_relations(relations, performers, relation["work"]["relations"])


def add_all_mbids(
    api: "PluginApi", tagger: "Track", metadata: "Metadata", track: dict, release: dict
) -> None:

    if not api.plugin_config[FETCH_ALL_ARTISTS]:
        return

    # This is an OrderedDict in the event that the release AND
    # recording have the same artist. Deduplicate there.
    # I have no idea how likely that is, but I'm not taking chances there.
    relations: Dict[str, Dict[str, str]] = defaultdict(OrderedDict)
    performers: Dict[str, List[str]] = defaultdict(list)

    # The order appears to be process release attributes first, then recording attributes
    if release and "relations" in release:
        process_relations(relations, performers, release["relations"])

    if "recording" in track and "relations" in track["recording"]:
        process_relations(relations, performers, track["recording"]["relations"])

    sep = "" if api.plugin_config[USE_MBZ_TAG_NAMING] else "_"

    for relation, ids in relations.items():
        key = f"musicbrainz_{relation}{sep}id"
        metadata[key] = list(ids)

        # Override the existing relation credits with translated name (if available)
        # or just the roles in order. Note that we group all performer roles under one item
        # mbz_performer*id rather than individual roles
        if not relation.startswith("performer"):
            metadata[relation] = list(ids.values())

    if release and "label-info" in release:
        seen_labels = set()
        label_ids = []

        # Ignore duplicates, and only pick the first instance of the label
        # as the position
        for label in release["label-info"]:
            if label and "label" in label and label["label"] and label["label"]["id"]:
                id = label["label"]["id"]
                if id not in seen_labels:
                    label_ids.append(id)
                    seen_labels.add(id)

        metadata[f"musicbrainz_label{sep}id"] = label_ids

    # performers are different, we need to handle those regardless, and do it in sub role
    for key in list(metadata):
        if key.startswith("performer:") or key == "performer":
            del metadata[key]

    for role, artists in performers.items():
        key = f"performer:{role}" if role else "performer"
        metadata[key] = artists


def process_artist_credits(item: dict):
    for artist in item["artist-credit"]:
        id = artist["artist"]["id"]
        if id not in ARTIST_CACHE:
            ARTIST_CACHE[id] = artist_credit_from_node([artist]).names[0]


def get_untranslated_artists_mbids(
    data: List[dict],
    missing_artist_ids: Set[str] = set(),
) -> Tuple[Set[str], Set[str]]:
    for relation in data:
        if relation["target-type"] == "artist" and "artist" in relation:
            reltype = relation["type"]
            id = relation["artist"]["id"]

            if reltype in MAPPED_KEYS or reltype in PERFORMER_MAP:
                if id in missing_artist_ids:
                    continue

                if id not in ARTIST_CACHE:
                    missing_artist_ids.add(id)
            elif (
                relation["target-type"] == "work"
                and "work" in relation
                # This is what Picard does internally. Not sure why, but I'll keep it for now.
                and reltype == "performance"
                and "relations" in relation["work"]
            ):
                nested = untranslated_artists(
                    relation["work"]["relations"],
                    missing_artist_ids,
                )

    return missing_artist_ids


def fetch_artist(api: "PluginApi", mbid: str, retries=5):
    """
    This implementation is terrible, but
    """
    url = api.mb_api.url_from_path(f"/artist/{mbid}")
    path = url.toString() + "?fmt=json&inc=aliases"

    for attempt in range(retries):
        now = time()
        try:
            with urlopen(path) as r:
                artist = load(r)

            payload = [{"artist": artist, "name": artist["name"]}]
            return artist_credit_from_node(payload).names[0]
        except BaseException as e:
            api.logger.exception(
                f"Failed to fetch artist aliases, attempt={attempt}", exc_info=e
            )
        finally:
            elapsed = time() - now
            if elapsed > 0:
                sleep(1.5 - elapsed)


def fetch_artist_translations(
    api: "PluginApi", album: "Album", metadata: dict, release: dict
):
    if not api.plugin_config[FETCH_ALL_ARTISTS]:
        return

    process_artist_credits(release)

    for media in release["media"]:
        for track in media["tracks"]:
            process_artist_credits(track)

    missing = get_untranslated_artists_mbids(release["relations"])

    for media in release["media"]:
        for track in media["tracks"]:
            get_untranslated_artists_mbids(track["recording"]["relations"], missing)

    # The following code is NOT good, as it blocks the UI until it is done
    # But, the proper code (background requests) doesn't work right now (3.0.2)
    # as it looks like complete_album_task (or `api`) is not thread-safe,
    # so the album would never finish
    for idx, mbid in enumerate(missing):
        api.logger.debug(
            f"Fetching artist {idx}/{len(missing)} ({mbid}) for {album.id}"
        )
        name = fetch_artist(api, mbid)
        if name:
            ARTIST_CACHE[mbid] = name

    # NOTE: the following code **WILL NOT WORK** because `api` is not threadsafe
    # Attempting to call `complete_album_task` in another thread will in fact still block the UI

    # for mbid in missing:
    #     print("registering task", album, mbid)

    #     def fetch_artist_factory():
    #         return api.mb_api._get_by_id(
    #             "artist",
    #             mbid,
    #             handler=partial(process_artist, api, album, mbid),
    #             inc=["aliases"],
    #         )

    #     print(mbid)

    #     api.add_album_task(
    #         album,
    #         mbid,
    #         "finalize artist",
    #         request_factory=fetch_artist_factory,
    #         timeout=5,
    #     )


# def process_artist(
#     api: "PluginApi",
#     album: "Album",
#     mbid: str,
#     artist,
#     http,
#     error,
# ):
#     try:
#         if error:
#             print("error", http.errorString())
#             return

#         payload = [{"artist": artist, "name": artist["name"]}]
#         name = artist_credit_from_node(payload).names[0]
#         ARTIST_CACHE[artist["id"]] = name
#     finally:
#         api.complete_album_task(album, mbid)
#         semaphore.release()


def enable(api: "PluginApi"):
    """Called when plugin is enabled."""
    api.register_album_metadata_processor(fetch_artist_translations)
    api.register_track_metadata_processor(add_all_mbids, priority=-100)
    register_options(api)
