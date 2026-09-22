"""Mr Tharoor, your pronunciation teacher.

    tharoor drill version three       say it after him, three times each
    tharoor say version               hear it once
    tharoor look comfortable          IPA and source, no sound
    tharoor check                     judge his flags, so we learn if he is right
    tharoor score                     how accurate he has actually been
    tharoor setup                     one command: check, permit, download, schedule
    tharoor listen                    start listening (context-aware, all day)
    tharoor analyse-day               the 23:30 job: score today, build the report
    tharoor morning                   the 08:30 job: open it, send reminders
    tharoor probe                     record the 20 sentences that test if he works
    tharoor analyse                   score those recordings, see if he can hear you
    tharoor mictest                   compare microphones, find your best setup
    tharoor install                   run every day by itself (launchd)
    tharoor remind                    what Mr Tharoor would nudge you about
    tharoor gate                      is the mic gate working on this Mac
    tharoor cache                     what is already offline
"""

from __future__ import annotations

import argparse
import json
import sys

import time
from datetime import date, timedelta

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
            print("Give him words directly:  tharoor drill version three")
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
    import subprocess
    from pathlib import Path

    from . import daily, report

    day = (date.fromisoformat(args.day) if getattr(args, "day", None)
           else report.latest_day(before=date.today() + timedelta(days=1)))
    findings = daily.load(day) if day else []
    grouped = daily.group(findings, day) if day else {}
    if not grouped:
        print("Nothing flagged to check yet.")
        print("Mr Tharoor needs to have heard you speak first.")
        return 0

    pending = []
    for items in grouped.values():
        seen = set()
        for item in items:
            if item.word in seen:
                continue
            pending.append(item)
            seen.add(item.word)
            if len(seen) >= args.per_sound:
                break
    print(f"{len(pending)} flags to judge. y = I did say it wrong, n = I said it fine,")
    print("s = skip, u = cannot tell. Ctrl-C to stop; answers are saved as you go.\n")

    saved = 0
    bounds = daily.trustworthy_contrasts(findings, day)
    for item in pending:
        word = item.word
        print(f"  {word} ({item.contrast}) from {day}; model score {item.confidence:.0%}")
        print(f"     transcript: {item.sentence[:160]}")
        if not item.clip_path or not Path(item.clip_path).exists():
            print("     Your clip is unavailable; skipping so you do not have to guess.")
            continue
        print("     playing your recording...")
        subprocess.run(["afplay", item.clip_path], check=False)
        entry = dictionary.lookup(word)
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
                day=day.isoformat(),
                word=word,
                contrast=item.contrast,
                verdict=verdict,
                clip=item.clip_path,
                lower_bound=bounds.get(item.contrast),
            )
        )
        saved += 1

    if saved:
        grammar_path = config.REPORTS_DIR / f"{day}-grammar.json"
        habits = json.loads(grammar_path.read_text()) if grammar_path.exists() else []
        report.write(findings, day, grammar=habits)

    print(f"\n  {saved} judgements saved. Run `tharoor score` to see what they say.")
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
        print(f"\n  Judge {20 - card.flagged} more with `tharoor check` for a threshold suggestion.")
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
            print("\n  stopped. Progress is saved; run `tharoor probe` again to continue.")
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
        print("No recordings yet. Run `tharoor probe` first.")
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
    print("  cannot hear you, or you genuinely say it differently. Only `tharoor check`")
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
    try:
        for line in schedule.install(dry_run=args.dry_run):
            print(f"  {line}")
    except schedule.InstallationError as exc:
        print(f"  Installation incomplete: {exc}")
        return 1
    print("\n  A missed run is not skipped: launchd fires it when you next open the lid.")
    print("  Remove anytime with `tharoor install --remove`. Nothing needs sudo.")
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
        print("\n  Stopping here. Install the libraries above and run `tharoor setup` again.")
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
    try:
        for line in schedule.install():
            print(f"     {line}")
    except schedule.InstallationError as exc:
        print(f"     {exc}")
        problems.append("schedule")

    print("\n" + ("-" * 58))
    if problems:
        print(f"  Set up with problems: {', '.join(problems)}")
        print("  Fix those and run `tharoor setup` again.")
        return 1
    print("  Ready. Mr Tharoor is listening now and starts on every login.")
    print()
    print("  Talk normally. At 23:30 he analyses the day, at 08:30 the report")
    print("  opens by itself. Nothing leaves this machine.")
    print()
    print("  tharoor gate     is he listening right now, and why")
    print("  tharoor mictest  find your best microphone setup")
    print("  tharoor logs     what the scheduled jobs did")
    return 0


