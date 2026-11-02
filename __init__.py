from typing import Callable, Dict, List, Optional, Set, Tuple

from collections import defaultdict, OrderedDict
from functools import partial
from json import load, loads


from picard.mbjson import artist_credit_from_node
from picard.plugin3.api import (
    Album,
    Metadata,
    PluginApi,
    Track,
)
from picard.util import thread

from PyQt6.QtCore import QStandardPaths

from .consts import *
from .db import DB
from .ui import register_options

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

# For whatever reason, forward/reverse have different meanings per key.
# This plugin intends for forward to mean recording A has <relation> recording B
# and for backward to mean that recording A is a <relation> of recoding B
# For relations where this is not the case, the first field will be True signifying
# that it is inverted
RECORDING_RELATION_KEYS: Dict[str, Tuple[bool, str]] = {
    "a cappella": (False, "acappella"),
    "instrumental": (False, "instrumental"),
    "karaoke": (False, "karaoke"),
    "remix": (True, "remix"),
    "samples material": (True, "samples"),
}


ARTIST_CACHE: Dict[str, str] = {}


def process_relations(
    api: "PluginApi",
    relations: Dict[str, Dict[str, Optional[str]]],
    performers: Dict[str, List[str]],
    data: List[dict],
) -> None:
    api.mb_api.get_release_by_id
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
        reltype = relation["type"]

        if relation["target-type"] == "artist" and "artist" in relation:
            attributes = relation.get("attributes", [])

            id = relation["artist"]["id"]

            if id in ARTIST_CACHE:
                name = ARTIST_CACHE[id]
            else:
                # If we aren't fetching all alias names, still fall back
                # to possibly using the artist sort name where applicable
                node = {
                    "artist": relation["artist"],
                    "name": relation["artist"]["name"],
                }
                name = artist_credit_from_node([node]).names[0]

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
            and reltype == "performance"
        ):
            if "relations" in relation["work"]:
                process_relations(
                    api, relations, performers, relation["work"]["relations"]
                )
        elif (
            relation["target-type"] == "recording"
            and "recording" in relation
            and reltype in RECORDING_RELATION_KEYS
        ):
            is_inverted, rel_key = RECORDING_RELATION_KEYS[reltype]
            if is_inverted:
                is_forward = relation["direction"] == "backward"
            else:
                is_forward = relation["direction"] == "forward"

            if (is_forward and api.plugin_config[FORWARD_RECORDING_RELS]) or (
                not is_forward and api.plugin_config[BACKWARD_RECORDING_RELS]
            ):

                key = f"has{rel_key}" if is_forward else f"{rel_key}of"
                relations[key][relation["recording"]["id"]] = None


def add_all_mbids(
    api: "PluginApi", tagger: "Track", metadata: "Metadata", track: dict, release: dict
) -> None:

    # This is an OrderedDict in the event that the release AND
    # recording have the same artist. Deduplicate there.
    # I have no idea how likely that is, but I'm not taking chances there.
    relations: Dict[str, Dict[str, str | None]] = defaultdict(OrderedDict)
    performers: Dict[str, List[str]] = defaultdict(list)

    # The order appears to be process release attributes first, then recording attributes
    if release and "relations" in release:
        process_relations(api, relations, performers, release["relations"])

    if "recording" in track and "relations" in track["recording"]:
        process_relations(api, relations, performers, track["recording"]["relations"])

    sep = "" if api.plugin_config[USE_MBZ_TAG_NAMING] else "_"

    for relation, ids in relations.items():
        key = f"musicbrainz_{relation}{sep}id"
        mbids = list(ids)
        metadata[key] = mbids

        # Some items return "None" for the value; this is for fields which are processed in a special way
        # Currently this is:
        #   - Performers: they are grouped under one field in the performers block
        #   - Recordings (forward and backwards): only the mbid is included
        if ids[mbids[0]] != None:
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
    should_cache = DB.is_db_enabled()

    for artist in item["artist-credit"]:
        id = artist["artist"]["id"]
        if id not in ARTIST_CACHE:
            if should_cache:
                DB.cache_artist_info(id, artist)

            ARTIST_CACHE[id] = artist_credit_from_node([artist]).names[0]


def get_untranslated_artists_mbids(
    data: List[dict],
    missing_artist_ids: Set[str],
) -> Set[str]:
    for relation in data:
        reltype = relation["type"]

        if relation["target-type"] == "artist" and "artist" in relation:
            id = relation["artist"]["id"]

            if (
                reltype in MAPPED_KEYS
                or reltype in PERFORMER_MAP
                or reltype in ARTIST_REL_TYPES
            ):
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
            nested = get_untranslated_artists_mbids(
                relation["work"]["relations"],
                missing_artist_ids,
            )

    return missing_artist_ids


def process_artist(
    api: "PluginApi",
    album: "Album",
    idx: int,
    total: int,
    mbid: str,
    artist,
    http,
    error,
):
    try:
        api.tagger.window.set_statusbar_message(
            f"Processed artist {idx + 1} / {total} of {album.id}"
        )

        if error:
            api.logger.error(f"Failed to retrieve artist {http.errorstring()}")
            return

        payload = {"artist": artist, "name": artist["name"]}
        name = artist_credit_from_node([payload]).names[0]
        ARTIST_CACHE[artist["id"]] = name

        if DB.is_db_enabled():
            DB.cache_artist_info(mbid, payload)
    finally:
        api.complete_album_task(album, mbid)

        # Workaround for PICARD-3513. Basically, implement the same behavior if the fix is not in place, gated over the presence of the internal function
        if not hasattr(album, "try_finalize_loading"):
            if not album.loaded and not album.has_critical_tasks():
                thread.to_main(album._finalize_loading, False)


def fetch_artist_translations(
    api: "PluginApi", album: "Album", metadata: dict, release: dict
):
    if not api.plugin_config[FETCH_ALL_ARTISTS]:
        return

    process_artist_credits(release)

    for media in release["media"]:
        for track in media["tracks"]:
            process_artist_credits(track)

    missing = get_untranslated_artists_mbids(release["relations"], set())

    for media in release["media"]:
        for track in media["tracks"]:
            get_untranslated_artists_mbids(track["recording"]["relations"], missing)

    total_missing = len(missing)

    for idx, mbid in enumerate(missing):

        def fetch_artist_factory():
            return api.mb_api._get_by_id(
                "artist",
                mbid,
                handler=partial(process_artist, api, album, idx, total_missing, mbid),
                inc=["aliases"],
            )

        api.add_album_task(
            album,
            mbid,
            f"finalize artist {mbid}",
            request_factory=fetch_artist_factory,
            blocking=True,
        )


def enable(api: "PluginApi"):
    """Called when plugin is enabled."""
    register_options(api)

    DB.init_singleton(api)
    cached_items = DB.initialize_db(return_items=True)

    if cached_items:
        for id, body in cached_items:
            ARTIST_CACHE[id] = artist_credit_from_node([loads(body)]).names[0]

    api.register_album_metadata_processor(fetch_artist_translations)
    api.register_track_metadata_processor(add_all_mbids, priority=-100)
