"""The mentions of entities in mails, from their own text and from their attachments (D80).

mentions() is the one definition the figures, the filters and the API read: a row per entity
and mail for the mail's own subject and text (document_id NULL), and a row per entity, mail and
attachment whose document's text mentions it. A mail can thus appear several times for one
entity (in its text and in two attachments); count DISTINCT mail_id.
"""

from sqlalchemy import BigInteger, Subquery, null, select, union_all

from mailrobbe.db.models import Attachment, DocumentEntity, MailEntity


def mentions(name: str = "mention") -> Subquery:
    """Columns entity_id, mail_id, occurrences, context, position, document_id."""
    own = select(
        MailEntity.entity_id,
        MailEntity.mail_id,
        MailEntity.occurrences,
        MailEntity.context,
        MailEntity.position,
        null().cast(BigInteger).label("document_id"),
    )
    attached = select(
        DocumentEntity.entity_id,
        Attachment.mail_id,
        DocumentEntity.occurrences,
        DocumentEntity.context,
        DocumentEntity.position,
        DocumentEntity.document_id,
    ).join(Attachment, Attachment.document_id == DocumentEntity.document_id)
    return union_all(own, attached).subquery(name)
