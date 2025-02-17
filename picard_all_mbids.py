PLUGIN_NAME = "Add Other role MBIDs"
PLUGIN_AUTHOR = "Kendall Garner"
PLUGIN_DESCRIPTION = """
This plugin is to add MBIDs for other roles (composer, remixer, label ,etc.).
This will also normalize performer roles so everything is in the form performer:individual role
"""
PLUGIN_VERSION = "0.1"
PLUGIN_API_VERSIONS = [
    "2.2",
    "2.3",
    "2.4",
    "2.5",
    "2.6",
    "2.7",
    "2.8",
    "2.9",
    "2.10",
    "2.11",
    "2.12",
]
PLUGIN_LICENSE = ["MIT"]
PLUGIN_LICENSE_URL = "https://opensource.org/license/MIT"

from typing import Dict, List
from collections import defaultdict, OrderedDict

from picard.config import Config, get_config
from picard.metadata import Metadata, register_track_metadata_processor
from picard.plugin import PluginPriority

try:
    # We want to respect translation as much as possible. If Picard
    # changes, then this needs to be fixed
    from picard.mbjson import _translate_artist_node
except:

    def _translate_artist_node(artist: dict, _: "Config"):
        return (artist["name"], artist["sort-name"])


def get_translated_name(relation: dict, config: "Config") -> str:
    """
    The following is to get the consistent naming that Picard
    for performer roles. We have to manually order these
    properly, because Picard will by default combine
    multiple separate performer/instrument credits for an artist
    into one tag (e.g., (vocals and flute)). We want
    individual artist (role) pairs. See _relations_to_metadata_target_type_artist
    implementation.
    """

    use_credited_as = not config.setting["standardize_artists"]

    artist = relation["artist"]
    translated_name = _translate_artist_node(artist, config)[0]
    has_translation = translated_name != artist["name"]

    if not has_translation and use_credited_as and "target-credit" in relation:
        if relation["target-credit"]:
            return relation["target-credit"]

    return translated_name


PERFORMER_KEY = "performer"

# Taken from picard/mbjson.py (release-2.12.3, 2c1c30e6ccba886270cb49aed6d0329e114763da)
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
    # 'mastering': 'engineer',
    "mix-DJ": "djmixer",
    "mix": "mixer",
    "orchestrator": "arranger",
    "producer": "producer",
    # "recording": "recording engineer",
    "remixer": "remixer",
    "sound": "engineer",
    "audio director": "director",
    "video director": "director",
    "vocal arranger": "arranger",
    "writer": "writer",
}

PERFORMER_MAP = {
    "chorus master": "chorus master",
    "concertmaster": "concertmaster",
    "performing orchestra": "orchestra",
}


MAPPED_KEYS = {"instrument": "instrument", "performer": "performer", "vocal": "vocals"}


PERFORMER_PREFIX = {"additional", "guest", "minor", "solo"}


def process_relations(
    relations: Dict[str, OrderedDict[str, None]],
    performers: Dict[str, List[str]],
    data: List[dict],
    config: "Config",
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

            if reltype in MAPPED_KEYS:
                # This is a type which may have multiple attributes (roles)
                # for the same artist. In this case, append each one in order
                # If no special attribute, used the mapped key name
                name = get_translated_name(relation, config)

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
                name = get_translated_name(relation, config)

                # These are also of type performer, but no special attribute
                # Still, put them in the performer key
                mapped_name = PERFORMER_MAP.get(reltype)
                id_role = f"{id} ({mapped_name})"

                if id_role not in relations[PERFORMER_KEY]:
                    relations[PERFORMER_KEY][id_role] = None
                    performers[mapped_name].append(name)
            else:
                # A standard key (hopefully). If it doesn't exist, don't
                # include it.
                key = ARTIST_REL_TYPES.get(reltype)
                if key:
                    if id not in relations[key]:
                        relations[key][id] = None
        elif (
            relation["target-type"] == "work"
            and "work" in relation
            # This is what Picard does internally. Not sure why, but I'll keep it for now.
            and relation["type"] == "performance"
        ):
            if "relations" in relation["work"]:
                process_relations(
                    relations, performers, relation["work"]["relations"], config
                )


def add_all_mbids(_tagger, metadata: "Metadata", track: dict, release: dict) -> None:
    # This is an OrderedDict in the event that the release AND
    # recording have the same artist. Deduplicate there.
    # I have no idea how likely that is, but I'm not taking chances there.
    relations: Dict[str, OrderedDict[str, None]] = defaultdict(OrderedDict)
    performers: Dict[str, List[str]] = defaultdict(list)
    config = get_config()

    # The order appears to be process release attributes first, then recording attributes
    if release and "relations" in release:
        process_relations(relations, performers, release["relations"], config)

    if "recording" in track:
        if "relations" in track["recording"]:
            process_relations(
                relations, performers, track["recording"]["relations"], config
            )

    for relation, ids in relations.items():
        key = f"musicbrainz_{relation}_id"
        metadata[key] = list(ids)

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

        metadata["musicbrainz_label_id"] = label_ids

    for key in list(metadata):
        if key.startswith("performer:") or key == "performer":
            del metadata[key]

    for role, artists in performers.items():
        key = f"performer:{role}" if role else "performer"
        metadata[key] = artists


register_track_metadata_processor(add_all_mbids, priority=PluginPriority.LOW)
