from gi.repository import GLib
from pydbus import SessionBus
from spotipy import Spotify
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError
from appdirs import AppDirs
from configparser import ConfigParser
from pkgutil import get_data

from .BusManager import SingleBusManager, MultiBusManager
from . import MediaPlayer2
import argparse
import os

ifaces = ["org.mpris.MediaPlayer2",
          "org.mpris.MediaPlayer2.Player"]  # , "org.mpris.MediaPlayer2.Playlists", "org.mpris.MediaPlayer2.TrackList"]
dirs = AppDirs("spotpris2", "freundTech")
scope = "user-modify-playback-state,user-read-playback-state,user-read-currently-playing"
redirect_uri = "http://127.0.0.1:8000"


def _load_mpris_interfaces():
    return [get_data("spotpris2", f"mpris/{iface}.xml").decode("utf-8")
            for iface in ifaces]


def main():
    parser = argparse.ArgumentParser(description="Control Spotify Connect devices using MPRIS2")
    parser.add_argument('-d', '--devices', nargs='+', metavar="DEVICE",
                        help="Only create interfaces for the listed devices")
    parser.add_argument('-i', '--ignore', nargs='+', metavar="DEVICE", help="Ignore the listed devices")
    parser.add_argument('-a', '--auto', action="store_true", help="Automatically control the active device")
    parser.add_argument('-l', '--list', nargs='?', choices=["name", "id"], const="name",
                        help="List available devices and exit")
    parser.add_argument('-s', '--steal-bus', action="store_true", help="Steal the dbus bus name from spotify to prevent "
                        "it from also offering an MPRIS2 interface. If --auto is used use the spotify bus name as own "
                        "bus name (experimental)")
    args = parser.parse_args()

    MediaPlayer2.dbus = _load_mpris_interfaces()

    loop = GLib.MainLoop()

    oauth = authenticate()
    sp = Spotify(oauth_manager=oauth)

    if args.list:
        devices = sp.devices()
        for devices in devices["devices"]:
            print(devices[args.list])
        return

    exclusive_count = 0
    for arg in [args.devices, args.ignore, args.auto]:
        if arg:
            exclusive_count += 1
    if exclusive_count >= 2:
        parser.error("Only one of --devices, --ignore and --auto can be used at the same time")
        return

    if args.steal_bus:
        bus = SessionBus()
        try:
            # This sets the bus name for the SessionBus singleton which is also used by SingleBusManager
            bus.request_name("org.mpris.MediaPlayer2.spotify", allow_replacement=False, replace=True)
        except RuntimeError:
            print("Failed to steal spotify bus name. You need to start spotPRIS2 before spotify")
            exit(1)

    if not args.auto:
        manager = MultiBusManager(sp, args.devices, args.ignore)
    else:
        if args.steal_bus:
            manager = SingleBusManager(sp, bus=bus)
        else:
            manager = SingleBusManager(sp)

    def timeout_handler():
        try:
            manager.main_loop()
        except Exception as e:
            print(e)
        finally:
            return True

    GLib.timeout_add_seconds(1, timeout_handler)

    try:
        loop.run()
    except KeyboardInterrupt:
        pass


class ReauthorizingSpotifyOAuth(SpotifyOAuth):
    """Start a fresh authorization flow when a cached grant is revoked."""

    def validate_token(self, token_info):
        try:
            return super().validate_token(token_info)
        except SpotifyOauthError as error:
            if not _is_invalid_grant(error):
                raise

            print("Spotify authorization has expired or was revoked. "
                  "Starting a new authorization flow.")
            _remove_cached_token(self.cache_handler)
            return None


def authenticate():
    config = get_config()
    cache_handler = CacheFileHandler(cache_path=dirs.user_cache_dir)

    oauth = ReauthorizingSpotifyOAuth(
        client_id=config["client_id"],
        client_secret=config["client_secret"],
        redirect_uri=redirect_uri,
        scope=scope,
        cache_handler=cache_handler,
    )

    token_info = oauth.validate_token(cache_handler.get_cached_token())

    if not token_info:
        # SpotifyOAuth opens the browser, receives the loopback callback, and
        # persists the resulting token through the configured cache handler.
        oauth.get_access_token(as_dict=False, check_cache=False)
    return oauth


def _is_invalid_grant(error):
    error_code = getattr(error, "error", None)
    if error_code is not None:
        return error_code == "invalid_grant"

    # Older Spotipy releases did not always expose the OAuth error code as a
    # structured field. Keep the compatibility fallback intentionally narrow.
    return "invalid_grant" in str(error).lower()


def _remove_cached_token(cache_handler):
    try:
        os.remove(cache_handler.cache_path)
    except FileNotFoundError:
        pass


def get_config():
    config = ConfigParser()
    config.read(f"{dirs.user_config_dir}.cfg")
    if "spotpris2" not in config:
        config["spotpris2"] = {}
    section = config["spotpris2"]
    if section.get("client_id") is None or section.get("client_secret") is None:
        print("To use this software you need to provide your own spotify developer credentials. Go to "
              "https://developer.spotify.com/dashboard/applications, create a new client id and add "
              f"{redirect_uri} to the redirect URIs.")
        section["client_id"] = input("Enter client id: ")
        section["client_secret"] = input("Enter client secret: ")
        with open(f"{dirs.user_config_dir}.cfg", 'w+') as f:
            config.write(f)
    return config["spotpris2"]


if __name__ == '__main__':
    main()
