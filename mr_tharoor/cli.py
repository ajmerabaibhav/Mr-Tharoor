"""Mr Tharoor, your pronunciation teacher.

    roy drill version three       say it after him, three times each
    roy say version               hear it once
    roy look comfortable          IPA and source, no sound
    roy check                     judge his flags, so we learn if he is right
    roy score                     how accurate he has actually been
    roy setup                     one command: check, permit, download, schedule
    roy listen                    start listening (context-aware, all day)
    roy analyse-day               the 23:30 job: score today, build the report
    roy morning                   the 08:30 job: open it, send reminders
    roy probe                     record the 20 sentences that test if he works
    roy analyse                   score those recordings, see if he can hear you
    roy mictest                   compare microphones, find your best setup
    roy install                   run every day by itself (launchd)
    roy remind                    what Mr Tharoor would nudge you about
    roy gate                      is the mic gate working on this Mac
    roy cache                     what is already offline
"""

from __future__ import annotations

import argparse
import json
import sys

import time
from datetime import date

from . import accuracy, config, dictionary, micgate, probe, streaks


def cmd_say(args: argparse.Namespace) -> int:
    missing = 0
    for word in args.words:
        entry = dictionary.play(word)
        print(f"  {entry}")
        if entry.source == "missing":
            missing += 1
            print(f"    no recording found for {word!r}")
        elif entry.source == "synthetic":
            print("    no human recording on Wiktionary, used the macOS voice")
    return 1 if missing == len(args.words) else 0


TIPS = {
    "v->w": "Top teeth on the bottom lip, then voice it. Not a rounded w.",
    "th->t": "Tongue between the teeth and blow. It should feel silly.",
    "z->s": "Same mouth as s, but switch your voice on. Feel your throat buzz.",
    "zh->j": "Soft, like the middle of treasure. No d in front of it.",
    "stress": "Punch the marked syllable and let the others fall away.",
}


