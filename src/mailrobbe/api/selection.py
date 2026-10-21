"""The mails a bulk change or an export applies to (MailSelection, D60, D62).

resolve_selection is the one place that turns a selection into mails: ids as given (an unknown
id is not_found), filters through the conditions of the mail list, so a selection by filter is
exactly the mails the list shows. Mails come oldest first, in the list's date_asc order.
"""

from dataclasses import dataclass

from sqlalchemy import BigInteger, any_, literal, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.deps import api_error
from mailrobbe.api.filters import FilterError, internal_domains, mail_conditions, order
from mailrobbe.api.query import QueryError, parse_query
from mailrobbe.api.schemas import MailSelection
from mailrobbe.config import Settings
from mailrobbe.db.models import Mail


@dataclass(frozen=True, slots=True)
class SelectedMail:
    id: int
    raw_sha256: str


async def resolve_selection(
    session: AsyncSession, settings: Settings, selection: MailSelection, limit: int
) -> list[SelectedMail]:
    """The selected mails, oldest first. Errors: invalid_selection (not exactly one of ids and
    filters), invalid_query/invalid_filter (as the list), not_found (an unknown id),
    empty_selection, too_many_mails (more than limit)."""
    if (selection.ids is None) == (selection.filters is None):
        raise api_error(400, "invalid_selection", "give exactly one of ids and filters")
    if selection.ids is not None:
        ids = sorted(set(selection.ids))
        where = [Mail.id == any_(literal(ids, ARRAY(BigInteger)))]
    else:
        assert selection.filters is not None
        filters = selection.filters
        try:
            terms = parse_query(filters.q)
            where = mail_conditions(filters, terms, internal_domains(settings.internal_domains))
        except QueryError as error:
            raise api_error(400, "invalid_query", str(error)) from error
        except FilterError as error:
            raise api_error(400, "invalid_filter", str(error)) from error
    statement = (
        select(Mail.id, Mail.raw_sha256).where(*where).order_by(*order("date_asc")).limit(limit + 1)
    )
    mails = [SelectedMail(mail_id, sha) for mail_id, sha in await session.execute(statement)]
    if selection.ids is not None:
        missing = set(ids) - {mail.id for mail in mails}
        if missing:
            raise api_error(404, "not_found", f"no mail with id {min(missing)}")
    if not mails:
        raise api_error(400, "empty_selection", "the selection matches no mail")
    if len(mails) > limit:
        raise api_error(400, "too_many_mails", f"the selection has more than {limit} mails")
    return mails
