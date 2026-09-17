"""Is another app using the microphone right now?

This is the battery gate. Holding a capture stream open all day costs real
power; asking CoreAudio a question costs microseconds. So the listener sleeps
until this module says a call is actually happening.

Primary path (macOS 14.2+): walk the audio process-object list and check
kAudioProcessPropertyIsRunningInput on each, skipping our own PID. That tells
us exactly which apps hold the mic, so our own capture stream never counts as
a reason to keep capturing.

Fallback (older macOS): kAudioDevicePropertyDeviceIsRunningSomewhere on the
default input device. Cheaper but blunt -- it cannot tell our stream from
anyone else's, so the caller has to stop us before trusting it.

Bluetooth: widely reported to be invisible to CoreAudio. MEASURED FALSE on
macOS 26.6 with AirPods Pro -- input activity is reported normally, so the
primary path above works on Bluetooth here. The inferred fallback below is
kept as insurance for hardware that genuinely does not report (older macOS,
some HFP headsets), and only ever runs when the primary check sees nothing
AND the current device is Bluetooth. Re-measure before relying on it.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import struct
from dataclasses import dataclass

_path = ctypes.util.find_library("CoreAudio")
if _path is None:  # pragma: no cover - macOS always has this
    raise ImportError("CoreAudio not found; mr-roy is macOS only")
_ca = ctypes.CDLL(_path)


def _fourcc(code: str) -> int:
    """CoreAudio selectors are four-char codes packed into a UInt32."""
    return struct.unpack(">I", code.encode("ascii"))[0]


kAudioObjectSystemObject = 1
kAudioObjectPropertyScopeGlobal = _fourcc("glob")
kAudioObjectPropertyElementMain = 0

kAudioHardwarePropertyProcessObjectList = _fourcc("prs#")
kAudioHardwarePropertyDefaultInputDevice = _fourcc("dIn ")
kAudioProcessPropertyPID = _fourcc("ppid")
kAudioProcessPropertyBundleID = _fourcc("pbid")
kAudioProcessPropertyIsRunningInput = _fourcc("piri")
kAudioProcessPropertyIsRunningOutput = _fourcc("piro")
kAudioDevicePropertyDeviceIsRunningSomewhere = _fourcc("gone")
kAudioDevicePropertyTransportType = _fourcc("tran")
kAudioDeviceTransportTypeBluetooth = _fourcc("blue")
kAudioDeviceTransportTypeBluetoothLE = _fourcc("blea")

# Apps whose audio output means a conversation, not entertainment. Used only
# on the Bluetooth path, where the microphone itself is invisible to us.
CALL_APPS = frozenset(
    {
        "us.zoom.xos",
        "com.microsoft.teams",
        "com.microsoft.teams2",
        "com.microsoft.SkypeForBusiness",
        "com.tinyspeck.slackmacgap",
        "com.apple.FaceTime",
        "com.apple.iChat",
        "net.whatsapp.WhatsApp",
        "com.hnc.Discord",
        "com.google.meet",
        "com.readdle.spark",
        "com.loom.desktop",
        "com.cisco.webexmeetingsapp",
        "com.google.Chrome",
        "com.apple.Safari",
        "com.microsoft.edgemac",
        "com.brave.Browser",
        "company.thebrowser.Browser",
    }
)


class _Address(ctypes.Structure):
    _fields_ = [
        ("mSelector", ctypes.c_uint32),
        ("mScope", ctypes.c_uint32),
        ("mElement", ctypes.c_uint32),
    ]


def _addr(selector: int) -> _Address:
    return _Address(selector, kAudioObjectPropertyScopeGlobal, kAudioObjectPropertyElementMain)


def _data_size(obj: int, selector: int) -> int:
    size = ctypes.c_uint32(0)
    err = _ca.AudioObjectGetPropertyDataSize(
        ctypes.c_uint32(obj), ctypes.byref(_addr(selector)), 0, None, ctypes.byref(size)
    )
    if err != 0:
        raise OSError(err, f"AudioObjectGetPropertyDataSize failed for {selector:#x}")
    return size.value


def _get(obj: int, selector: int, ctype):
    """Read one fixed-size property value."""
    value = ctype()
    size = ctypes.c_uint32(ctypes.sizeof(ctype))
    err = _ca.AudioObjectGetPropertyData(
        ctypes.c_uint32(obj),
        ctypes.byref(_addr(selector)),
        0,
        None,
        ctypes.byref(size),
        ctypes.byref(value),
    )
    if err != 0:
        raise OSError(err, f"AudioObjectGetPropertyData failed for {selector:#x}")
    return value.value


def _get_array(obj: int, selector: int) -> list[int]:
    """Read a variable-length array of AudioObjectIDs."""
    size = _data_size(obj, selector)
    count = size // ctypes.sizeof(ctypes.c_uint32)
    if count == 0:
        return []
    buf = (ctypes.c_uint32 * count)()
    io_size = ctypes.c_uint32(size)
    err = _ca.AudioObjectGetPropertyData(
        ctypes.c_uint32(obj),
        ctypes.byref(_addr(selector)),
        0,
        None,
        ctypes.byref(io_size),
        ctypes.byref(buf),
    )
    if err != 0:
        raise OSError(err, f"AudioObjectGetPropertyData failed for {selector:#x}")
    return list(buf)[: io_size.value // ctypes.sizeof(ctypes.c_uint32)]


_cf_path = ctypes.util.find_library("CoreFoundation")
_cf = ctypes.CDLL(_cf_path) if _cf_path else None


def _get_cfstring(obj: int, selector: int) -> str | None:
    """Read a CFStringRef property and convert it to a Python str."""
    cf = _cf
    if cf is None:  # pragma: no cover
        return None
    ref = ctypes.c_void_p()
    size = ctypes.c_uint32(ctypes.sizeof(ctypes.c_void_p))
    err = _ca.AudioObjectGetPropertyData(
        ctypes.c_uint32(obj),
        ctypes.byref(_addr(selector)),
        0,
        None,
        ctypes.byref(size),
        ctypes.byref(ref),
    )
    if err != 0 or not ref:
        return None
    try:
        cf.CFStringGetCStringPtr.restype = ctypes.c_char_p
        ptr = cf.CFStringGetCStringPtr(ref, 0x08000100)  # kCFStringEncodingUTF8
        if ptr:
            return ptr.decode("utf-8")
        buf = ctypes.create_string_buffer(512)
        if not cf.CFStringGetCString(ref, buf, 512, 0x08000100):
            return None  # leaked a CFString here before the try/finally
        return buf.value.decode("utf-8")
    finally:
        # The gate polls every few seconds for the life of the machine, so a
        # handle leaked on the failure path leaks forever.
        cf.CFRelease(ref)


@dataclass(frozen=True)
class MicUser:
    """One process currently holding the microphone."""

    pid: int
    bundle_id: str | None

    def __str__(self) -> str:
        return f"{self.bundle_id or 'unknown'} (pid {self.pid})"


def _process_api_available() -> bool:
    try:
        _data_size(kAudioObjectSystemObject, kAudioHardwarePropertyProcessObjectList)
        return True
    except OSError:
        return False


def mic_users(exclude_self: bool = True) -> list[MicUser]:
    """Every process currently running audio input, newest API only.

    Returns an empty list on macOS older than 14.2 -- callers should check
    `has_process_api` before treating that as "nobody is on a call".
    """
    if not _process_api_available():
        return []
    me = os.getpid()
    users: list[MicUser] = []
    for obj in _get_array(kAudioObjectSystemObject, kAudioHardwarePropertyProcessObjectList):
        try:
            if not _get(obj, kAudioProcessPropertyIsRunningInput, ctypes.c_uint32):
                continue
            pid = _get(obj, kAudioProcessPropertyPID, ctypes.c_int32)
        except OSError:
            continue  # process vanished between the list read and the query
        if exclude_self and pid == me:
            continue
        users.append(MicUser(pid=pid, bundle_id=_get_cfstring(obj, kAudioProcessPropertyBundleID)))
    return users


def _device_running_somewhere() -> bool:
    """Fallback for macOS < 14.2. Cannot exclude our own stream."""
    device = _get(
        kAudioObjectSystemObject, kAudioHardwarePropertyDefaultInputDevice, ctypes.c_uint32
    )
    if device == 0:
        return False
    return bool(_get(device, kAudioDevicePropertyDeviceIsRunningSomewhere, ctypes.c_uint32))


def input_is_bluetooth() -> bool:
    """Is the current microphone one CoreAudio cannot see the state of?"""
    try:
        device = _get(
            kAudioObjectSystemObject, kAudioHardwarePropertyDefaultInputDevice, ctypes.c_uint32
        )
        if device == 0:
            return False
        transport = _get(device, kAudioDevicePropertyTransportType, ctypes.c_uint32)
    except OSError:
        return False
    return transport in (kAudioDeviceTransportTypeBluetooth, kAudioDeviceTransportTypeBluetoothLE)


def audio_output_apps(exclude_self: bool = True) -> list[MicUser]:
    """Processes currently PLAYING audio. Bluetooth reports this even though
    it refuses to report input, which is what makes the fallback possible."""
    if not _process_api_available():
        return []
    me = os.getpid()
    out: list[MicUser] = []
    for obj in _get_array(kAudioObjectSystemObject, kAudioHardwarePropertyProcessObjectList):
        try:
            if not _get(obj, kAudioProcessPropertyIsRunningOutput, ctypes.c_uint32):
                continue
            pid = _get(obj, kAudioProcessPropertyPID, ctypes.c_int32)
        except OSError:
            continue
        if exclude_self and pid == me:
            continue
        out.append(MicUser(pid=pid, bundle_id=_get_cfstring(obj, kAudioProcessPropertyBundleID)))
    return out


def _bluetooth_call_likely() -> list[MicUser]:
    """Insurance, not the main path. Unverified on real hardware.

    If a Bluetooth mic ever does hide its input state, a call is still
    two-way: the other person's voice is being played to you, and output IS
    reported. So infer a call from "a conversation app is making sound".

    Weaker signal -- a browser playing a video looks like a browser on a call
    -- so a caller must confirm with voice activity before keeping any audio.
    A false positive costs battery, never bad data, because a segment with
    none of your speech in it is discarded downstream.
    """
    if not input_is_bluetooth():
        return []
    return [app for app in audio_output_apps() if app.bundle_id in CALL_APPS]


has_process_api = _process_api_available()


def is_mic_in_use() -> bool:
    """True when a conversation is happening that is worth recording."""
    if not has_process_api:
        return _device_running_somewhere()
    return bool(mic_users()) or bool(_bluetooth_call_likely())


def why_open() -> tuple[bool, str, list[MicUser]]:
    """The gate's reasoning, for logs and for `roy gate`."""
    if not has_process_api:
        running = _device_running_somewhere()
        return running, "device-running fallback (cannot exclude our own stream)", []
    direct = mic_users()
    if direct:
        return True, "another app holds the microphone", direct
    inferred = _bluetooth_call_likely()
    if inferred:
        return True, "bluetooth mic is invisible; a call app is playing audio", inferred
    return False, "no conversation detected", []


def gate_health() -> dict[str, object]:
    """What this machine can and cannot detect. Surfaced in the daily report."""
    return {
        "process_api": has_process_api,
        "method": "process-object list" if has_process_api else "device-running fallback",
        "input_is_bluetooth": input_is_bluetooth(),
        "bluetooth_input_visible": bool(mic_users()) or not input_is_bluetooth(),
        "bluetooth_fallback": "call-app audio output (insurance, unverified)",
        "note": (
            "Measured on macOS 26.6 + AirPods Pro: Bluetooth input IS reported, "
            "so the primary path works. The inferred fallback stays for hardware "
            "that does not report, and only runs when the primary sees nothing."
        ),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(gate_health(), indent=2))
    users = mic_users()
    print(f"\nmic in use: {is_mic_in_use()}")
    for u in users:
        print(f"  {u}")
