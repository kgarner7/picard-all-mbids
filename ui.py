from picard.plugin3.api import OptionsPage, PluginApi

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QVBoxLayout, QCheckBox

__all__ = ["FETCH_ALL_ARTISTS", "USE_MBZ_TAG_NAMING", "register_options"]


FETCH_ALL_ARTISTS = "fetch_all_artists"
USE_MBZ_TAG_NAMING = "use_mbz_tag_naming"


class PluginOptionPage(OptionsPage):
    NAME = "picard_all_mbids"
    TITLE = "Picard additional role MBIDs"
    PARENT = "plugins"

    def __init__(self):
        super().__init__()
        self.use_picard_tag_format = QCheckBox(
            "Use Picard standard tag naming for extended tags (picard_labelid instead of picard_label_id)"
        )
        self.fetch_all_artists = QCheckBox(
            "Translate all artist roles. This will likely result in much longer processing time as additional artists have to be fetched to get translated names"
        )

        layout = QVBoxLayout(self)
        layout.addWidget(self.use_picard_tag_format)
        layout.addWidget(self.fetch_all_artists)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def load(self):
        self.use_picard_tag_format.setChecked(
            self.api.plugin_config[USE_MBZ_TAG_NAMING]
        )
        self.fetch_all_artists.setChecked(self.api.plugin_config[FETCH_ALL_ARTISTS])

    def save(self):
        self.api.plugin_config[USE_MBZ_TAG_NAMING] = (
            self.use_picard_tag_format.isChecked()
        )
        self.api.plugin_config[FETCH_ALL_ARTISTS] = self.fetch_all_artists.isChecked()


def register_options(api: "PluginApi"):
    api.plugin_config.register_option(
        USE_MBZ_TAG_NAMING,
        False,
        title="Use Picard standard tag naming for extended tags",
    )
    api.plugin_config.register_option(
        FETCH_ALL_ARTISTS, False, title="Fetch all artist names from MusicBrainz"
    )
    api.register_options_page(PluginOptionPage)
