"""How sure are we, really?

The old rule threw away almost everything. A hard confidence cutoff at 0.80
discarded a 0.79 detection completely, as though it carried no information.
A "said 3+ times" rule discarded every rare word. And each word was scored as
if it were an isolated experiment, which is the deepest mistake of the three.

It is not isolated. If you produce /w/ where /v/ belongs 140 times out of 200
opportunities, across forty different words, then you saying "vulnerable" once
and producing /w/ is not one weak data point. Conditioned on everything else
we know about your /v/, it is close to a certainty. Evidence about a SOUND
compounds across every word that contains it.

That is a hierarchical model, so this module implements one.

    global prior            most sounds are said correctly
        |                   Beta(0.5, 4.5)
        v
    contrast rate  θ_c      your /v/ -> /w/ rate, pooled over every word
        |                   containing /v/, over weeks, decayed
        v
    word posterior          "vulnerable" starts at θ_c and moves from there
                            Beta(κθ_c + k, κ(1-θ_c) + n - k)

Three consequences, all of which are the behaviour we actually want:

  * A word said ONCE, wrong once, on a contrast you fail constantly, gets
    reported. Its posterior inherits the strength of the contrast.
  * The same word, wrong once, on a contrast you have never failed, does not.
    Its posterior shrinks back toward "you probably said it fine".
  * A low-confidence detection is no longer deleted. It is counted as a
    fraction of an observation. 0.6 confidence is 0.6 of an error, not zero.
    Nothing is thrown away, so nothing has to be guessed back.

We report on the LOWER bound of the posterior, not the mean. With a lot of
data the interval is tight and the bound sits near the true rate. With one
observation the interval is wide and the bound stays low unless the prior is
genuinely strong. Small samples disqualify themselves, without a rule.

No scipy. The incomplete beta function is forty lines of continued fraction
and it has been the same forty lines since Numerical Recipes.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from math import exp, lgamma, log, log1p

# --- the global prior -------------------------------------------------------
# Beta(0.5, 4.5): before seeing anything, assume a sound is about 10% likely
# to be wrong. Starting at 50/50 would treat every first mistake as damning.
GLOBAL_ALPHA = 0.5
GLOBAL_BETA = 4.5

# How strongly a word is pulled toward its contrast's rate, in pseudo-counts.
# 4.0 means "the contrast is worth about four observations of this word", so
# a single real observation moves the estimate but does not dominate it.
POOLING_STRENGTH = 4.0

# Report when we are 95% sure the true error rate is at least this high.
REPORT_THRESHOLD = 0.35
CREDIBLE_LEVEL = 0.05

# Smallest shape parameter we will hand to the beta distribution. Below this
# the distribution is degenerate and the credible bound stops meaning anything.
SHAPE_FLOOR = 0.05

# Evidence compounds but must stay current: a day's weight halves every week.
HALF_LIFE_DAYS = 7.0
LOOKBACK_DAYS = 30


# --- regularised incomplete beta, and its inverse ---------------------------


def _betacf(a: float, b: float, x: float, itmax: int = 300) -> float:
    """Continued fraction for the incomplete beta. Lentz's algorithm."""
    eps, fpmin = 3e-16, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def beta_cdf(x: float, a: float, b: float) -> float:
    """P(X <= x) for X ~ Beta(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = lgamma(a + b) - lgamma(a) - lgamma(b) + a * log(x) + b * log1p(-x)
    if x < (a + 1.0) / (a + b + 2.0):
        return exp(front) * _betacf(a, b, x) / a
    return 1.0 - exp(front) * _betacf(b, a, 1.0 - x) / b


def beta_ppf(p: float, a: float, b: float) -> float:
    """Inverse CDF by bisection. The CDF is monotone, so this always converges."""
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if beta_cdf(mid, a, b) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# --- evidence ---------------------------------------------------------------


@dataclass(frozen=True)
class Observation:
    """One word, one contrast, one day.

    `opportunities` counts how many times the sound could have occurred --
    that comes from the transcript and is close to exact. `error_weight` is
    the SUM of the detector's confidence over the times it thought you got it
    wrong, so a hesitant 0.6 detection contributes 0.6 of an error rather
    than being deleted by a threshold.
    """

    day: date
    word: str
    contrast: str
    opportunities: int
    error_weight: float


@dataclass
class Assessment:
    """What we believe about one word-and-sound, after pooling everything."""

    word: str
    contrast: str
    observations: float  # decayed opportunities for THIS word
    errors: float  # decayed weighted errors for this word
    contrast_rate: float  # your rate on this sound, pooled across all words
    contrast_observations: float
    posterior_mean: float
    lower_bound: float  # 95% sure the true rate is at least this
    borrowed: bool  # would this have been invisible without pooling?

    @property
    def report(self) -> bool:
        return self.lower_bound >= REPORT_THRESHOLD

    @property
    def certainty(self) -> str:
        if self.lower_bound >= 0.60:
            return "certain"
        if self.lower_bound >= REPORT_THRESHOLD:
            return "confident"
        if self.posterior_mean >= REPORT_THRESHOLD:
            return "suspected"
        return "unproven"

    def explain(self) -> str:
        """Plain English, because a number nobody trusts changes no behaviour."""
        rate = round(self.posterior_mean * 100)
        if self.borrowed:
            said = "once" if self.observations < 1.5 else f"{self.observations:.0f} times"
            return (
                f"You only said {self.word} {said}, but you get this sound wrong "
                f"{round(self.contrast_rate * 100)}% of the time across "
                f"{self.contrast_observations:.0f} other chances. So this one counts."
            )
        return (
            f"{self.errors:.0f} wrong out of {self.observations:.0f}. "
            f"Best estimate {rate}%, and at least "
            f"{round(self.lower_bound * 100)}% even being pessimistic."
        )


def _decay(day: date, today: date) -> float:
    """A day's evidence halves every HALF_LIFE_DAYS. Old habits fade, not vanish."""
    age = (today - day).days
    if age < 0 or age > LOOKBACK_DAYS:
        return 0.0
    return 0.5 ** (age / HALF_LIFE_DAYS)