def cmd_drill(args: argparse.Namespace) -> int:
    """Hear it, say it, hear it again. The whole learning loop.

    Two plays with a gap, because the gap is where you speak. A single play
    is a lookup; a play, a silence and a play is practice.
    """
    words = args.words
    if not words:
        rows = streaks.tonights_report()
        words = [w for row in rows for w in row.words[:2]][:4]
        if not words:
            print("Nothing to drill yet. Mr Tharoor has not heard you speak.")
            print("Give him words directly:  roy drill version three")
            return 0
        print("Tonight's worst, from your own speech:\n")

    for word in words:
        entry = dictionary.lookup(word)
        if not entry.audio_path:
            print(f"  {word}: no recording available, skipping")
            continue

        label = "human" if entry.is_human else "robot"
        print(f"  {word}  {entry.ipa or ''}  [{label}]")
        for round_number in range(1, args.times + 1):
            dictionary.play(word)
            if round_number < args.times:
                print(f"     now you say it  ({round_number}/{args.times})")
                time.sleep(args.gap)
        print()
    print("Done. Two minutes a day beats an hour once a week.")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Label what he flagged, so we find out whether he is any good.

    This is the only source of truth in the whole system. Every threshold in
    evidence.py is currently my guess; your answers here are what turn those
    guesses into settings.
    """
    rows = streaks.tonights_report()
    if not rows:
        print("Nothing flagged to check yet.")
        print("Mr Tharoor needs to have heard you speak first.")
        return 0

    pending = [(row, word) for row in rows for word in row.words[: args.per_sound]]
    print(f"{len(pending)} flags to judge. y = I did say it wrong, n = I said it fine,")
    print("s = skip, u = cannot tell. Ctrl-C to stop; answers are saved as you go.\n")

    saved = 0
    for row, word in pending:
        entry = dictionary.lookup(word)
        print(f"  {word}  ({row.contrast})   Mr Tharoor is {row.lower_bound:.0%} sure")
        if entry.audio_path:
            print("     playing the correct pronunciation...")
            dictionary.play(word)
        try:
            answer = input("     did you say it wrong? [y/n/s/u] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  stopped.")
            break
        verdict = {
            "y": accuracy.HIT,
            "n": accuracy.FALSE_ALARM,
            "u": accuracy.UNSURE,
        }.get(answer)
        if verdict is None:
            continue
        accuracy.record(
            accuracy.Label(
                day=date.today().isoformat(),
                word=word,
                contrast=row.contrast,
                verdict=verdict,
                lower_bound=row.lower_bound,
            )
        )
        saved += 1

    print(f"\n  {saved} judgements saved. Run `roy score` to see what they say.")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    """How right has Mr Tharoor actually been?"""
    card = accuracy.scorecard()
    print(f"  {card.verdict}\n")
    if card.flagged:
        low, est, high = card.precision
        print(f"  Of {card.flagged} flags you judged, {card.hits} were real.")
        print(f"  Precision: {est:.0%}   (somewhere between {low:.0%} and {high:.0%})")
    if card.misses or card.clean:
        low, est, high = card.recall
        print(f"  Recall:    {est:.0%}   (between {low:.0%} and {high:.0%}, "
              f"from {card.audited} audited)")
    if card.unsure:
        print(f"  {card.unsure} you could not tell. Not counted either way.")

    per_sound = accuracy.by_contrast()
    if per_sound:
        print("\n  By sound:")
        for contrast, sound_card in per_sound.items():
            if not sound_card.flagged:
                continue
            low, est, _ = sound_card.precision
            print(f"    {contrast:10} {sound_card.hits}/{sound_card.flagged} real  "
                  f"({est:.0%}, at least {low:.0%})")

    suggestion = accuracy.suggested_threshold()
    if suggestion:
        threshold, why = suggestion
        print(f"\n  Suggested REPORT_THRESHOLD: {threshold:.2f}")
        print(f"    {why}")
    elif card.flagged < 20:
        print(f"\n  Judge {20 - card.flagged} more with `roy check` for a threshold suggestion.")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """Record the go/no-go set. Twenty sentences, about ten minutes.

    Read them the way you would say them to a colleague. Reading carefully is
    the one way to get a misleading result, because the tool has to work on
    how you actually talk, not on how you read.
    """
    if args.list:
        import sounddevice as sd

        for index, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0:
                print(f"  [{index}] {dev['name']}  ({dev['default_samplerate']:.0f} Hz)")
        return 0

    try:
        device, device_name, warning = probe.choose_input()
    except Exception as exc:
        print(f"Cannot reach the microphone: {type(exc).__name__}: {exc}")
        return 1
    if args.device is not None:
        device = args.device
        device_name = f"device {args.device}"
        warning = None

    done = set(probe.recorded())
    todo = [s for s in probe.SENTENCES if s.number not in done or args.redo]
    if not todo:
        print(f"All {len(probe.SENTENCES)} recorded. Re-record with --redo.")
        return 0

    if done and not args.redo:
        print(f"{len(done)} already recorded, {len(todo)} to go.\n")
    print(f"Microphone: {device_name}")
    if warning:
        print(f"  note: {warning}")
    print()
    print("Press ENTER to start each one, speak, then press ENTER again to stop.")
    print("Say them naturally. Block A slowly and clearly, Block B at call speed.\n")

    block_shown = None
    for sentence in todo:
        if sentence.block != block_shown:
            block_shown = sentence.block
            how = ("minimal pairs, say them clearly"
                   if block_shown == "A" else "normal speed, like you are on a call")
            print(f"\n--- BLOCK {block_shown}: {how} ---\n")

        print(f"  {sentence.number:2d}/20  {sentence.text}")
        try:
            input("         ENTER to record, ENTER again to stop  ")
        except (EOFError, KeyboardInterrupt):
            print("\n  stopped. Progress is saved; run `roy probe` again to continue.")
            return 0
        try:
            path = probe.record_one(sentence, seconds=args.seconds, device=device)
        except KeyboardInterrupt:
            print("\n  stopped. Progress is saved.")
            return 0
        except Exception as exc:
            print(f"         recording failed: {type(exc).__name__}: {exc}")
            print("         check microphone permission for your terminal, then retry")
            return 1
        print(f"         saved {path.name}\n")

    print(f"\nAll {len(probe.recorded())} recorded in {probe.PROBE_DIR}")
    print("Next: the phoneme model scores these and we find out if Mr Tharoor works.")
    return 0


def cmd_analyse(args: argparse.Namespace) -> int:
    """Score the probe recordings. This is the go/no-go number."""
    from . import listen, probe

    numbers = probe.recorded()
    if not numbers:
        print("No recordings yet. Run `roy probe` first.")
        return 1

    print(f"Scoring {len(numbers)} recordings. First run loads a 1.2GB model.\n")
    print(f"{'#':>3} {'blk':>3} {'SNR':>8} {'match':>7}  flagged")
    print("-" * 44)
    by_block: dict[str, list[float]] = {"A": [], "B": []}
    total_flagged = 0
    for sentence in probe.SENTENCES:
        if sentence.number not in numbers:
            continue
        result = listen.analyse(str(probe.wav_path(sentence.number)), sentence.text)
        expected = result["expected"]
        tokens = [listen.Token(x, 1.0, 0.0) for x in result["heard"]]
        diffs = listen.align(expected, tokens)
        wrong = sum(1 for d in diffs if d.expected)
        rate = (len(expected) - wrong) / max(len(expected), 1)
        by_block[sentence.block].append(rate)
        total_flagged += len(result["scored"])
        snr = result["quality"]["snr_db"]
        print(f"{sentence.number:>3} {sentence.block:>3} {snr:>7.1f}dB {rate:>7.0%} "
              f"{len(result['scored']):>8}")

    print()
    for block, rates in by_block.items():
        if rates:
            kind = "minimal pairs" if block == "A" else "connected speech"
            print(f"  Block {block} ({kind:<17}): {sum(rates)/len(rates):.0%} match")
    print(f"\n  {total_flagged} contrast errors flagged.")
    print("  Reference: 83% on clean native-speaker audio.")
    print("\n  A low match rate here is ambiguous on purpose: it means either he")
    print("  cannot hear you, or you genuinely say it differently. Only `roy check`")
    print("  can tell those apart, because only you know which it was.")
    return 0


def cmd_mictest(args: argparse.Namespace) -> int:
    """Find the best microphone setup on this Mac, by measuring not guessing.

    Signal-to-noise is decided at the microphone, so this is the highest
    leverage thing you can change. Three ways of recording the same sentence,
    same words, same room, and the numbers decide.
    """
    from . import capture, clean, listen

    sentence = "The vet was wet, and the zoo sued us for three days."
    setups = [
        ("laptop mic, arm's length", "sit normally, as you did the first time", False),
        ("laptop mic, a hand-span", "lean in close to the screen", False),
        ("laptop + voice processing", "same close position, Apple's noise path on", True),
    ]
    if not capture.available():
        print("pyobjc is missing: pip install pyobjc-framework-AVFoundation")
        return 1

    print("Say this line each time:\n")
    print(f'   "{sentence}"\n')
    results = []
    for name, how, voice in setups:
        print(f"  {name}  --  {how}")
        try:
            input("     ENTER to record 8 seconds, then speak  ")
        except (EOFError, KeyboardInterrupt):
            print("\n  stopped.")
            return 0
        path = f"/tmp/mictest-{len(results)}.wav"
        info = capture.record(8.0, path, voice_processing=voice)
        quality = listen.audio_quality(path)
        expected, _ = listen.expected_phonemes(sentence)
        tokens = listen.heard(path)
        diffs = listen.align(expected, tokens)
        wrong = sum(1 for d in diffs if d.expected)
        match = (len(expected) - wrong) / max(len(expected), 1)
        results.append((name, quality["snr_db"], match, info["voice_processing"]))
        print(f"     SNR {quality['snr_db']:.1f} dB, {match:.0%} of sounds recognised\n")

    print(f"\n  {'setup':<28} {'SNR':>8} {'match':>7}")
    print("  " + "-" * 46)
    for name, snr, match, _ in results:
        print(f"  {name:<28} {snr:>7.1f}dB {match:>7.0%}")
    best = max(results, key=lambda r: r[2])
    print(f"\n  Best: {best[0]} ({best[1]:.0f} dB, {best[2]:.0%})")
    print("  Use that position from now on. It costs nothing and beats any algorithm.")
    return 0


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
    for line in schedule.install(dry_run=args.dry_run):
        print(f"  {line}")
    print("\n  A missed run is not skipped: launchd fires it when you next open the lid.")
    print("  Remove anytime with `roy install --remove`. Nothing needs sudo.")
    return 0


def cmd_remind(args: argparse.Namespace) -> int:
    from . import remind

    print("  queue:", remind.summary())
    allowed, why = remind.may_interrupt()
    print(f"  may interrupt now: {allowed}{' (' + why + ')' if why else ''}")
    print()
    result = remind.run(dry_run=not args.send)
    if args.send:
        print(f"  sent {result['sent']} notifications")
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    """Everything a fresh clone needs, in the order it needs it.

    Written because the alternative is a README a person follows wrongly.
    Each step says what it is doing and what it costs, and a failure names
    the fix rather than a traceback.
    """
    import platform
    import shutil

    from . import schedule

    problems = []
    print("Mr Tharoor setup\n")

    print("  1. this machine")
    if platform.system() != "Darwin":
        print(f"     {platform.system()} is not supported. macOS only, for now.")
        return 1
    version = platform.mac_ver()[0]
    print(f"     macOS {version} on {platform.machine()}  ok")

    print("\n  2. libraries")
    required = {
        "numpy": "numpy", "soundfile": "soundfile", "sounddevice": "sounddevice",
        "cmudict": "cmudict", "torch": "torch", "transformers": "transformers",
        "faster_whisper": "faster-whisper", "AVFoundation": "pyobjc-framework-AVFoundation",
        "AppKit": "pyobjc-framework-Cocoa",
    }
    missing = []
    for module, package in required.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if missing:
        print(f"     missing: {', '.join(missing)}")
        print(f"     fix: pip install {' '.join(missing)}")
        problems.append("libraries")
    else:
        print(f"     all {len(required)} present  ok")

    if problems:
        print("\n  Stopping here. Install the libraries above and run `roy setup` again.")
        return 1

    print("\n  3. microphone permission")
    print("     recording half a second. macOS will ask once, say yes.")
    try:
        from . import capture

        info = capture.record(0.6, str(config.DATA_DIR / ".setup-check.wav"))
        (config.DATA_DIR / ".setup-check.wav").unlink(missing_ok=True)
        if info["peak"] == 0:
            print("     got silence. Grant access in System Settings > Privacy > Microphone.")
            problems.append("microphone")
        else:
            vp = "with Apple voice processing" if info["voice_processing"] else "raw"
            print(f"     captured {info['channels']} channel(s) {vp}  ok")
    except Exception as exc:
        print(f"     failed: {type(exc).__name__}: {exc}")
        print("     grant access in System Settings > Privacy & Security > Microphone")
        problems.append("microphone")

    print("\n  4. models (about 3 GB, downloaded once, then offline forever)")
    if args.skip_models:
        print("     skipped. They download on first use instead.")
    else:
        from . import listen

        try:
            print("     phoneme recogniser...", end=" ", flush=True)
            listen._model()
            print("ok")
            print("     speech recogniser...", end=" ", flush=True)
            listen._whisper()
            print("ok")
        except Exception as exc:
            print(f"failed: {type(exc).__name__}: {exc}")
            print("     they will retry on first use; check your connection")
            problems.append("models")

    print("\n  5. schedule")
    for line in schedule.install():
        print(f"     {line}")

    print("\n" + ("-" * 58))
    if problems:
        print(f"  Set up with problems: {', '.join(problems)}")
        print("  Fix those and run `roy setup` again.")
        return 1
    print("  Ready. Mr Tharoor is listening now and starts on every login.")
    print()
    print("  Talk normally. At 23:30 he analyses the day, at 08:30 the report")
    print("  opens by itself. Nothing leaves this machine.")
    print()
    print("  roy gate     is he listening right now, and why")
    print("  roy mictest  find your best microphone setup")
    print("  roy logs     what the scheduled jobs did")
    return 0


def cmd_listen(args: argparse.Namespace) -> int:
    from . import listener

    worker = listener.Listener(use_voice_processing=not args.raw)
    stats = worker.run(max_seconds=args.seconds)
    print(f"  {stats.as_dict()}")
    return 0


def cmd_analyse_day(args: argparse.Namespace) -> int:
    """The nightly job. Every step logged, so a failure is never silent.

    Two sources, best first:

      Wispr Flow's own database. Clean close-mic audio already paired with
      the words you meant, worked out by a model that saw the whole sentence.
      Also the source of grammar corrections: what it heard against what it
      decided you meant, and what you fixed by hand.

      Our own recordings. Meetings, calls, reading aloud: the things Wispr
      never hears. Words come from Whisper, which is weaker, so these count
      for a little less.
    """
    from datetime import date as _date, datetime

    from . import daily, grammar, listener, listen, log, remind, report, schedule, streaks, wispr

    when = _date.fromisoformat(args.day) if args.day else _date.today()
    logger = log.get("nightly")

    files, freed = streaks.purge_expired_audio(when)
    if files:
        logger.info(f"deleted {files} expired recordings, freed {freed} MB")
        print(f"  cleaned up {files} old recordings ({freed} MB), tallies kept")

    if schedule.on_battery() and not args.force:
        logger.info("on battery, skipping (use --force to override)")
        print("  On battery. Skipping so nothing drains in your bag. --force to override.")
        return 0

    findings = []
    grammar_findings = []
    sources = {"wispr": 0, "own": 0}

    with log.step("nightly", day=str(when)):
        # ---- source 1: Wispr Flow ----
        if wispr.available():
            try:
                dictations = wispr.for_day(when)
            except wispr.SchemaChanged as exc:
                logger.error(f"Wispr reader disabled: {exc}")
                print(f"  Wispr Flow database changed shape: {exc}")
                dictations = []
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Wispr read failed: {type(exc).__name__}: {exc}")
                dictations = []
            print(f"  {len(dictations)} dictations in Wispr Flow for {when}")
            folder = listener.sessions_dir(when)
            for index, d in enumerate(dictations, 1):
                grammar_findings += grammar.compare(d.heard, d.meant, f"wispr-{d.id[:8]}")
                path = wispr.write_wav(d, folder)
                if not path:
                    continue
                quality = listen.audio_quality(str(path))
                if not quality["usable"]:
                    continue
                findings += daily.findings_for(str(path), d.meant, f"wispr-{d.id[:8]}")
                sources["wispr"] += 1
                if index % 10 == 0:
                    print(f"    {index}/{len(dictations)} dictations, {len(findings)} sound findings so far")
        else:
            print("  Wispr Flow not found; using our own recordings only")

        # ---- source 2: our own recordings (meetings, calls, reading aloud) ----
        chunks = listener.todays_audio(when)
        print(f"  {len(chunks)} recordings of our own for {when}")
        for index, chunk in enumerate(chunks, 1):
            quality = listen.audio_quality(str(chunk))
            if not quality["usable"]:
                logger.info(f"skip {chunk.name}: SNR {quality['snr_db']}dB is room tone")
                continue
            for segment in listen.transcribe(str(chunk)):
                findings += daily.findings_for(
                    str(chunk), segment["text"], f"{chunk.stem}-{int(segment['start'])}"
                )
            sources["own"] += 1
            if index % 10 == 0:
                print(f"    {index}/{len(chunks)} recordings, {len(findings)} sound findings so far")

        if not findings and not grammar_findings:
            logger.info(f"nothing to report for {when}")
            print("  Nothing heard. Dictate into Wispr, or make sure `roy listen` is running.")
            return 0

        daily.attach_pronunciations(findings)
        daily.save(findings, when)
        # Raw corrections are kept per day; the report's habits are counted
        # over the last week, because one day rarely repeats a phrase twice
        # and a habit is by definition something that repeats.
        from dataclasses import asdict as _asdict
        from datetime import timedelta as _td
        import json as _json

        config.write_json_atomically(
            config.REPORTS_DIR / f"{when.isoformat()}-grammar-raw.json",
            [_asdict(g) for g in grammar_findings],
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
                    when - _td(days=grammar.HABIT_WINDOW_DAYS - 1), datetime.min.time()
                ).astimezone()
            try:
                for d in wispr.dictations(since=cutoff, with_audio=False):
                    if d.when.date() <= when:
                        week += grammar.compare(d.heard, d.meant, f"wispr-{d.id[:8]}")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"weekly grammar pass failed: {type(exc).__name__}: {exc}")
                week = list(grammar_findings)
        else:
            for back in range(grammar.HABIT_WINDOW_DAYS):
                raw = config.REPORTS_DIR / f"{(when - _td(days=back)).isoformat()}-grammar-raw.json"
                if raw.exists():
                    week += [grammar.GrammarFinding(**row) for row in _json.loads(raw.read_text())]
        grammar_rows = [row for row in grammar.summarise(week, limit=10) if row["times"] >= 2]
        config.write_json_atomically(
            config.REPORTS_DIR / f"{when.isoformat()}-grammar.json", grammar_rows
        )
        added = remind.enqueue(findings)
        written = report.write(findings, when, grammar=grammar_rows)

    log.event("nightly_done", day=str(when), findings=len(findings),
              grammar=len(grammar_findings), cards=added, **sources)
    print(f"\n  {len(findings)} sound findings, {len(grammar_findings)} grammar corrections "
          f"({len(grammar_rows)} habits), {added} new reminder cards")
    for kind, path in written.items():
        print(f"  {kind}: {path}")
    return 0


def cmd_morning(args: argparse.Namespace) -> int:
    """08:30. Open yesterday's report and say good morning."""
    import json
    import subprocess
    from datetime import date as _date, timedelta

    from . import daily, log, remind, report

    yesterday = _date.today() - timedelta(days=1)
    day = yesterday if (config.REPORTS_DIR / f"{yesterday.isoformat()}.html").exists() else _date.today()
    with log.step("morning"):
        path = report.open_report(day)
        findings = daily.load(day)
        grammar_file = config.REPORTS_DIR / f"{day.isoformat()}-grammar.json"
        habits = json.loads(grammar_file.read_text()) if grammar_file.exists() else []
        sounds = len({f.contrast for f in findings})
        name = config.user_name()
        thrown = log.too_far(day)
        if path:
            body = (
                f"{sounds} sound{'s' if sounds != 1 else ''} and "
                f"{len(habits)} phrase{'s' if len(habits) != 1 else ''} from {day:%A}. "
                f"The report is open."
            )
            # Said here because here is where it can still change something:
            # the only lever on audio quality is how far away you sit.
            if thrown >= 10:
                body += f" {thrown} recordings were too far from the mic to use."
            subprocess.run(
                ["osascript", "-e",
                 f'display notification {json.dumps(body)} with title '
                 f'{json.dumps(f"Good morning, {name}")} sound name "Glass"'],
                capture_output=True,
            )
        result = remind.run()
    if path:
        print(f"  Good morning, {name}. Opened {path}")
    else:
        print("  no report to open yet")
    print(f"  reminders: {result}")
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    """Measure the false-alarm floor on human recordings of correct speech."""
    from . import accuracy

    print("  running the detector on human recordings of CORRECT speech.")
    print("  every finding below is a false alarm by construction.\n")
    result = accuracy.selftest(limit=args.limit, refresh=args.refresh)
    if not result["words"]:
        print("  no cached reference recordings yet. Run a day first, or `roy say version`.")
        return 1

    for word, contrast, expected, actual in result["examples"]:
        print(f"  FALSE ALARM  {word:<16}{contrast:<14}{expected} -> {actual}")
    if result["examples"]:
        print()
    print(f"  {result['words']} words, phoneme agreement {result['mean_agreement']:.2f}")
    print(f"  {result['false_alarms']} false alarms in {result['chances']} chances "
          f"({result['rate']:.1%}, at most {result['upper']:.1%})\n")
    print(f"  {'contrast':<16}{'false':>7}{'chances':>9}{'at most':>9}")
    for name, row in result["contrasts"].items():
        print(f"  {name:<16}{row['false']:>7}{row['chances']:>9}{row['upper']:>9.1%}")
    print()
    if result["rate"] > 0.05:
        print("  The detector flags correct speech. Fix that before tuning anything.")
    else:
        print("  A floor, not the real rate: single words, quiet room, a speaker")
        print("  without your habits. `roy check` is still the only test that")
        print("  measures findings from your own speech.")
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    from . import log

    print(f"  health: {log.health()}")
    thrown = log.too_far()
    if thrown:
        print(
            f"  {thrown} recordings thrown away today: the microphone was too "
            f"far to analyse. A hand-span from your mouth is worth about 12 dB, "
            f"which no amount of processing buys back."
        )
    print()
    print(log.tail(args.lines))
    return 0


