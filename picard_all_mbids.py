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
from collections import defaultdict

from picard import log
from picard.metadata import Metadata, register_track_metadata_processor

try:
    from picard.mbjson import _ARTIST_REL_TYPES as ARTIST_REL_TYPES
except:
    try:
        from picard.mbjson import _artist_rel_types as ARTIST_REL_TYPES
    except:
        log.warning(
            "This version of Picard has no ARTIST_REL_TYPES. Assuming an empty object"
        )
        ARTIST_REL_TYPES = {}


def process_relations(relations: Dict[str, List[str]], data: List[dict]) -> None:
    for relation in data:
        if relation["target-type"] == "artist" and "artist" in relation:
            if relation["attributes"]:
                key = (
                    relation["type"]
                    + ":"
                    + ":".join(item.capitalize() for item in relation["attributes"])
                )
            else:
                key = relation["type"]

            target_type = ARTIST_REL_TYPES.get(key, key).capitalize()
            relations[target_type].append(relation["artist"]["id"])
        elif (
            relation["target-type"] == "work"
            and "work" in relation
            # This is what Picard does internally. Not sure why, but I'll keep it for now.
            and relation["type"] == "performance"
        ):
            if "relations" in relation["work"]:
                process_relations(relations, relation["work"]["relations"])


def add_all_mbids(tagger, metadata: "Metadata", track: dict, release: dict) -> None:
    if "recording" in track:
        if "relations" in track["recording"]:
            relations: Dict[str, List[str]] = defaultdict(list)
            process_relations(relations, track["recording"]["relations"])

            for relation, ids in relations.items():
                metadata[f"MusicBrainz {relation} Id"] = ids

    if "label-info" in release:
        label_ids = [
            label["label"]["id"]
            for label in release["label-info"]
            if label and "label" in label and "id" in label["label"]
        ]
        metadata["MusicBrainz Label Id"] = label_ids


register_track_metadata_processor(add_all_mbids)
