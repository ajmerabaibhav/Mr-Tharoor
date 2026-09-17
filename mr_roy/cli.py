"""Mr Roy, your pronunciation teacher.

    roy drill version three       say it after him, three times each
    roy say version               hear it once
    roy look comfortable          IPA and source, no sound
    roy check                     judge his flags, so we learn if he is right
    roy score                     how accurate he has actually been
    roy probe                     record the 20 sentences that test if he works
    roy analyse                   score those recordings, see if he can hear you
    roy mictest                   compare microphones, find your best setup
    roy install                   run every day by itself (launchd)
    roy remind                    what Mr Roy would nudge you about
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
            print("Nothing to drill yet. Mr Roy has not heard you speak.")
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
        print("Mr Roy needs to have heard you speak first.")
        return 0

    pending = [(row, word) for row in rows for word in row.words[: args.per_sound]]
    print(f"{len(pending)} flags to judge. y = I did say it wrong, n = I said it fine,")
    print("s = skip, u = cannot tell. Ctrl-C to stop; answers are saved as you go.\n")

    saved = 0
    for row, word in pending:
        entry = dictionary.lookup(word)
        print(f"  {word}  ({row.contrast})   Mr Roy is {row.lower_bound:.0%} sure")
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
    """How right has Mr Roy actually been?"""
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
    print("Next: the phoneme model scores these and we find out if Mr Roy works.")
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
    print("SHOULD MR ROY BE LISTENING RIGHT NOW?")
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
    parser = argparse.ArgumentParser(prog="roy", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    drill = sub.add_parser("drill", help="say it after him, three times each")
    drill.add_argument("words", nargs="*", help="defaults to tonight's worst")
    drill.add_argument("--times", type=int, default=3, help="repeats per word")
    drill.add_argument("--gap", type=float, default=2.0, help="seconds to say it back")
    drill.set_defaults(func=cmd_drill)

    check = sub.add_parser("check", help="judge his flags, so we learn if he is right")
    check.add_argument("--per-sound", type=int, default=2, help="words to judge per sound")
    check.set_defaults(func=cmd_check)

    score = sub.add_parser("score", help="how accurate Mr Roy has actually been")
    score.set_defaults(func=cmd_score)

    say = sub.add_parser("say", help="play the correct pronunciation out loud")
    say.add_argument("words", nargs="+")
    say.set_defaults(func=cmd_say)

    look = sub.add_parser("look", help="show IPA and audio source without playing")
    look.add_argument("words", nargs="+")
    look.add_argument("--refresh", action="store_true", help="ignore the cache")
    look.set_defaults(func=cmd_look)

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

    remind_cmd = sub.add_parser("remind", help="what Mr Roy would nudge you about")
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
