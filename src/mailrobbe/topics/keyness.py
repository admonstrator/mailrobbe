"""Whether a term stands out in a scope (D142), and its figures; pure.

A scope is a period or the mails of a selection: n of the archive's N mails, a of them holding a
term that df archive mails hold. The rest of the archive is the other N - n mails, df - a of them
holding the term. The term stands out when a >= MIN_SCOPE_MAILS, its share in the scope is at
least MIN_RATIO times its share in the rest (or the rest has none) and Dunning's log-likelihood
G2 of the two shares is at least MIN_SCORE (p < 0.01 with one degree of freedom). In a scope of
at least COMMON_MIN_SCOPE mails a term that stands out in more than COMMON_SHARE of them is
common (a signature, a greeting, a list's footer) and listed apart.

G2 is the two-cell form of the corpus comparison (Rayson and Garside 2000): with the term's
expected mails E1 = n * df / N in the scope and E2 = (N - n) * df / N in the rest,
G2 = 2 * (a * ln(a / E1) + (df - a) * ln((df - a) / E2)), a zero count adding nothing.
"""

import math
from dataclasses import dataclass

MIN_SCOPE_MAILS = 3
MIN_RATIO = 2.0
MIN_SCORE = 6.63
COMMON_SHARE = 0.5
COMMON_MIN_SCOPE = 20


@dataclass(frozen=True, slots=True)
class Keyness:
    mails: int  # a, rounded when it was estimated from a sample
    share: float  # a / n
    rest_share: float  # (df - a) / (N - n)
    ratio: float | None  # share / rest_share; None when the rest has none
    score: float  # G2
    common: bool  # in more than COMMON_SHARE of a scope of at least COMMON_MIN_SCOPE mails


def keyness(a: float, n: float, df: float, total: float) -> Keyness | None:
    """The term's figures when it stands out in the scope, else None.

    a and n may be estimates for a whole selection from a sample (D144). df is raised to a when
    it is smaller (mails imported after the vocabulary was counted), and a scope that is the
    whole archive (n >= total) has no rest to stand out from.
    """
    if a < MIN_SCOPE_MAILS or n <= 0 or n >= total:
        return None
    df = max(df, a)
    rest = df - a
    share = a / n
    rest_share = rest / (total - n)
    if rest_share and share < MIN_RATIO * rest_share:
        return None
    expected_here = n * df / total
    expected_rest = (total - n) * df / total
    score = 2 * a * math.log(a / expected_here)
    if rest:
        score += 2 * rest * math.log(rest / expected_rest)
    if score < MIN_SCORE:
        return None
    return Keyness(
        mails=round(a),
        share=share,
        rest_share=rest_share,
        ratio=share / rest_share if rest_share else None,
        score=score,
        common=n >= COMMON_MIN_SCOPE and share > COMMON_SHARE,
    )
