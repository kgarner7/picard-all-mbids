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


MAPPED_KEYS = {"instrument", "performer"}


def process_relations(relations: Dict[str, List[str]], data: List[dict]) -> None:
    for relation in data:
        if relation["target-type"] == "artist" and "artist" in relation:
            reltype = relation["type"]
            attributes = relation.get("attributes", [])

            if reltype == "recording":
                key = "recording_engineer"
            elif reltype == "vocal":
                if attributes:
                    key = "performer_" + attributes[0].replace(" ", "_")
                else:
                    key = "performer_vocals"
            elif reltype in MAPPED_KEYS:
                key = "performer"
                if attributes:
                    key += "_" + attributes[0].replace(" ", "_")
                else:
                    key += "_general"
            else:
                key = ARTIST_REL_TYPES.get(reltype, reltype).replace(" ", "_")

            id = relation["artist"]["id"]
            target_relation = relations[key]

            if id not in target_relation:
                target_relation.append(id)
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
                key = f"musicbrainz_{relation}_id"
                metadata[key] = ids

    if "label-info" in release:
        seen_labels = set()
        label_ids = []

        for label in release["label-info"]:
            if label and "label" in label and label["label"] and label["label"]["id"]:
                id = label["label"]["id"]
                if id not in seen_labels:
                    label_ids.append(id)
                    seen_labels.add(id)

        metadata["musicbrainz_label_id"] = label_ids


register_track_metadata_processor(add_all_mbids)
