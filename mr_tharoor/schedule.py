"""Run every day without being asked, including when the laptop was shut.

The question this answers: if the Mac is closed at 23:30, what happens?

launchd, not cron. cron silently skips anything scheduled while the machine
was asleep or off, which would mean a closed laptop quietly costs you a day.
launchd with StartCalendarInterval keeps the missed event and fires it at the
next opportunity, so the job runs when you next open the lid. Nothing is lost
and nothing needs a daemon sitting awake.

Three agents, deliberately separate so one failing never takes the others out:

    com.tharoor.listen    at login, stays resident, reads the text box you
                        are typing in. Restarted if it dies, throttled so a
                        crash loop cannot spin the CPU.
    com.tharoor.nightly   23:30 and every 15 minutes while awake, catches up
                        retained days. Does not request a wake lock.
    com.tharoor.morning   08:30, opens the report.

Every agent runs as you, in your login session. Nothing installs to /Library,
nothing needs sudo, nothing runs as root. Removing it is `tharoor uninstall`, and
what that removes is three files in ~/Library/LaunchAgents.
"""

from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from . import config

AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
LOG_DIR = config.ROOT / "logs"

JOBS = {
    "com.tharoor.listen": {
        "args": ["listen"],
        "resident": True,  # starts at login and stays up
        "battery_safe": True,
        "what": "reads your typing, all day",
    },
    "com.tharoor.nightly": {
        "args": ["analyse-pending", "--force"],
        "hour": 23,
        "minute": 30,
        "retry": True,
        "battery_safe": True,  # no wake assertion; catches up while the Mac is awake
        "what": "check the day's grammar",
    },
    "com.tharoor.morning": {
        "args": ["morning", "--automatic"],
        "hour": 8,
        "minute": 30,
        "battery_safe": True,  # cheap: opens a file and posts a notification
        "retry": True,
        "what": "open the lesson",
    },
}


def _tharoor() -> list[str]:
    """The installed command, resolved now rather than guessed at run time."""
    found = shutil.which("tharoor")
    if found:
        return [found]
    return [sys.executable, "-m", "mr_tharoor.cli"]


APP = config.ROOT / "Mr Tharoor.app"
APP_INFO = {
    "CFBundleName": "Mr Tharoor", "CFBundleDisplayName": "Mr Tharoor",
    "CFBundleIdentifier": "com.tharoor.app", "CFBundleExecutable": "MrTharoor",
    "CFBundlePackageType": "APPL", "CFBundleVersion": "1", "LSUIElement": True,
    "CFBundleIconFile": "AppIcon",
}