def cmd_listen(args: argparse.Namespace) -> int:
    from . import listener

    worker = listener.Listener(use_voice_processing=not args.raw)
    stats = worker.run(max_seconds=args.seconds)
    print(f"  {stats.as_dict()}")
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

    from . import daily, grammar, listener, listen, log, remind, report, schedule, streaks, typed, wispr

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
    tallies = []
    grammar_findings = []
    spoken_texts: list[tuple[str, str]] = []  # everything said today, for one grammar pass
    sources = {"wispr": 0, "own": 0, "typed": 0}
    failures = 0

    with log.step("nightly", day=str(when)):
        # ---- source 1: Wispr Flow ----
        dictations: list = []
        if wispr.available():
            try:
                dictations = wispr.for_day(when)
            except wispr.SchemaChanged as exc:
                logger.error(f"Wispr reader disabled: {exc}")
                print(f"  Wispr Flow database changed shape: {exc}")
                dictations = []
                failures += 1
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Wispr read failed: {type(exc).__name__}: {exc}")
                dictations = []
                failures += 1
            print(f"  {len(dictations)} dictations in Wispr Flow for {when}")
            folder = listener.sessions_dir(when)
            for index, d in enumerate(dictations, 1):
                label = f"{when}-wispr-{dictionary.cache_key(d.id)}"
                # Raw ASR, not the cleaned text: Wispr's model has already
                # fixed the grammar in `meant`, so marking that finds nothing.
                if d.heard:
                    spoken_texts.append((label, d.heard))
                if d.edited:  # your own hand corrections are the best evidence there is
                    grammar_findings += grammar.compare(d.heard, d.meant, label, edited=True)
                path = wispr.write_wav(d, folder)
                if not path:
                    continue
                if not d.heard:
                    continue
                try:
                    findings += daily.findings_for(
                        str(path), d.heard, label, tallies=tallies,
                        excluded_words=daily.uncertain_words(d.heard, d.meant),
                    )
                except Exception as exc:
                    failures += 1
                    logger.error(f"could not analyse {label}: {type(exc).__name__}: {exc}")
                    continue
                sources["wispr"] += 1
                if index % 10 == 0:
                    print(f"    {index}/{len(dictations)} dictations, {len(findings)} sound findings so far")
        else:
            print("  Wispr Flow not found; using our own recordings only")

        # ---- source 2: our own recordings (meetings, calls, reading aloud) ----
        chunks = listener.todays_audio(when)
        print(f"  {len(chunks)} recordings of our own for {when}")
        for index, chunk in enumerate(chunks, 1):
            try:
                quality = listen.audio_quality(str(chunk))
                if not quality["usable"]:
                    logger.info(f"skip {chunk.name}: SNR {quality['snr_db']}dB is room tone")
                    continue
                segments = listen.transcribe(str(chunk))
                label = f"{when}-{chunk.stem}"
                findings += daily.findings_for_segments(str(chunk), segments, label, tallies=tallies)
                for n, segment in enumerate(segments):
                    if segment.get("words") and all(w.get("probability", 0) >= 0.80 for w in segment["words"]):
                        spoken_texts.append((f"{label}-{n}", segment["text"]))
            except Exception as exc:
                failures += 1
                logger.error(f"could not analyse {chunk.name}: {type(exc).__name__}: {exc}")
                continue
            sources["own"] += 1
            if index % 10 == 0:
                print(f"    {index}/{len(chunks)} recordings, {len(findings)} sound findings so far")

        if failures:
            logger.error(f"{failures} sources failed; keeping the previous report and retrying later")
            print(f"  {failures} sources failed. Previous report kept; see `tharoor logs`.")
            return 1

        # ---- source 3: what you typed (Claude Code's own transcripts) ----
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
        if grammar.llm_available():
            print(f"  checking grammar on {len(spoken_texts)} utterances and {len(typed_texts)} messages")
            found = grammar.llm_check(spoken_texts, "spoken", logger=logger)
            found += grammar.llm_check(typed_texts, "typed", logger=logger)
            grammar_findings += grammar.merge(found, rules)
        else:
            logger.warning("Claude Code CLI not found; grammar falls back to local rules")
            grammar_findings += rules

        streaks.record_day(when, tallies)
        selected = [f for items in daily.group(findings, when).values() for f in items]
        daily.attach_pronunciations(selected)
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
                        week += grammar.compare(d.heard, d.meant, f"{d.when.date()}-wispr-{d.id}", edited=d.edited)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"weekly grammar pass failed: {type(exc).__name__}: {exc}")
                week = list(grammar_findings)
        for back in range(grammar.HABIT_WINDOW_DAYS):
            raw = config.REPORTS_DIR / f"{(when - _td(days=back)).isoformat()}-grammar-raw.json"
            if raw.exists():
                try:
                    week += [grammar.GrammarFinding(**row) for row in _json.loads(raw.read_text())]
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
                        + [r for r in rows if r.get("mode") == "typed"][:6])
        config.write_json_atomically(config.REPORTS_DIR / f"{when}-grammar.json", grammar_rows)
        added = remind.enqueue(selected, day=when)
        analysis = {
            "version": daily.ANALYSIS_VERSION, "completed_at": datetime.now().isoformat(),
            "sources": sources, "opportunities": sum(t.said for t in tallies),
            "candidates": len(findings), "shown": len(selected),
            "grammar_engine": "claude-cli" if grammar.llm_available() else "local-rules",
            "grammar_found": len(grammar_findings),
        }
        written = report.write(findings, when, grammar=grammar_rows, analysis=analysis)
        analysis["outputs"] = sorted(written)
        config.write_json_atomically(config.REPORTS_DIR / f"{when}-analysis.json", analysis)

    log.event("nightly_done", day=str(when), findings=len(findings),
              grammar=len(grammar_findings), cards=added, **sources)
    print(f"\n  {len(findings)} sound findings, {len(grammar_findings)} grammar corrections "
          f"({len(grammar_rows)} habits), {added} new reminder cards")
    for kind, path in written.items():
        print(f"  {kind}: {path}")
    if "pdf" not in written:
        print("  PDF export is incomplete. The next scheduled check will retry from saved results.")
    return 0