def assess(observations: list[Observation], today: date | None = None) -> list[Assessment]:
    """Pool everything, then judge each word. Worst first."""
    today = today or date.today()

    by_word: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
    by_contrast: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])

    for obs in observations:
        weight = _decay(obs.day, today)
        if weight == 0.0:
            continue
        n = obs.opportunities * weight
        k = min(obs.error_weight, obs.opportunities) * weight
        by_word[(obs.word, obs.contrast)][0] += n
        by_word[(obs.word, obs.contrast)][1] += k
        by_contrast[obs.contrast][0] += n
        by_contrast[obs.contrast][1] += k

    out: list[Assessment] = []
    for (word, contrast), (n_word, k_word) in by_word.items():
        n_con, k_con = by_contrast[contrast]

        # The contrast rate must not include this word, or a word that only
        # ever appears once would be justifying itself with its own evidence.
        n_other = max(n_con - n_word, 0.0)
        k_other = max(k_con - k_word, 0.0)
        contrast_rate = (k_other + GLOBAL_ALPHA) / (n_other + GLOBAL_ALPHA + GLOBAL_BETA)

        # Floor both shapes well above zero. At 1e-9 the distribution
        # degenerates and beta_ppf(0.05) returns 1.0 -- "95% certain the
        # error rate is exactly 100%" -- which is an artefact of the clamp,
        # not something the data ever said.
        alpha = max(POOLING_STRENGTH * contrast_rate + k_word, SHAPE_FLOOR)
        beta = max(POOLING_STRENGTH * (1.0 - contrast_rate) + (n_word - k_word), SHAPE_FLOOR)

        mean = alpha / (alpha + beta)
        lower = beta_ppf(CREDIBLE_LEVEL, alpha, beta)

        # Would this word have cleared the bar on its own evidence alone?
        solo_alpha = GLOBAL_ALPHA + k_word
        solo_beta = GLOBAL_BETA + (n_word - k_word)
        solo_lower = beta_ppf(CREDIBLE_LEVEL, solo_alpha, max(solo_beta, SHAPE_FLOOR))

        out.append(
            Assessment(
                word=word,
                contrast=contrast,
                observations=n_word,
                errors=k_word,
                contrast_rate=contrast_rate,
                contrast_observations=n_other,
                posterior_mean=mean,
                lower_bound=lower,
                borrowed=lower >= REPORT_THRESHOLD > solo_lower,
            )
        )

    out.sort(key=lambda a: (-a.lower_bound, -a.errors, a.word))
    return out


def contrast_summary(observations: list[Observation], today: date | None = None) -> dict:
    """Per-sound totals. This is where a rare word's evidence comes from."""
    today = today or date.today()
    totals: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for obs in observations:
        weight = _decay(obs.day, today)
        if weight == 0.0:
            continue
        totals[obs.contrast][0] += obs.opportunities * weight
        totals[obs.contrast][1] += min(obs.error_weight, obs.opportunities) * weight
    return {
        contrast: {
            "opportunities": n,
            "errors": k,
            "rate": (k + GLOBAL_ALPHA) / (n + GLOBAL_ALPHA + GLOBAL_BETA),
        }
        for contrast, (n, k) in sorted(totals.items(), key=lambda kv: -kv[1][1])
    }
