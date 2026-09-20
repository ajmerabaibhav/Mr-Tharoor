"""Run every day without being asked, including when the laptop was shut.

The question this answers: if the Mac is closed at 23:30, what happens?

launchd, not cron. cron silently skips anything scheduled while the machine
was asleep or off, which would mean a closed laptop quietly costs you a day.
launchd with StartCalendarInterval keeps the missed event and fires it at the
next opportunity, so the job runs when you next open the lid. Nothing is lost
and nothing needs a daemon sitting awake.

Three agents, deliberately separate so one failing never takes the others out:

    com.tharoor.listen    at login, stays resident, sleeps until there is
                        something to hear. ~9 seconds of CPU across a 14 hour
                        day. Restarted if it dies, throttled so a crash loop
                        cannot spin the CPU.
    com.tharoor.nightly   23:30, analyses the day. Skips itself on battery, so
                        it never wakes up and drains a laptop in a bag.
    com.tharoor.morning   08:30, opens the report and sends the day's reminders.

Every agent runs as you, in your login session. Nothing installs to /Library,
nothing needs sudo, nothing runs as root. Removing it is `roy uninstall`, and
what that removes is three files in ~/Library/LaunchAgents.
"""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from . import config

AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
LOG_DIR = config.ROOT / "logs"

JOBS = {
    "com.tharoor.listen": {
        "args": ["listen"],
        "resident": True,  # starts at login and stays up
        "battery_safe": True,  # 8.3 seconds of CPU across a whole day
        "what": "listen, context-aware, all day",
    },
    "com.tharoor.nightly": {
        "args": ["analyse-pending", "--force"],
        "hour": 23,
        "minute": 30,
        "retry": True,
        "battery_safe": True,  # no wake assertion; catches up while the Mac is awake
        "what": "analyse the day's speech",
    },
    "com.tharoor.morning": {
        "args": ["morning", "--automatic"],
        "hour": 8,
        "minute": 30,
        "battery_safe": True,  # cheap: opens a file and posts notifications
        "retry": True,
        "what": "open the report, queue the reminders",
    },
}


def _roy() -> list[str]:
    """The installed command, resolved now rather than guessed at run time."""
    found = shutil.which("tharoor")
    if found:
        return [found]
    return [sys.executable, "-m", "mr_tharoor.cli"]


def plist_for(label: str, job: dict) -> dict:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    command = _roy() + list(job["args"])
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
        # `roy install --remove`, which unloads the job so there is nothing
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
        "EnvironmentVariables": {"MR_THAROOR_HOME": str(config.ROOT)},
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


def install(dry_run: bool = False) -> list[str]:
    """Write and load the agents. Idempotent: re-running just refreshes them."""
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for label, job in JOBS.items():
        path = AGENTS_DIR / f"{label}.plist"
        data = plist_for(label, job)
        if dry_run:
            written.append(f"would write {path}")
            continue
        path.write_bytes(plistlib.dumps(data))
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
        result = subprocess.run(["launchctl", "load", str(path)], capture_output=True)
        state = "loaded" if result.returncode == 0 else result.stderr.decode().strip()
        when = "at login" if job.get("resident") else f"{job['hour']:02d}:{job['minute']:02d}"
        written.append(f"{label:<20} {when:<9} {state}")
    return written


def uninstall() -> list[str]:
    removed = []
    for label in JOBS:
        path = AGENTS_DIR / f"{label}.plist"
        if path.exists():
            subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
            path.unlink()
            removed.append(label)
    return removed


def status() -> list[str]:
    out = []
    listing = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
    for label, job in JOBS.items():
        path = AGENTS_DIR / f"{label}.plist"
        installed = "installed" if path.exists() else "not installed"
        running = "loaded" if label in listing else "not loaded"
        when = "at login" if job.get("resident") else f"{job['hour']:02d}:{job['minute']:02d}"
        out.append(f"{label:<20} {when:<9} {installed}, {running}   ({job['what']})")
    return out


def on_battery() -> bool:
    """True when unplugged. The nightly job refuses to run on battery."""
    result = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True)
    return "Battery Power" in result.stdout
