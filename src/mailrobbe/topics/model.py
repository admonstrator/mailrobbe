"""What the topics phase, the clusters and the API share (D140 to D146): the rules as constants,
the periods, and the vocabulary and clusters handed from one module to the next."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

# Raise when the computation changes, so that the next import computes the topics again (D146).
TOPICS_VERSION = 1

# Vocabulary (D141).
MIN_LENGTH = 3  # characters of a lexeme
MAX_LENGTH = 40
MIN_MAILS = 3  # archive mails a term must be in
# The weights of mail.tsv terms come from, as SQL for ts_filter: the subject, the own and the
# quoted text, never the standard blocks (weight D, D205, D226).
TOPIC_WEIGHTS = "'{a,b,c}'"

# Periods (D143).
Unit = Literal["month", "quarter", "year"]  # api/schemas.py TopicUnit
UNITS: tuple[Unit, ...] = ("month", "quarter", "year")
PERIOD_TERMS = 30  # terms kept per period

# Clusters (D145).
CLUSTER_CANDIDATES = 3_000  # terms with most mails taken into account at most
CLUSTER_MIN_MAILS = 10  # a candidate is in at least this many mails
CLUSTER_MAX_SHARE = 0.05  # and in at most this share of the archive's mails
LINK_MIN_MAILS = 3  # mails holding both terms of a link
LINK_MIN_NPMI = 0.3  # normalised pointwise mutual information of a link
MAIL_MAX_TERMS = 100  # a mail with more candidates does not count for links
CLUSTER_MIN_TERMS = 4
CLUSTER_TERMS = 15  # strongest terms kept per cluster
CLUSTER_LABEL_TERMS = 3  # in its label
CLUSTER_QUERY_TERMS = 5  # in its search
CLUSTER_LIMIT = 100  # clusters kept, most mails first


def usable_lexeme(lexeme: str) -> bool:
    """Whether a lexeme of mail.tsv can be a term (D141): letters only (no numbers, addresses,
    links, hosts or hyphenated compounds, whose parts are lexemes of their own) and 3 to 40 of
    them. Stop words, ignored words and names are left out by the phase."""
    return MIN_LENGTH <= len(lexeme) <= MAX_LENGTH and lexeme.isalpha()


def period_start(day: date, unit: Unit) -> date:
    """The first day of the month, quarter or year (UTC) holding day."""
    match unit:
        case "month":
            return day.replace(day=1)
        case "quarter":
            return date(day.year, (day.month - 1) // 3 * 3 + 1, 1)
        case "year":
            return date(day.year, 1, 1)


def period_end(start: date, unit: Unit) -> date:
    """The last day of the period beginning on start, inclusive, as the mail list's date_to."""
    months = {"month": 1, "quarter": 3, "year": 12}[unit]
    month = start.month - 1 + months
    following = date(start.year + month // 12, month % 12 + 1, 1)
    return date.fromordinal(following.toordinal() - 1)


def cluster_label(labels: list[str]) -> str:
    """A cluster's label: its first CLUSTER_LABEL_TERMS term labels (D145)."""
    return ", ".join(labels[:CLUSTER_LABEL_TERMS])


def cluster_query(labels: list[str]) -> str:
    """A cluster's search in the syntax of q (D20): its first CLUSTER_QUERY_TERMS term labels,
    any of them."""
    return " or ".join(labels[:CLUSTER_QUERY_TERMS])


@dataclass(frozen=True, slots=True)
class Term:
    """A term of the vocabulary (D141), as the phase hands it on."""

    lexeme: str  # as in mail.tsv
    label: str  # the spelling used most; the word the mail list searches for
    mails: int  # archive mails that are no duplicates holding it
    themes: tuple[str, ...] = ()  # keys of the themes whose word field holds it (themes.toml)


@dataclass(frozen=True, slots=True)
class Cluster:
    """A cluster as clusters.find_clusters finds it (D145)."""

    terms: tuple[tuple[str, float], ...]  # (lexeme, strength), strongest first, CLUSTER_TERMS
    mails: int  # mails that are no duplicates holding any of the first CLUSTER_QUERY_TERMS
    first_date: datetime | None  # earliest and latest of those mails
    last_date: datetime | None
    months: tuple[tuple[date, int], ...]  # first day of every month with such mails, ascending
