from os.path import join

from picard.plugin3.api import OptionsPage, PluginApi

from PyQt6.QtCore import QStandardPaths, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from .consts import *
from .db import DB

__all__ = ["register_options"]


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
        self.cache_artist_info = QCheckBox("Cache artist info")

        self.layout = QVBoxLayout(self)
        self.layout.addWidget(self.use_picard_tag_format)
        self.layout.addWidget(self.fetch_all_artists)
        self.layout.addWidget(self.cache_artist_info)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.file_group = QHBoxLayout()

        self.file_label = QLabel("File:")
        self.cache_file = QLineEdit()

        self.file_group.addWidget(self.file_label)
        self.file_group.addWidget(self.cache_file)

        self.layout.addLayout(self.file_group)

        self.fetch_all_artists.stateChanged.connect(self._toggle_fetch_artists)
        self.cache_artist_info.stateChanged.connect(self._toggle_fetch_artists)

    def load(self):
        self.use_picard_tag_format.setChecked(
            self.api.plugin_config[USE_MBZ_TAG_NAMING]
        )
        self.fetch_all_artists.setChecked(self.api.plugin_config[FETCH_ALL_ARTISTS])
        self.cache_artist_info.setChecked(self.api.plugin_config[CACHE_ARTIST_INFO])
        self.cache_file.setText(self.api.plugin_config[CACHE_FILE])

    def save(self):
        self.api.plugin_config[USE_MBZ_TAG_NAMING] = (
            self.use_picard_tag_format.isChecked()
        )
        self.api.plugin_config[FETCH_ALL_ARTISTS] = self.fetch_all_artists.isChecked()
        self.api.plugin_config[CACHE_ARTIST_INFO] = self.cache_artist_info.isChecked()
        self.api.plugin_config[CACHE_FILE] = self.cache_file.text()

    def _toggle_fetch_artists(self):
        can_fetch = self.fetch_all_artists.isChecked()
        can_cache = self.cache_artist_info.isChecked()

        self.cache_artist_info.setEnabled(can_fetch)
        self.cache_file.setEnabled(can_cache and can_fetch)

        DB.initialize_db()


def register_options(api: "PluginApi"):
    base_dir = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    default_cache_dir = join(base_dir, "artist_info_cache.db")

    api.plugin_config.register_option(
        USE_MBZ_TAG_NAMING,
        False,
        title="Use Picard standard tag naming for extended tags",
    )
    api.plugin_config.register_option(
        FETCH_ALL_ARTISTS, False, title="Fetch all artist names from MusicBrainz"
    )
    api.plugin_config.register_option(
        CACHE_ARTIST_INFO, True, title="Cache artist info"
    )
    api.plugin_config.register_option(
        CACHE_FILE, default_cache_dir, title="Path to artist cache database"
    )
    api.register_options_page(PluginOptionPage)
