"""V2 Step C5-C6: pause / play / next reach whatever is playing, and are checked.

A fake MPRIS player (like Chrome playing YouTube or Spotify web) runs on a
private D-Bus session; Ultron's real gdbus code controls it.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

from backend.app.tools import media_control

FAKE_PLAYER = r'''
import asyncio, sys
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, method, dbus_property, PropertyAccess
from dbus_next import Variant

SONGS = ["Believer", "Thunder", "Demons"]

class Root(ServiceInterface):
    def __init__(self):
        super().__init__("org.mpris.MediaPlayer2")
    @dbus_property(access=PropertyAccess.READ)
    def Identity(self) -> "s":
        return "Fake"

class Player(ServiceInterface):
    def __init__(self, status):
        super().__init__("org.mpris.MediaPlayer2.Player")
        self.status, self.i, self.vol = status, 0, 1.0
    @method()
    def Pause(self): self.status = "Paused"
    @method()
    def Play(self): self.status = "Playing"
    @method()
    def PlayPause(self): self.status = "Paused" if self.status == "Playing" else "Playing"
    @method()
    def Stop(self): self.status = "Stopped"
    @method()
    def Next(self): self.i = (self.i + 1) % len(SONGS)
    @method()
    def Previous(self): self.i = (self.i - 1) % len(SONGS)
    @dbus_property(access=PropertyAccess.READ)
    def PlaybackStatus(self) -> "s":
        return self.status
    @dbus_property(access=PropertyAccess.READ)
    def Metadata(self) -> "a{sv}":
        return {"xesam:title": Variant("s", SONGS[self.i]), "xesam:artist": Variant("as", ["Imagine Dragons"]),
                "xesam:url": Variant("s", sys.argv[3])}
    @dbus_property()
    def Volume(self) -> "d":
        return self.vol
    @Volume.setter
    def Volume(self, value: "d"):
        self.vol = value

async def main():
    bus = await MessageBus().connect()
    bus.export("/org/mpris/MediaPlayer2", Root())
    bus.export("/org/mpris/MediaPlayer2", Player(sys.argv[2]))
    await bus.request_name("org.mpris.MediaPlayer2." + sys.argv[1])
    print("ready", flush=True)
    await asyncio.Event().wait()

asyncio.run(main())
'''


def _have_dbus() -> bool:
    import importlib.util

    if importlib.util.find_spec("dbus_next") is None:
        return False
    return os.name != "nt" and bool(shutil.which("dbus-daemon") and shutil.which("gdbus"))


@unittest.skipUnless(_have_dbus(), "needs dbus-daemon, gdbus and dbus-next (Linux)")
class TestRealMprisPlayer(unittest.TestCase):
    def setUp(self):
        self.bus = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"],
                                    stdout=subprocess.PIPE, text=True)
        self.addCleanup(self.bus.kill)
        address = self.bus.stdout.readline().strip()
        env = patch.dict(os.environ, {"DBUS_SESSION_BUS_ADDRESS": address})
        env.start()
        self.addCleanup(env.stop)

    def player(self, name, status, url=""):
        proc = subprocess.Popen([sys.executable, "-c", FAKE_PLAYER, name, status, url],
                                stdout=subprocess.PIPE, text=True, env=dict(os.environ))
        self.addCleanup(proc.kill)
        self.assertEqual(proc.stdout.readline().strip(), "ready")
        return proc

    def test_nothing_playing_is_said_plainly(self):
        result = media_control.control("pause")
        self.assertFalse(result["success"])
        self.assertIn("Nothing is playing", result["error"])

    def test_pause_youtube_in_chrome_then_play(self):
        self.player("chromium.instance123", "Playing", "https://www.youtube.com/watch?v=x")
        paused = media_control.control("pause")
        self.assertTrue(paused["success"], paused)
        self.assertEqual(paused["data"]["status"], "Paused")
        self.assertEqual(paused["data"]["player"], "YouTube in Chrome")
        again = media_control.control("pause")
        self.assertTrue(again["data"]["already"], "pause twice never toggles it back on")
        played = media_control.control("play")
        self.assertEqual(played["data"]["status"], "Playing")

    def test_next_is_checked_by_title(self):
        self.player("spotify", "Playing")
        result = media_control.control("next")
        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"]["title"], "Thunder")
        self.assertTrue(result["data"]["confirmed"])

    def test_spotify_hint_picks_spotify_web_over_other_players(self):
        self.player("vlc", "Playing")
        self.player("chromium.instance9", "Playing", "https://open.spotify.com/track/1")
        result = media_control.control("pause", "spotify")
        self.assertEqual(result["data"]["player"], "Spotify in Chrome")
        self.assertEqual(media_control.now_playing("vlc")["data"]["status"], "Playing")

    def test_spotify_tools_use_it(self):
        from backend.app.tools.spotify_tools import SpotifyCurrentTrackTool, SpotifyPauseTool
        self.player("spotify", "Playing")
        result = asyncio.run(SpotifyPauseTool().execute())
        self.assertTrue(result["success"], result)
        track = asyncio.run(SpotifyCurrentTrackTool().execute())
        self.assertEqual(track["data"]["current_track"], "Believer - Imagine Dragons")

    def test_pause_music_tool_reaches_browser_when_ultron_plays_nothing(self):
        from backend.app.tools.music_tools import PauseMusicTool
        self.player("firefox.instance_1_2", "Playing", "https://www.youtube.com/watch?v=y")
        result = asyncio.run(PauseMusicTool().execute())
        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"]["player"], "YouTube in Firefox")

    def test_volume(self):
        self.player("spotify", "Playing")
        self.assertEqual(media_control.set_player_volume(40, "spotify")["data"]["level"], 40)


class TestPlainRules(unittest.TestCase):
    def test_pick_prefers_named_then_playing(self):
        found = [{"bus": "a", "label": "VLC", "status": "Paused"},
                 {"bus": "b", "label": "Chrome", "status": "Playing"}]
        self.assertEqual(media_control.pick(found, "pause")["bus"], "b")
        self.assertEqual(media_control.pick(found, "play")["bus"], "a")
        self.assertEqual(media_control.pick(found, "pause", "vlc")["bus"], "a")

    def test_unknown_action(self):
        self.assertFalse(media_control.control("explode")["success"])

    def test_windows_sends_key_and_says_it_cannot_check(self):
        with patch.object(media_control, "IS_WINDOWS", True), \
                patch.object(media_control, "_windows_key", return_value=media_control._ok(confirmed=False)) as key:
            self.assertFalse(media_control.control("pause")["data"]["confirmed"])
        key.assert_called_once_with("pause")


if __name__ == "__main__":
    unittest.main()
