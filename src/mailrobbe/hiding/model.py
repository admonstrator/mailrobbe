"""Which mails a hide rule hides (D221 to D223).

mail_hidden holds the mails each enabled rule matches; a mail is hidden when a rule matches it
and its content is not kept: in an Akte, with a note, bookmarked or reviewed relevant (D203).
Keeping is decided when a list is asked, so a note or an Akte shows a mail at once.
"""

from sqlalchemy import ColumnElement, exists, or_, select

from mailrobbe.db.models import CollectionMail, Mail, MailHidden, MailMark, Note
from mailrobbe.enums import ReviewStatus


def kept() -> ColumnElement[bool]:
    """The mail's content stays visible whatever the rules say (D203)."""
    marked = or_(MailMark.flagged.is_(True), MailMark.review == ReviewStatus.RELEVANT)
    return or_(
        Mail.raw_sha256.in_(select(CollectionMail.mail_sha256)),
        Mail.raw_sha256.in_(select(Note.mail_sha256)),
        Mail.raw_sha256.in_(select(MailMark.mail_sha256).where(marked)),
    )


def visible() -> ColumnElement[bool]:
    """No enabled rule matches the mail, or it is kept (D222)."""
    return or_(~exists().where(MailHidden.mail_id == Mail.id), kept())