def cmd_look(args: argparse.Namespace) -> int:
    for word in args.words:
        entry = dictionary.lookup(word, refresh=args.refresh)
        print(f"  {entry}")
        if entry.credit:
            print(f"    {entry.credit}")
        if entry.audio_path:
            print(f"    {entry.audio_path}")
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    from . import context

    decision = context.decide()
    print("SHOULD MR THAROOR BE LISTENING RIGHT NOW?")
    print(f"  answer    : {decision.mode.upper()}")
    print(f"  because   : {decision.reason}")
    print(f"  frontmost : {decision.frontmost}")
    print()
    health = micgate.gate_health()
    print(json.dumps(health, indent=2))
    users = micgate.mic_users()
    print(f"\nmic in use right now: {micgate.is_mic_in_use()}")
    for user in users:
        print(f"  {user}")
    if not health["process_api"]:
        print(
            "\nThis Mac is on the blunt fallback. The listener cannot tell its own "
            "stream from another app's, so it will over-record."
        )
    return 0


def cmd_cache(args: argparse.Namespace) -> int:
    words = dictionary.cached_words()
    size = sum(f.stat().st_size for f in config.AUDIO_DIR.glob("*") if f.is_file())
    print(f"{len(words)} words offline, {size / 1024:.0f} KB in {config.AUDIO_DIR}")
    for word in words:
        print(f"  {word}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tharoor", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    drill = sub.add_parser("drill", help="say it after him, three times each")
    drill.add_argument("words", nargs="*", help="defaults to tonight's worst")
    drill.add_argument("--times", type=int, default=3, help="repeats per word")
    drill.add_argument("--gap", type=float, default=2.0, help="seconds to say it back")
    drill.set_defaults(func=cmd_drill)

    check = sub.add_parser("check", help="judge his flags, so we learn if he is right")
    check.add_argument("--per-sound", type=int, default=2, help="words to judge per sound")
    check.set_defaults(func=cmd_check)

    score = sub.add_parser("score", help="how accurate Mr Tharoor has actually been")
    score.set_defaults(func=cmd_score)

    say = sub.add_parser("say", help="play the correct pronunciation out loud")
    say.add_argument("words", nargs="+")
    say.set_defaults(func=cmd_say)

    look = sub.add_parser("look", help="show IPA and audio source without playing")
    look.add_argument("words", nargs="+")
    look.add_argument("--refresh", action="store_true", help="ignore the cache")
    look.set_defaults(func=cmd_look)

    setup_cmd = sub.add_parser("setup", help="one command to get running")
    setup_cmd.add_argument("--skip-models", action="store_true",
                           help="do not pre-download the 3GB of models")
    setup_cmd.set_defaults(func=cmd_setup)

    listen_cmd = sub.add_parser("listen", help="start listening, context-aware")
    listen_cmd.add_argument("--seconds", type=float, default=None, help="stop after N seconds")
    listen_cmd.add_argument("--raw", action="store_true", help="skip Apple voice processing")
    listen_cmd.set_defaults(func=cmd_listen)

    day_cmd = sub.add_parser("analyse-day", help="the 23:30 job")
    day_cmd.add_argument("--day", help="YYYY-MM-DD, defaults to today")
    day_cmd.add_argument("--force", action="store_true", help="run even on battery")
    day_cmd.set_defaults(func=cmd_analyse_day)

    morning_cmd = sub.add_parser("morning", help="the 08:30 job")
    morning_cmd.set_defaults(func=cmd_morning)

    selftest_cmd = sub.add_parser(
        "selftest", help="false-alarm floor, measured on known-correct speech"
    )
    selftest_cmd.add_argument("--limit", type=int, default=None, help="only N words")
    selftest_cmd.add_argument("--refresh", action="store_true", help="re-convert audio")
    selftest_cmd.set_defaults(func=cmd_selftest)

    logs_cmd = sub.add_parser("logs", help="what the scheduled jobs did")
    logs_cmd.add_argument("--lines", type=int, default=30)
    logs_cmd.set_defaults(func=cmd_logs)

    probe_cmd = sub.add_parser("probe", help="record the 20 sentences that test if he works")
    probe_cmd.add_argument("--redo", action="store_true", help="re-record everything")
    probe_cmd.add_argument("--seconds", type=float, default=12.0, help="max per sentence")
    probe_cmd.add_argument("--device", type=int, default=None,
                           help="input device index (roy probe --list to see them)")
    probe_cmd.add_argument("--list", action="store_true", help="list input devices and exit")
    probe_cmd.set_defaults(func=cmd_probe)

    analyse = sub.add_parser("analyse", help="score the probe recordings")
    analyse.set_defaults(func=cmd_analyse)

    mictest = sub.add_parser("mictest", help="compare microphones, find your best setup")
    mictest.set_defaults(func=cmd_mictest)

    install = sub.add_parser("install", help="run every day by itself")
    install.add_argument("--remove", action="store_true")
    install.add_argument("--status", action="store_true")
    install.add_argument("--dry-run", action="store_true")
    install.set_defaults(func=cmd_install)

    remind_cmd = sub.add_parser("remind", help="what Mr Tharoor would nudge you about")
    remind_cmd.add_argument("--send", action="store_true", help="actually notify")
    remind_cmd.set_defaults(func=cmd_remind)

    gate = sub.add_parser("gate", help="report microphone gate health")
    gate.set_defaults(func=cmd_gate)

    cache = sub.add_parser("cache", help="list words already available offline")
    cache.set_defaults(func=cmd_cache)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