def _icon_png() -> bytes:
    """The welcome portrait (welcome.ART) on a cream square, 1024 px, as PNG.
    Stdlib only: nearest-neighbour blocks need no imaging library."""
    import struct
    import zlib

    from .welcome import ART, PALETTE

    size, scale = 1024, 32
    background = (240, 233, 220)
    left, top = (size - len(ART[0]) * scale) // 2, size - len(ART) * scale  # shoulders on the edge
    rows = []
    for y in range(size):
        art = ART[(y - top) // scale] if y >= top else ""
        row = bytearray(b"\0")
        for x in range(size):
            cell = art[(x - left) // scale] if art and 0 <= x - left < len(art) * scale else "."
            row += bytes(PALETTE.get(cell, background))
        rows.append(bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def launcher() -> str | None:
    """Build Mr Tharoor.app once; the listener runs inside it so macOS names
    the Accessibility grant "Mr Tharoor", not "python3.12" (native/launcher.c).

    Built only when missing or its source, icon or Info.plist changed: a
    rebuilt app is a new identity to macOS, and the grant must be given again. None when
    there is no compiler (no Xcode command line tools); the listener then runs
    as plain Python, which works the same under its old name.
    """
    import hashlib

    source = Path(__file__).with_name("native") / "launcher.c"
    binary = APP / "Contents" / "MacOS" / "MrTharoor"
    stamp = APP / "Contents" / "Resources" / "source.sha256"
    icon = _icon_png()
    digest = hashlib.sha256(source.read_bytes() + icon + plistlib.dumps(APP_INFO)).hexdigest()
    if binary.exists() and stamp.exists() and stamp.read_text() == digest:
        return str(binary)
    binary.parent.mkdir(parents=True, exist_ok=True)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    (APP / "Contents" / "Info.plist").write_bytes(plistlib.dumps(APP_INFO))
    try:
        built = subprocess.run(["clang", "-O2", "-o", str(binary), str(source)],
                               capture_output=True, timeout=120).returncode == 0
        iconset = stamp.with_name("AppIcon.iconset")  # iconutil: sips failed writing its temp file
        iconset.mkdir(exist_ok=True)
        (iconset / "icon_512x512@2x.png").write_bytes(icon)
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(stamp.with_name("AppIcon.icns"))],
                       capture_output=True, timeout=60)
        shutil.rmtree(iconset)
        stamp.write_text(digest)  # before signing: a file added after breaks the seal
        signed = built and subprocess.run(["codesign", "--force", "-s", "-", "-i", APP_INFO["CFBundleIdentifier"],
                                           str(APP)], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        signed = False
    if not signed:
        shutil.rmtree(APP, ignore_errors=True)
        return None
    return str(binary)


def plist_for(label: str, job: dict) -> dict:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    command = _tharoor() + list(job["args"])
    if job.get("resident"):
        app = launcher()
        command = ([app] if app else []) + command
    schedule: dict = {}
    if job.get("resident"):
        # KeepAlive: True, not {"SuccessfulExit": False}.
        #
        # The listener handles SIGTERM gracefully and exits 0, which is
        # correct behaviour. But under SuccessfulExit:False launchd reads a
        # clean exit as "it meant to stop" and never restarts it. Anything
        # that signals the process -- a test, a reinstall, Activity Monitor,
        # a logout -- left it permanently dead and silent. Observed: it
        # captured four real chunks, was signalled, exited 0, and stayed down.
        #
        # True means always bring it back. Stopping it deliberately is
        # `tharoor install --remove`, which unloads the job so there is nothing
        # left to restart. ThrottleInterval keeps a crash loop from spinning
        # the CPU.
        schedule["RunAtLoad"] = True
        schedule["KeepAlive"] = True
        schedule["ThrottleInterval"] = 30
    else:
        # A missed calendar event is not dropped: launchd runs it at the next
        # wake. That is the whole reason this is not cron.
        schedule["RunAtLoad"] = bool(job.get("retry"))
        if job.get("retry"):
            schedule["StartInterval"] = 900
        schedule["StartCalendarInterval"] = {
            "Hour": job["hour"],
            "Minute": job["minute"],
        }
    return {
        "Label": label,
        "ProgramArguments": command,
        **schedule,
        "StandardOutPath": str(LOG_DIR / f"{label}.log"),
        "StandardErrorPath": str(LOG_DIR / f"{label}.err"),
        "LowPriorityIO": True,
        "Nice": 5,  # never compete with whatever you are actually doing
        "ProcessType": "Background",
        "EnvironmentVariables": {"MR_THAROOR_HOME": str(config.ROOT), "PYTHONUNBUFFERED": "1"},
    }


@contextmanager
def job_lock(name: str):
    """Manual and scheduled jobs must not overwrite each other's day or queue."""
    import fcntl

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with (config.DATA_DIR / f".{name}.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class InstallationError(RuntimeError):
    """The plist exists, but launchd did not confirm the job was installed."""


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _launchctl(*args: str):
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=15)


def service_state(label: str) -> dict:
    """Inspect the actual login service, not this shell's bootstrap namespace."""
    result = _launchctl("print", f"{_domain()}/{label}")
    if result.returncode:
        return {"loaded": False, "detail": result.stderr.strip() or "not loaded"}
    state = {"loaded": True}
    for field in ("state", "pid", "runs", "last exit code"):
        found = re.search(rf"^\s*{re.escape(field)} = (.+)$", result.stdout, re.M)
        if found:
            state[field] = found[1].strip()
    return state


def install(dry_run: bool = False) -> list[str]:
    """Write and load the agents. Idempotent: re-running just refreshes them."""
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    failures = []
    if not dry_run:
        result = _launchctl("print", _domain())
        if result.returncode:
            raise InstallationError("Cannot access the macOS login session. Run `tharoor install` "
                                    "from Terminal while logged in to the desktop.")
    for label, job in JOBS.items():
        path = AGENTS_DIR / f"{label}.plist"
        data = plist_for(label, job)
        if dry_run:
            written.append(f"would write {path}")
            continue
        path.write_bytes(plistlib.dumps(data))
        target = f"{_domain()}/{label}"
        # Legacy `load` can exit successfully without installing a service in
        # the desktop session. Bootstrap explicitly and verify the target.
        if service_state(label)["loaded"]:
            result = _launchctl("bootout", target)
            if result.returncode:
                failures.append(f"{label}: could not stop the old service: {result.stderr.strip()}")
                continue
        enabled = _launchctl("enable", target)
        for _ in range(10):
            # Right after a bootout launchd can still be tearing the old
            # one down and answers "5: Input/output error" (10 Oct, setup).
            result = _launchctl("bootstrap", _domain(), str(path))
            if result.returncode == 0:
                break
            time.sleep(0.5)
        verified = service_state(label)
        if enabled.returncode or result.returncode or not verified["loaded"]:
            failures.append(f"{label}: installation failed: "
                            f"{result.stderr.strip() or enabled.stderr.strip() or verified.get('detail')}")
            continue
        when = "at login" if job.get("resident") else f"{job['hour']:02d}:{job['minute']:02d}"
        written.append(f"{job['what']:<28} {when}")
    if failures:
        raise InstallationError("\n".join(written + failures))
    return written


def uninstall() -> list[str]:
    removed = []
    for label in JOBS:
        path = AGENTS_DIR / f"{label}.plist"
        if path.exists():
            if service_state(label)["loaded"]:
                result = _launchctl("bootout", f"{_domain()}/{label}")
                if result.returncode:
                    raise InstallationError(f"Could not unload {label}: {result.stderr.strip()}")
            path.unlink()
            removed.append(label)
    return removed


def status() -> list[str]:
    out = []
    for label, job in JOBS.items():
        path = AGENTS_DIR / f"{label}.plist"
        installed = "installed" if path.exists() else "not installed"
        state = service_state(label)
        running = "NOT LOADED" if not state["loaded"] else f"loaded, {state.get('state', 'waiting')}"
        if state.get("pid"):
            running += f" (PID {state['pid']})"
        if state.get("last exit code") not in (None, "0", "(never exited)"):
            running += f", last exit {state['last exit code']}"
        when = "at login" if job.get("resident") else f"{job['hour']:02d}:{job['minute']:02d}"
        out.append(f"{label:<20} {when:<9} {installed}, {running}   ({job['what']})")
    return out


def on_battery() -> bool:
    """True when unplugged. The nightly job refuses to run on battery."""
    result = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True)
    return "Battery Power" in result.stdout