def cmd_analyse_pending(args: argparse.Namespace) -> int:
    """Catch up retained days after sleep/login; completed days are not decoded again."""
    from datetime import datetime, timedelta

    from . import daily, report

    now = datetime.now()
    # Yesterday's review should not wait behind several days of old audio.
    days = [now.date() - timedelta(days=n) for n in range(1, 4)]
    if (now.hour, now.minute) >= (23, 30):
        days.append(now.date())
    failed = False
    for day in days:
        marker = config.REPORTS_DIR / f"{day}-analysis.json"
        if marker.exists():
            try:
                completed = json.loads(marker.read_text())
                completed_at = datetime.fromisoformat(completed["completed_at"])
                if (completed.get("version") == daily.ANALYSIS_VERSION
                        and (completed_at.date() > day or (day == now.date()
                             and (completed_at.hour, completed_at.minute) >= (23, 30)))):
                    from . import schedule

                    with schedule.job_lock("analysis") as acquired:
                        if not acquired:
                            print("  Analysis is already running; export recovery will retry later.")
                            return 1
                        if not report.repair_exports(day, completed):
                            failed = True
                            print(f"  {day}: PDF still unavailable; will retry at the next check.")
                    continue
            except (ValueError, TypeError, KeyError):
                pass
        result = cmd_analyse_day(argparse.Namespace(day=str(day), force=args.force))
        failed = failed or bool(result)
    return int(failed)


def cmd_morning(args: argparse.Namespace) -> int:
    from . import schedule

    with schedule.job_lock("morning") as acquired:
        if not acquired:
            return 0
        return _morning(args)


def _morning(args: argparse.Namespace) -> int:
    """08:30. Open yesterday's report and say good morning."""
    import json
    import subprocess
    from datetime import date as _date, timedelta

    from . import daily, log, remind, report

    automatic = getattr(args, "automatic", False)
    state_path = config.DATA_DIR / "morning.json"
    if automatic:
        from datetime import datetime
        from . import micgate

        if not 8 <= datetime.now().hour < 21 or micgate.is_mic_in_use():
            return 0
    day = report.latest_day(before=_date.today())
    if day is None:
        print("  No completed report yet. Analysis will catch up at the next scheduled check.")
        return 0
    if automatic and state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            if state.get("opened_on") == str(_date.today()) and state.get("report_day") == str(day):
                return 0
        except (ValueError, TypeError):
            pass
    with log.step("morning"):
        path = report.open_report(day)
        findings = daily.load(day)
        grammar_file = config.REPORTS_DIR / f"{day.isoformat()}-grammar.json"
        habits = json.loads(grammar_file.read_text()) if grammar_file.exists() else []
        sounds = len(daily.group(findings, day))
        name = config.user_name()
        thrown = log.too_far(day)
        if path:
            delivered = "The PDF report is open in Preview."
            if not path.endswith(".pdf"):
                delivered = "The interactive report is open in your browser."
            body = (
                f"{sounds} sound{'s' if sounds != 1 else ''} and "
                f"{len(habits)} phrase{'s' if len(habits) != 1 else ''} from {day:%A}. "
                f"{delivered}"
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
            config.write_json_atomically(state_path, {"opened_on": str(_date.today()), "report_day": str(day)})
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
        print("  no cached reference recordings yet. Run a day first, or `tharoor say version`.")
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
        print("  without your habits. `tharoor check` is still the only test that")
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
    check.add_argument("--day", help="review a specific YYYY-MM-DD report")
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

    pending = sub.add_parser("analyse-pending", help="catch up unprocessed days after sleep or login")
    pending.add_argument("--force", action="store_true", help="also analyse while on battery")
    pending.set_defaults(func=cmd_analyse_pending)

    morning_cmd = sub.add_parser("morning", help="the 08:30 job")
    morning_cmd.add_argument("--automatic", action="store_true", help="open once per day, outside calls and quiet hours")
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
                           help="input device index (tharoor probe --list to see them)")
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
