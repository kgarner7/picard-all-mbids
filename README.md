# Picard All MBIDs

This is a plugin for Picard designed to add MBIDs for all other roles where possible (remixer, composer, label).
It tries to use the same naming convention as the original tags.

## Mappings

Standard Picard (see `picard/mbjson.py` / `ARTIST_REL_TYPES` for the list) tags are mapped to `musicbrainz_role_id`.

Performers (instrument, vocalist, other roles) are mapped to `musicbrainz_performer_id` as a multi-valued field.
Each item in the tag is in the form `artist-mbid (role)`, where `role` is **one** role.

For example, if an artist `A` has two roles, `piano` and `guitar`, you would have `musicbrainz_performer_id` be `A (piano); A (guitar)`.

Note: **For best results, please also use the Standardise Performers role**.
This will ensure that you have the same number of individual performers as performer IDs.
