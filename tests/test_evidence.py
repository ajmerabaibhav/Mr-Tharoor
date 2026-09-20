"""The statistics. If these are wrong, every number Mr Tharoor shows is a lie.

Run: python3 tests/test_evidence.py
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mr_tharoor import evidence as e
from mr_tharoor.evidence import Observation

TODAY = date(2026, 9, 15)


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol


def test_incomplete_beta_matches_known_values():
    """Beta(1,1) is the uniform distribution, so its CDF is the identity.
    If the continued fraction is wrong, everything downstream is decoration."""
    for x in (0.05, 0.25, 0.5, 0.9):
        assert close(e.beta_cdf(x, 1.0, 1.0), x), x
    assert close(e.beta_cdf(0.5, 2.0, 2.0), 0.5)        # symmetric
    assert close(e.beta_cdf(0.5, 0.5, 0.5), 0.5)        # Jeffreys, symmetric
    assert close(e.beta_cdf(0.5, 3.0, 1.0), 0.125)      # x^3
    assert close(e.beta_cdf(0.2, 2.0, 1.0), 0.04)       # x^2
    print("incomplete beta             ok")


def test_ppf_inverts_cdf():
    for a, b in ((1.0, 1.0), (2.0, 5.0), (0.5, 4.5), (3.8, 1.2)):
        for p in (0.05, 0.5, 0.95):
            x = e.beta_ppf(p, a, b)
            assert close(e.beta_cdf(x, a, b), p, 1e-6), (a, b, p, x)
    print("ppf inverts cdf             ok")


def test_a_word_said_once_is_reported_when_the_sound_is_chronic():
    """The whole point. You said 'vulnerable' once and got /v/ wrong. On its
    own that proves nothing. But you fail /v/ constantly everywhere else, so
    this one counts."""
    obs = [
        # forty other words carrying /v/, wrong most of the time
        Observation(TODAY, f"word{i}", "v->w", opportunities=5, error_weight=4.0)
        for i in range(40)
    ]
    obs.append(Observation(TODAY, "vulnerable", "v->w", opportunities=1, error_weight=1.0))

    rare = next(a for a in e.assess(obs, TODAY) if a.word == "vulnerable")
    assert rare.report, rare
    assert rare.borrowed, "should only clear the bar by borrowing from the contrast"
    assert rare.observations == 1.0
    assert "only said" in rare.explain()
    print(f"said once + chronic sound   ok  (lower bound {rare.lower_bound:.2f}, reported)")


def test_the_same_word_is_silent_when_the_sound_is_clean():
    """Same single observation, no history behind it. Must stay quiet, or the
    report fills with one-off slips and nobody opens it twice."""
    obs = [
        Observation(TODAY, f"word{i}", "v->w", opportunities=5, error_weight=0.0)
        for i in range(40)
    ]
    obs.append(Observation(TODAY, "vulnerable", "v->w", opportunities=1, error_weight=1.0))

    rare = next(a for a in e.assess(obs, TODAY) if a.word == "vulnerable")
    assert not rare.report, rare
    print(f"said once + clean sound     ok  (lower bound {rare.lower_bound:.2f}, silent)")


def test_a_word_cannot_justify_itself():
    """If the contrast rate included this word's own errors, a word seen only
    once would vote for its own conviction."""
    obs = [Observation(TODAY, "solo", "zz->q", opportunities=1, error_weight=1.0)]
    only = e.assess(obs, TODAY)[0]
    assert only.contrast_observations == 0.0
    assert not only.report, "one observation with no support must never report"
    print(f"no self-justification       ok  (lower bound {only.lower_bound:.2f})")


def test_low_confidence_counts_partially_not_zero():
    """The old hard cutoff deleted a 0.79 detection. Now it is 0.79 of an
    error, so twenty hesitant detections add up to real evidence."""
    strong = [Observation(TODAY, "w", "a->b", opportunities=20, error_weight=16.0)]
    weak = [Observation(TODAY, "w", "a->b", opportunities=20, error_weight=16 * 0.6)]
    none = [Observation(TODAY, "w", "a->b", opportunities=20, error_weight=0.0)]
    s, k, n = e.assess(strong, TODAY)[0], e.assess(weak, TODAY)[0], e.assess(none, TODAY)[0]
    assert s.posterior_mean > k.posterior_mean > n.posterior_mean
    assert k.posterior_mean > 0.3, "hesitant detections must still accumulate"
    print(f"soft confidence             ok  (strong {s.posterior_mean:.2f} > "
          f"weak {k.posterior_mean:.2f} > clean {n.posterior_mean:.2f})")


def test_evidence_decays_but_does_not_vanish():
    """Counts are free, so we look back a month. But last month must not
    outweigh this week, or a habit you fixed keeps being reported."""
    fresh = [Observation(TODAY, "w", "a->b", 10, 8.0)]
    old = [Observation(TODAY - timedelta(days=21), "w", "a->b", 10, 8.0)]
    ancient = [Observation(TODAY - timedelta(days=60), "w", "a->b", 10, 8.0)]
    f, o = e.assess(fresh, TODAY)[0], e.assess(old, TODAY)[0]
    assert f.observations > o.observations > 0
    assert e.assess(ancient, TODAY) == [], "beyond the lookback it should be gone"
    print(f"decay                       ok  (today {f.observations:.1f} vs "
          f"3 weeks ago {o.observations:.1f} effective observations)")


def test_more_evidence_tightens_the_bound():
    """Ten wrong out of ten should be reported harder than one out of one,
    even though both are 100%."""
    one = e.assess([Observation(TODAY, "w", "a->b", 1, 1.0)], TODAY)[0]
    many = e.assess([Observation(TODAY, "w", "a->b", 30, 30.0)], TODAY)[0]
    assert many.lower_bound > one.lower_bound
    assert many.report and not one.report
    print(f"sample size                 ok  (1/1 -> {one.lower_bound:.2f}, "
          f"30/30 -> {many.lower_bound:.2f})")


def test_contrast_summary_ranks_sounds():
    obs = [
        Observation(TODAY, "version", "v->w", 20, 15.0),
        Observation(TODAY, "three", "th->t", 20, 4.0),
    ]
    summary = e.contrast_summary(obs, TODAY)
    assert list(summary)[0] == "v->w"
    assert summary["v->w"]["rate"] > summary["th->t"]["rate"]
    print("contrast summary            ok")


def test_quality_has_two_axes():
    """Signal-to-noise and agreement answer different questions.

    MEASURED on 14 dictations: recordings where the phoneme model matched
    under half the expected sequence produced findings at 15.5% per chance,
    against 2.4% above it -- and SNR did not predict which was which. The
    worst of them had the second-best signal in the set, 32.9 dB. Without
    the second axis those findings enter the tally at full weight.
    """
    from mr_tharoor import listen

    assert listen.agreement_weight(0.16) == 0.0, "untracked speech must not count"
    assert listen.agreement_weight(0.33) == 0.0
    assert listen.agreement_weight(0.87) == 1.0, "clean reference speech is full weight"
    assert 0 < listen.agreement_weight(0.51) < 1, "the middle is a ramp, not a cliff"
    ramp = [listen.agreement_weight(a / 100) for a in range(30, 70)]
    assert ramp == sorted(ramp), "weight must never fall as agreement rises"
    print(f"agreement is a second axis  ok  (0.43 -> {listen.agreement_weight(0.43)})")


def test_snr_of_a_buffer():
    """The listener judges a chunk before writing it, and must agree with the
    analyser that judges it afterwards. Two definitions would mean recordings
    kept at capture and thrown away at 23:30, every night, invisibly."""
    import numpy as np

    from mr_tharoor import listen

    rate = 16000
    rng = np.random.default_rng(0)
    hiss = rng.normal(0, 0.01, rate).astype("float32")
    speech = hiss.copy()
    speech[rate // 4 : 3 * rate // 4] += (
        0.3 * np.sin(2 * np.pi * 180 * np.arange(rate // 2) / rate)
    ).astype("float32")

    quiet, loud = listen.snr_of(hiss, rate), listen.snr_of(speech, rate)
    assert quiet < listen.MIN_SNR_DB, f"steady hiss scored {quiet:.0f} dB as usable"
    assert loud > quiet + 10, f"a burst in the same hiss only gained {loud - quiet:.0f} dB"
    assert listen.snr_of(np.zeros(rate, dtype="float32"), rate) == -99.0
    print(f"snr of a buffer             ok  ({quiet:.0f} dB hiss, {loud:.0f} dB speech)")


def main() -> int:
    test_incomplete_beta_matches_known_values()
    test_ppf_inverts_cdf()
    test_a_word_said_once_is_reported_when_the_sound_is_chronic()
    test_the_same_word_is_silent_when_the_sound_is_clean()
    test_a_word_cannot_justify_itself()
    test_low_confidence_counts_partially_not_zero()
    test_evidence_decays_but_does_not_vanish()
    test_more_evidence_tightens_the_bound()
    test_contrast_summary_ranks_sounds()
    test_quality_has_two_axes()
    test_snr_of_a_buffer()
    print("\nPASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
