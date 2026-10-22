"""One page through a vision model (D182, D184): the PNG and the OCR prompt of ai.toml out, the
page's text back through the guards (ai.ocr.guards).

An answer cut at the length limit fails the page with AnswerError, never a partial text; an
empty answer or "[kein Text]" is a page without writing (text ""); a loop is cut and the page
marked uncertain. Unreachable and ModelMissing pass through from ai.services for the run to
wait or stop.
"""

import time

from mailrobbe.ai.model import OcrPage, Protocol, Service
from mailrobbe.ai.ocr.guards import clean_answer
from mailrobbe.ai.prompts import Prompts
from mailrobbe.ai.services import AnswerError, chat_image

# Tokens of one page's answer: a dense page of text with a table is about 2,500.
MAX_TOKENS = 4096


def read_page(
    service: Service,
    png: bytes,
    number: int,
    *,
    prompts: Prompts,
    protocol: Protocol,
    timeout: float,
) -> OcrPage:
    """Page `number` read from its PNG by service.model; see the module docstring."""
    started = time.monotonic()
    answer = chat_image(service, protocol, png, prompts.ocr, max_tokens=MAX_TOKENS, timeout=timeout)
    if answer.finish == "length":
        raise AnswerError(f"cut at the length limit of {MAX_TOKENS} tokens")
    cleaned = clean_answer(answer.text)
    return OcrPage(
        number=number,
        engine="vision",
        text=cleaned.text,
        uncertain=cleaned.looped,
        looped=cleaned.looped,
        seconds=round(time.monotonic() - started, 3),
        tokens_in=answer.tokens_in,
        tokens_out=answer.tokens_out,
    )
