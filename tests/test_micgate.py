"""Does the gate actually flip when another app takes the mic?

A gate that never returns True is worse than no gate -- it silently records
nothing forever. So this test opens the mic from a SEPARATE process (our own
PID is excluded by design) and checks the gate notices, then lets go and
checks it clears.

Run: python3 tests/test_micgate.py
Needs microphone permission for your terminal. macOS will ask once.
"""

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mr_roy import micgate

HOLD_MIC = """
import sounddevice as sd, time
with sd.InputStream(samplerate=16000, channels=1):
    time.sleep(6)
"""


def wait_for(predicate, timeout=8.0, interval=0.25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_bluetooth_fallback():
    """AirPods report no input state at all. Without this path the gate stays
    shut through every call, records nothing, and says nothing is wrong --
    which is exactly what it did before this test existed."""
    assert isinstance(micgate.input_is_bluetooth(), bool)

    real_output = micgate.audio_output_apps
    real_bt = micgate.input_is_bluetooth
    try:
        # A conversation app making sound on a Bluetooth mic means a call.
        micgate.input_is_bluetooth = lambda: True
        micgate.audio_output_apps = lambda exclude_self=True: [
            micgate.MicUser(pid=999, bundle_id="us.zoom.xos")
        ]
        assert micgate.is_mic_in_use(), "bluetooth call not detected"
        open_, why, who = micgate.why_open()
        assert open_ and "bluetooth" in why and who[0].pid == 999

        # Music is not a conversation.
        micgate.audio_output_apps = lambda exclude_self=True: [
            micgate.MicUser(pid=998, bundle_id="com.spotify.client")
        ]
        assert not micgate.is_mic_in_use(), "spotify must not open the gate"

        # On a visible mic the fallback must not fire at all.
        micgate.input_is_bluetooth = lambda: False
        micgate.audio_output_apps = lambda exclude_self=True: [
            micgate.MicUser(pid=997, bundle_id="us.zoom.xos")
        ]
        assert not micgate.is_mic_in_use(), "fallback fired on a visible mic"
    finally:
        micgate.audio_output_apps = real_output
        micgate.input_is_bluetooth = real_bt
    print("bluetooth fallback          ok")


def main() -> int:
    assert micgate.has_process_api, (
        "process-object API unavailable; this Mac falls back to the blunt "
        "device-running check and cannot exclude our own stream"
    )

    assert not micgate.is_mic_in_use(), (
        f"expected an idle mic before the test, but found: "
        f"{[str(u) for u in micgate.mic_users()]}"
    )
    print("idle       -> False  ok")

    holder = subprocess.Popen([sys.executable, "-c", HOLD_MIC])
    try:
        assert wait_for(micgate.is_mic_in_use), (
            "gate never opened while another process held the mic. If macOS "
            "showed a permission prompt, grant it and re-run."
        )
        users = micgate.mic_users()
        assert any(u.pid == holder.pid for u in users), (
            f"gate opened but did not name the holder (pid {holder.pid}); saw {users}"
        )
        print(f"other app  -> True   ok  ({users[0]})")

        # Our own stream must never be a reason to keep capturing.
        assert not any(u.pid == __import__("os").getpid() for u in micgate.mic_users())
        print("self       -> excluded ok")
    finally:
        holder.wait(timeout=12)

    assert wait_for(lambda: not micgate.is_mic_in_use()), (
        "gate stayed open after the other process released the mic"
    )
    print("released   -> False  ok")
    test_bluetooth_fallback()
    print("\nPASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
