from json import dumps
from os import makedirs
from os.path import dirname
from sqlite3 import connect, Connection
from threading import Lock
from time import time

from picard.plugin3.api import PluginApi

from .consts import *

DAY_IN_SECONDS = 24 * 60 * 60


class DB:
    api: PluginApi | None = None
    conn: Connection | None = None
    lock = Lock()

    @classmethod
    def init_singleton(cls, api: "PluginAPi"):
        cls.api = api

    @classmethod
    def initialize_db(cls, return_items=False):
        with cls.lock:
            try:
                if cls.conn:
                    cls.conn.close()
                    cls.conn = None

                if not cls.is_db_enabled():
                    return None

                file = cls.api.plugin_config[CACHE_FILE]
                base_dir = dirname(file)
                makedirs(base_dir, exist_ok=True)

                cls.conn = connect(file, check_same_thread=False)

                with cls.conn as c:
                    c.execute(
                        """
                        CREATE TABLE IF NOT EXISTS artists(
                            mbid TEXT PRIMARY KEY NOT NULL,
                            updated DATETIME NOT NULL,
                            contents JSONB NOT NULL
                        );
                        """
                    )

                    if cls.api.plugin_config[CACHE_DAYS] > 0:
                        expiry_time = cls.api.plugin_config[CACHE_DAYS] * DAY_IN_SECONDS

                        c.execute(
                            "DELETE FROM artists WHERE updated < ?",
                            (time() - expiry_time,),
                        )

                if return_items:
                    with cls.conn as c:
                        cursor = c.execute("SELECT mbid, contents FROM artists")
                        results = cursor.fetchall()
                        cursor.close()
                        return results

                return None

            except BaseException as e:
                cls.conn = None
                cls.api.logger.exception("Failed to open database", exc_info=e)
                return None

    @classmethod
    def is_db_enabled(cls):
        conf = cls.api.plugin_config
        return conf[FETCH_ALL_ARTISTS] and conf[CACHE_ARTIST_INFO]

    @classmethod
    def cache_artist_info(cls, mbid: str, info: dict):
        with cls.lock:
            if not cls.conn:
                return

            with cls.conn as c:
                c.execute(
                    "INSERT OR REPLACE INTO artists (mbid, updated, contents) VALUES(?, ?, ?)",
                    (mbid, time(), dumps(info, separators=(",", ":"))),
                )
