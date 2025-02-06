PLUGIN_NAME = "Add Other role MBIDs"
PLUGIN_AUTHOR = "Kendall Garner"
PLUGIN_DESCRIPTION = """
This plugin is to add MBIDs for other roles (composer, remixer, label ,etc.)
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

from picard.metadata import Metadata, register_track_metadata_processor

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


def process_relations(
    relations: Dict[str, OrderedDict[str, None]], data: List[dict]
) -> None:
    for relation in data:
        if relation["target-type"] == "artist" and "artist" in relation:
            reltype = relation["type"]
            attributes = relation.get("attributes", [])

            id = relation["artist"]["id"]

            if reltype in MAPPED_KEYS:
                # This is a type which may have multiple attributes (roles)
                # for the same artist. In this case, append each one in order
                # If no special attribute, used the mapped key name

                if not attributes:
                    if reltype == "performer":
                        relations[PERFORMER_KEY][id] = None
                        continue

                    attributes = [MAPPED_KEYS[reltype]]

                for attribute in attributes:
                    id_role = f"{id} ({attribute})"

                    if id_role not in relations[PERFORMER_KEY]:
                        relations[PERFORMER_KEY][id_role] = None
            elif reltype in PERFORMER_MAP:
                # These are also of type performer, but no special attribute
                # Still, put them in the performer key
                mapped_name = PERFORMER_MAP.get(reltype)
                id_role = f"{id} ({mapped_name})"

                if id_role not in relations[PERFORMER_KEY]:
                    relations[PERFORMER_KEY][id_role] = None
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
                process_relations(relations, relation["work"]["relations"])


def add_all_mbids(_tagger, metadata: "Metadata", track: dict, release: dict) -> None:
    # This is an OrderedDict in the event that the release AND
    # recording have the same artist. Deduplicate there.
    # I have no idea how likely that is, but I'm not taking chances there.
    relations: Dict[str, OrderedDict[str, None]] = defaultdict(OrderedDict)

    # The order appears to be process release attributes first, then recording attributes
    if "relations" in release:
        process_relations(relations, release["relations"])

    if "recording" in track:
        if "relations" in track["recording"]:
            process_relations(relations, track["recording"]["relations"])

    for relation, ids in relations.items():
        key = f"musicbrainz_{relation}_id"
        metadata[key] = list(ids)

    if "label-info" in release:
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


register_track_metadata_processor(add_all_mbids)
