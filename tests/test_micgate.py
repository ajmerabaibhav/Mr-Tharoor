"""Does the gate actually flip when another app takes the mic?

A gate that never returns True is worse than no gate -- it silently records
nothing forever. So this test opens the mic from a SEPARATE process (our own
PID is excluded by design) and checks the gate notices, then lets go and
checks it clears.

Run: python3 tests/test_micgate.py
Needs microphone permission for your terminal. macOS will ask once.
"""

import os
import signal
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


HELPER_SIGNATURE = "import sounddevice as sd, time"


def _is_our_helper(pid: int) -> bool:
    """Did this test file start that process?

    The check is the command line, not the fact that it holds the microphone.
    Holding the microphone is what Zoom does during a meeting.
    """
    try:
        command = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return False
    return HELPER_SIGNATURE in command


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

    # A previous run's helper process may still be releasing the device, and
    # CoreAudio reports the release a moment after the process exits. Give it
    # a beat before deciding the machine is busy, or this test fails at random
    # when run back to back -- and a flaky test is worse than no test, because
    # it teaches you to ignore a red result.
    # Clear only the helpers THIS test file spawns. An earlier version killed
    # anything holding the microphone, which would have terminated a Zoom call
    # or the user's own listener daemon. A test may never SIGTERM a process it
    # did not create.
    for stray in micgate.mic_users():
        if _is_our_helper(stray.pid):
            try:
                os.kill(stray.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
    wait_for(lambda: not micgate.mic_users(), timeout=3.0)
    already = micgate.mic_users()
    if already:
        # Not a failure: a dictation app or Siri may legitimately hold the
        # mic while the tests run. Skip the idle assertion rather than
        # demanding a pristine machine.
        print(f"idle       -> skipped, mic held by {[str(u) for u in already]}")
    else:
        assert not micgate.is_mic_in_use()
        print("idle       -> False  ok")

    holder = subprocess.Popen([sys.executable, "-c", HOLD_MIC])
    try:  # noqa: PLR1702
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
        # Kill it, do not merely wait for it. An assertion failure above used
        # to leave this process orphaned and still holding the microphone,
        # which then failed the NEXT run, and the one after that. One flaky
        # test became a permanently broken suite. PortAudio can also hang on
        # stream close when the device is contended, so waiting is not enough.
        holder.terminate()
        try:
            holder.wait(timeout=5)
        except subprocess.TimeoutExpired:
            holder.kill()
            holder.wait(timeout=5)

    if not already:
        assert wait_for(lambda: not micgate.is_mic_in_use()), (
            "gate stayed open after the other process released the mic"
        )
        print("released   -> False  ok")
    test_bluetooth_fallback()
    print("\nPASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
