"""Mr Tharoor, your English teacher.

    tharoor setup                     one command: check, ask, schedule
    tharoor listen                    the background job: reads your typing
    tharoor analyse-day               the 23:30 job: check today, build the lesson
    tharoor analyse-pending           catch up days missed while the Mac slept
    tharoor morning                   the 08:30 job: open the lesson
    tharoor install                   run every day by itself (launchd)
    tharoor logs                      what the scheduled jobs did
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config


def cmd_install(args: argparse.Namespace) -> int:
    from . import schedule

    if args.remove:
        removed = schedule.uninstall()
        print("Removed:" if removed else "Nothing was installed.")
        for label in removed:
            print(f"  {label}")
        return 0
    if args.status:
        for line in schedule.status():
            print(f"  {line}")
        return 0
    try:
        for line in schedule.install(dry_run=args.dry_run):
            print(f"  {line}")
    except schedule.InstallationError as exc:
        print(f"  Installation incomplete: {exc}")
        return 1
    print("\n  A missed run is not skipped: launchd fires it when you next open the lid.")
    print("  Remove anytime with `tharoor install --remove`. Nothing needs sudo.")
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    """Everything a fresh clone needs, in the order it needs it.

    Written because the alternative is a README a person follows wrongly.
    Each step says what it is doing, and a failure names the fix rather than
    a traceback.
    """
    import os
    import platform
    import subprocess

    from . import schedule, textboxes, welcome

    colour = welcome._colour()
    bold, dim, green, red, reset = ("\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[0m") if colour \
        else ("",) * 5
    ok, bad = f"{green}●{reset}", f"{red}○{reset}"

    print(f"\n  {bold}Mr Tharoor setup{reset}\n")
    if platform.system() != "Darwin":
        print(f"    {bad} {platform.system()} is not supported. macOS only, for now.\n")
        return 1
    print(f"    {ok} macOS {platform.mac_ver()[0]} on {platform.machine()}")
    try:
        import ApplicationServices  # noqa: F401
        print(f"    {ok} pyobjc-framework-ApplicationServices")
    except ImportError:
        print(f"    {bad} missing pyobjc-framework-ApplicationServices")
        print(f"      {dim}fix: pip install pyobjc-framework-ApplicationServices, then run setup again{reset}\n")
        return 1

    print(f"\n  {bold}What he reads{reset}")
    for what, how in (
        ("Wispr Flow", "your dictations; he never opens the mic"),
        ("Claude Code, Codex", "what you type into the chats"),
        ("other apps", "Gmail, Notes, Slack: needs Accessibility, next"),
    ):
        print(f"    {what:<21}{dim}{how}{reset}")
    print(f"    {dim}Once a night the day's sentences go to your Claude Code or Codex CLI for grammar.{reset}")

    print(f"\n  {bold}Background jobs{reset}")
    # The listener asks macOS for Accessibility itself: a prompt from this
    # process would name Terminal, which is not what runs in the background.
    (config.DATA_DIR / ".asked-accessibility").unlink(missing_ok=True)
    textboxes.GRANTED.unlink(missing_ok=True)
    try:
        for line in schedule.install():
            print(f"    {ok} {line}")
    except schedule.InstallationError as exc:
        for line in str(exc).splitlines():
            print(f"    {bad} {line}")
        print("\n  Run `tharoor setup` again. Nothing needs sudo.\n")
        return 1

    print(f"\n  {bold}Accessibility{reset}")
    python = os.path.realpath(sys.executable)
    granted = _wait_for(textboxes.GRANTED, 5)
    if not granted:
        print(f"    macOS is asking now. In the window that opens, switch on {bold}{Path(python).name}{reset}")
        print(f"    {dim}({python}). Not in the list? Press +, then Cmd-Shift-G and paste that path.{reset}")
        subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
                       capture_output=True)
        if sys.stdin.isatty():
            print(f"    {dim}Waiting for you (press Enter to skip)...{reset}", flush=True)
            granted = _wait_for(textboxes.GRANTED, 300, skippable=True)
    if granted:
        print(f"    {ok} granted: he can read the box you are typing in")
    else:
        print(f"    {bad} not yet: Wispr and the chats still work. Switch it on any time; he notices.")

    print(f"\n  {bold}Ready.{reset} He runs in the background and starts on every login.")
    print(f"  {dim}23:30 he checks the day. 08:30 the lesson opens by itself.{reset}\n")
    print(f"    tharoor          {dim}what he does and what is running{reset}")
    print(f"    tharoor logs     {dim}what the background jobs did{reset}\n")
    return 0


def _wait_for(path: Path, seconds: float, skippable: bool = False) -> bool:
    """True once `path` exists. Enter gives up early when `skippable`."""
    import select
    import time

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists():
            return True
        if skippable and select.select([sys.stdin], [], [], 1)[0]:
            sys.stdin.readline()
            return False
        if not skippable:
            time.sleep(0.5)
    return path.exists()


def cmd_listen(args: argparse.Namespace) -> int:
    """Read the text box you are typing in, until stopped."""
    import signal
    import threading

    from . import log, textboxes

    logger = log.get("listener")
    done = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: done.set())
    signal.signal(signal.SIGINT, lambda *_: done.set())
    stop_typing = textboxes.start(logger)
    done.wait(args.seconds)
    stop_typing.set()
    return 0


def cmd_analyse_day(args: argparse.Namespace) -> int:
    from . import schedule

    with schedule.job_lock("analysis") as acquired:
        if not acquired:
            print("  Analysis is already running; the next scheduled check will retry.")
            return 1
        return _analyse_day(args)


def _analyse_day(args: argparse.Namespace) -> int:
    """The nightly job. Every step logged, so a failure is never silent.

    Two sources: what you dictated into Wispr Flow (its raw transcript, and
    your own hand corrections), and what you typed (Claude Code, Codex, and
    other apps' text boxes).
    """
    from dataclasses import asdict
    from datetime import date, datetime, timedelta

    from . import grammar, log, report, schedule, typed, wispr

    when = date.fromisoformat(args.day) if args.day else date.today()
    logger = log.get("nightly")

    files, freed = config.purge_expired(when)
    if files:
        logger.info(f"deleted {files} expired files, freed {freed} MB")
        print(f"  deleted {files} files older than {config.KEEP_DAYS} days ({freed} MB)")

    if schedule.on_battery() and not args.force:
        logger.info("on battery, skipping (use --force to override)")
        print("  On battery. Skipping so nothing drains in your bag. --force to override.")
        return 0

    grammar_findings = []
    spoken_texts: list[tuple[str, str]] = []  # everything said today, for one grammar pass
    sources = {"wispr": 0, "typed": 0}

    with log.step("nightly", day=str(when)):
        # ---- source 1: Wispr Flow ----
        dictations: list = []
        if wispr.available():
            try:
                dictations = wispr.for_day(when)
            except wispr.SchemaChanged as exc:
                logger.error(f"Wispr reader disabled: {exc}")
                print(f"  Wispr Flow database changed shape: {exc}")
                print("  Previous report kept; see `tharoor logs`.")
                return 1
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Wispr read failed: {type(exc).__name__}: {exc}")
                print("  Wispr Flow could not be read. Previous report kept; see `tharoor logs`.")
                return 1
            print(f"  {len(dictations)} dictations in Wispr Flow for {when}")
            for d in dictations:
                label = f"{when}-wispr-{d.id}"
                # Raw ASR, not the cleaned text: Wispr's model has already
                # fixed the grammar in `meant`, so marking that finds nothing.
                if d.heard:
                    spoken_texts.append((label, d.heard))
                    sources["wispr"] += 1
                if d.edited:  # your own hand corrections are the best evidence there is
                    grammar_findings += grammar.compare(d.heard, d.meant, label, edited=True)
        else:
            print("  Wispr Flow not found; grammar from your typing only")

        # ---- source 2: what you typed (Claude Code, Codex, other apps' text boxes) ----
        spoken_now = [text for _, text in spoken_texts]
        try:
            typed_texts = typed.for_day(when, exclude=spoken_now + [d.meant for d in dictations])
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"typed source unavailable: {type(exc).__name__}: {exc}")
            typed_texts = []
        sources["typed"] = len(typed_texts)
        print(f"  {len(typed_texts)} typed messages for {when}")

        # ---- grammar, over both halves of the day, in as few calls as possible ----
        # The local rules run either way. They are few, but they are certain,
        # and a measured probe showed the model skipping one of them on every
        # run -- a rule never has an off night.
        rules = [f for label, text in spoken_texts for f in grammar.check(text, label, "spoken")]
        rules += [f for label, text in typed_texts for f in grammar.check(text, label, "typed")]
        grammar_failed: list[str] = []
        if grammar.llm_available():
            print(f"  checking grammar on {len(spoken_texts)} utterances and {len(typed_texts)} messages")
            found = grammar.llm_check(spoken_texts, "spoken", logger=logger, failed=grammar_failed)
            found += grammar.llm_check(typed_texts, "typed", logger=logger, failed=grammar_failed)
            grammar_findings += grammar.merge(found, rules)
        else:
            logger.warning("neither Claude Code nor Codex CLI found; grammar falls back to local rules")
            grammar_findings += rules

        # Raw corrections are kept per day; the report's habits are counted
        # over the last week, because one day rarely repeats a phrase twice
        # and a habit is by definition something that repeats.
        config.write_json_atomically(
            config.REPORTS_DIR / f"{when.isoformat()}-grammar-raw.json",
            [asdict(g) for g in grammar_findings],
        )
        # Habits come from the last seven days of Wispr's own history, not
        # from files we happen to have written. Keying off our own output
        # meant the first ever run had one day of data, a habit needs to
        # repeat, and a single day rarely repeats a phrase -- so the section
        # was empty on exactly the run where it should have had a week of
        # material sitting in Wispr's database already.
        week: list = []
        if wispr.available():
            cutoff = datetime.combine(
                    when - timedelta(days=grammar.HABIT_WINDOW_DAYS - 1), datetime.min.time()
                ).astimezone()
            try:
                for d in wispr.dictations(since=cutoff):
                    if d.when.date() <= when:
                        week += grammar.compare(d.heard, d.meant, f"{d.when.date()}-wispr-{d.id}", edited=d.edited)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"weekly grammar pass failed: {type(exc).__name__}: {exc}")
                week = list(grammar_findings)
        for back in range(grammar.HABIT_WINDOW_DAYS):
            raw = config.REPORTS_DIR / f"{(when - timedelta(days=back)).isoformat()}-grammar-raw.json"
            if raw.exists():
                try:
                    week += [grammar.GrammarFinding(**row) for row in json.loads(raw.read_text())]
                except (ValueError, TypeError):
                    logger.warning(f"could not read grammar history for {raw.name}")
        # Include local reading suggestions too, even when Wispr is present.
        week += grammar_findings
        # Yesterday's mistakes first, then the habits that keep coming back.
        # Requiring a repeat was why this section was empty every morning: a
        # correction you make once is still a correction you need to see.
        today_keys = {(f.kind, f.said, f.should_be) for f in grammar_findings}
        rows = [row for row in grammar.summarise(week, limit=200)
                if row["times"] >= 2 or (row["kind"], row["said"], row["should_be"]) in today_keys]
        rows.sort(key=lambda r: ((r["kind"], r["said"], r["should_be"]) not in today_keys, -r["times"]))
        # Capped per section, not overall: speech outnumbers typing most days,
        # and a single global cap silently emptied the typing half of the page.
        grammar_rows = ([r for r in rows if (r.get("mode") or "spoken") == "spoken"][:10]
                        + grammar.typed_rows(rows, 6))
        config.write_json_atomically(config.REPORTS_DIR / f"{when}-grammar.json", grammar_rows)
        analysis = {
            "version": report.ANALYSIS_VERSION, "completed_at": datetime.now().isoformat(),
            "sources": sources,
            "grammar_engine": f"{grammar.llm_name()}-cli" if grammar.llm_available() else "local-rules",
            "grammar_found": len(grammar_findings),
            # Lid shut mid-run wakes the Mac in DarkWake with no network (5 Oct).
            # The page is still written for the morning; analyse-pending redoes the day.
            "grammar_failed": grammar_failed,
        }
        written = report.write(when, grammar=grammar_rows, analysis=analysis)
        analysis["outputs"] = sorted(written)
        config.write_json_atomically(config.REPORTS_DIR / f"{when}-analysis.json", analysis)

    log.event("nightly_done", day=str(when), grammar=len(grammar_findings), **sources)
    print(f"\n  {len(grammar_findings)} grammar corrections ({len(grammar_rows)} on the page)")
    for kind, path in written.items():
        print(f"  {kind}: {path}")
    return 0


def _online() -> bool:
    import socket

    try:
        socket.create_connection(("api.anthropic.com", 443), timeout=5).close()
        return True
    except OSError:
        return False


def cmd_analyse_pending(args: argparse.Namespace) -> int:
    """Catch up retained days after sleep/login; completed days are not checked again."""
    from datetime import datetime, timedelta

    from . import report

    now = datetime.now()
    # Yesterday's review should not wait behind several older days.
    days = [now.date() - timedelta(days=n) for n in range(1, 4)]
    if (now.hour, now.minute) >= (23, 30):
        days.append(now.date())
    # Only days retention still keeps. The 23:30 run on day T deletes
    # everything before T - (KEEP_DAYS - 1); catching up an older day
    # rebuilt the very report that had just been deleted, every 15 min (6-7 Oct).
    last_purge = now.date() if (now.hour, now.minute) >= (23, 30) else now.date() - timedelta(days=1)
    days = [d for d in days if d >= last_purge - timedelta(days=config.KEEP_DAYS - 1)]
    failed = False
    for day in days:
        marker = config.REPORTS_DIR / f"{day}-analysis.json"
        if marker.exists():
            try:
                completed = json.loads(marker.read_text())
                completed_at = datetime.fromisoformat(completed["completed_at"])
                if completed.get("grammar_failed") and (
                        now - completed_at < timedelta(hours=1) or not _online()):
                    continue  # retried hourly once online; a logged-out CLI must not loop every 15 min
                if (completed.get("version") == report.ANALYSIS_VERSION
                        and not completed.get("grammar_failed")
                        and (completed_at.date() > day or (day == now.date()
                             and (completed_at.hour, completed_at.minute) >= (23, 30)))):
                    from . import schedule

                    with schedule.job_lock("analysis") as acquired:
                        if not acquired:
                            print("  Analysis is already running; export recovery will retry later.")
                            return 1
                        if not report.repair_exports(day, completed):
                            failed = True
                            print(f"  {day}: report page still missing; will retry at the next check.")
                    continue
            except (ValueError, TypeError, KeyError):
                pass
        result = cmd_analyse_day(argparse.Namespace(day=str(day), force=args.force))
        failed = failed or bool(result)
    # A Mac asleep at 08:30 finishes yesterday mid-morning; open it now rather
    # than at the morning job's next 15-min tick. _morning keeps its own gates
    # (08-21 h, mic in use, already opened today), so this is a no-op otherwise.
    cmd_morning(argparse.Namespace(automatic=True))
    return int(failed)


def cmd_morning(args: argparse.Namespace) -> int:
    from . import schedule

    with schedule.job_lock("morning") as acquired:
        if not acquired:
            return 0
        return _morning(args)


def _morning(args: argparse.Namespace) -> int:
    """08:30. Open yesterday's report and say good morning."""
    import subprocess
    from datetime import date, datetime, timedelta

    from . import log, report

    automatic = getattr(args, "automatic", False)
    state_path = config.DATA_DIR / "morning.json"
    if automatic:
        from . import micgate

        if not 8 <= datetime.now().hour < 21 or micgate.is_mic_in_use():
            return 0
    day = report.latest_day(before=date.today())
    if day is None:
        print("  No completed report yet. Analysis will catch up at the next scheduled check.")
        return 0
    marker = config.REPORTS_DIR / f"{day}-analysis.json"
    try:
        analysis = json.loads(marker.read_text())
        complete = not analysis.get("grammar_failed")
        redo_due = datetime.now() - datetime.fromisoformat(analysis["completed_at"]) >= timedelta(hours=1)
    except (OSError, ValueError, KeyError):
        complete, redo_due = True, False
    if automatic:
        # Waking at 9 or at 1 pm is the same: the catch-up job is still making
        # yesterday's page, or about to redo a grammar check that ran with no
        # network. Wait for it (both jobs tick every 15 min) instead of opening
        # an older or half page. If the redo also fails (both CLIs logged out),
        # its fresh completed_at ends the wait and the half page opens.
        if day != date.today() - timedelta(days=1):
            print("  Yesterday is still being analysed; opening it when ready.")
            return 0
        if not complete and redo_due and _online():
            print("  Yesterday's grammar is about to be redone; opening it when ready.")
            return 0
    if automatic and state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            # Opened a half page (offline all morning)? Open again once it is whole.
            if (state.get("opened_on") == str(date.today()) and state.get("report_day") == str(day)
                    and (state.get("complete", True) or not complete)):
                return 0
        except (ValueError, TypeError):
            pass
    with log.step("morning"):
        path = report.open_report(day)
        grammar_file = config.REPORTS_DIR / f"{day.isoformat()}-grammar.json"
        habits = json.loads(grammar_file.read_text()) if grammar_file.exists() else []
        name = config.user_name()
        if path:
            body = (f"{len(habits)} correction{'s' if len(habits) != 1 else ''} from {day:%A}. "
                    "The lesson is open in your browser.")
            subprocess.run(
                ["osascript", "-e",
                 f'display notification {json.dumps(body)} with title '
                 f'{json.dumps(f"Good morning, {name}")} sound name "Glass"'],
                capture_output=True,
            )
            config.write_json_atomically(state_path, {"opened_on": str(date.today()), "report_day": str(day),
                                                      "complete": complete})
    if path:
        print(f"  Good morning, {name}. Opened {path}")
    else:
        print("  no report to open yet")
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    from . import log

    print(f"  health: {log.health()}")
    print()
    print(log.tail(args.lines))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tharoor", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    setup_cmd = sub.add_parser("setup", help="one command to get running")
    setup_cmd.set_defaults(func=cmd_setup)

    listen_cmd = sub.add_parser("listen", help="the background job: reads your typing")
    listen_cmd.add_argument("--seconds", type=float, default=None, help="stop after N seconds")
    listen_cmd.set_defaults(func=cmd_listen)

    day_cmd = sub.add_parser("analyse-day", help="the 23:30 job")
    day_cmd.add_argument("--day", help="YYYY-MM-DD, defaults to today")
    day_cmd.add_argument("--force", action="store_true", help="run even on battery")
    day_cmd.set_defaults(func=cmd_analyse_day)

    pending = sub.add_parser("analyse-pending", help="catch up unprocessed days after sleep or login")
    pending.add_argument("--force", action="store_true", help="also analyse while on battery")
    pending.set_defaults(func=cmd_analyse_pending)

    morning_cmd = sub.add_parser("morning", help="the 08:30 job")
    morning_cmd.add_argument("--automatic", action="store_true", help="open once per day, outside calls and quiet hours")
    morning_cmd.set_defaults(func=cmd_morning)

    logs_cmd = sub.add_parser("logs", help="what the scheduled jobs did")
    logs_cmd.add_argument("--lines", type=int, default=30)
    logs_cmd.set_defaults(func=cmd_logs)

    install = sub.add_parser("install", help="run every day by itself")
    install.add_argument("--remove", action="store_true")
    install.add_argument("--status", action="store_true")
    install.add_argument("--dry-run", action="store_true")
    install.set_defaults(func=cmd_install)

    return parser


def main(argv: list[str] | None = None) -> int:
    if not (sys.argv[1:] if argv is None else argv):
        from . import welcome

        return welcome.show()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
