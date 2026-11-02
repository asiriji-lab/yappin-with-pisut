"""The iDotMatrix pixel display over Bluetooth LE, driven from its own thread.

Bleak (WinRT) gets a thread and asyncio loop of its own that never touches COM, because the
Windows voice (SAPI) sets up COM in the speaker thread. One connection is kept for the whole
session; the library reconnects by itself when a command finds it dropped.

What the display does (found by testing on IDM-E9D930):
  - still image: DIY mode on (setMode 1), then a PNG; shows in ~0.05 s
  - looping animation: DIY mode OFF (setMode 0), then a GIF; ~0.6 s to start. With DIY mode
    still on, the GIF plays once and freezes. Sending PNG frames one by one doesn't animate.
"""
import asyncio
import logging
import os
import tempfile
import threading

from idotmatrix import ConnectionManager, Gif, Image

from face import save_idle, save_talking

log = logging.getLogger("display")


class Display:
    def __init__(self, address=None):
        self.address = address
        self.ok = False
        self._talking = None
        folder = tempfile.mkdtemp(prefix="athena-face-")
        self._idle = os.path.join(folder, "idle.png")
        self._talk = os.path.join(folder, "talk.gif")
        save_idle(self._idle)
        save_talking(self._talk)
        self._loop = asyncio.new_event_loop()
        self._lock = None
        threading.Thread(target=self._loop.run_forever, daemon=True, name="ble").start()

    def _run(self, coro, wait=False, timeout=30):
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout) if wait else fut

    def connect(self):
        """Find and connect to the display; False if it isn't around (the app runs without it)."""
        try:
            self.ok = self._run(self._connect(), wait=True)
        except Exception as e:
            log.warning("display: %s", e)
            self.ok = False
        return self.ok

    async def _connect(self):
        self._lock = asyncio.Lock()
        conn = ConnectionManager()
        if self.address:
            await conn.connectByAddress(self.address)
        else:
            await conn.connectBySearch()
        if not (conn.client and conn.client.is_connected):
            return False
        self.address = conn.address
        await self._show(False)
        return True

    def talking(self, on: bool):
        """Mouth moving (True) or closed (False). Returns at once; repeats are ignored."""
        if not self.ok or on == self._talking:
            return
        self._talking = on
        self._run(self._show(on))

    async def _show(self, on):
        async with self._lock:
            for attempt in range(2):
                if on:
                    done = await Image().setMode(0) and await Gif().uploadUnprocessed(self._talk)
                else:
                    done = await Image().setMode(1) and await Image().uploadUnprocessed(self._idle)
                if done:
                    return
                log.warning("display didn't take the %s face, retrying", "talking" if on else "idle")
                await asyncio.sleep(0.5)

    def close(self):
        if self.ok:
            try:
                self._run(self._show(False), wait=True, timeout=10)
                self._run(ConnectionManager().disconnect(), wait=True, timeout=10)
            except Exception:
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)
