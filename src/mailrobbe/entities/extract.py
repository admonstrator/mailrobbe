"""One text to its entities (D80 to D83): local, deterministic, without a language model.

extract_entities runs the finders in the order of precedence of D81, each claiming the spans it
takes from the ones after it:

    contact   URLs and e-mail addresses (contact.py); the theme terms and context words around
              them (terms.py) only outside them
    money     IBANs, then account numbers, then (after phones) amounts (money.py)
    phones    after Tel., Fax and the like, and numbers starting with + (contact.py)
    dates     calendar days (dates.py)
    names     organisations, persons, places (names.py)
    domains   of the URLs and addresses found (contact.py)
    contexts  cash, donation, receipt for the amounts, IBANs and accounts (context.py)

The result is the same for the same text in any process and order: the patterns are bounded
(no nested unbounded repetition, so no catastrophic backtracking), the gazetteers and word lists
are read in file order, and the output is sorted by position, kind and key.
"""

from mailrobbe.entities import contact, context, dates, money, names, terms
from mailrobbe.entities.model import Found
from mailrobbe.entities.occurrences import Occurrences


def extract_entities(text: str) -> list[Found]:
    """The entities of one text, one Found per kind and key, by first position."""
    if not text:
        return []
    found = Occurrences(text)
    contact.find_urls(found)
    contact.find_emails(found)
    context_words = terms.find_terms(found)
    money.find_ibans(found)
    money.find_accounts(found)
    contact.find_phones(found)
    money.find_amounts(found)
    dates.find_dates(found)
    names.find_names(found)
    contact.add_domains(found)
    context.mark(found, context_words)
    return found.found()


def prepare() -> None:
    """Read the gazetteers and word lists now (a worker process does it once, at its start)."""
    names.gazetteers()
    terms.matcher()
