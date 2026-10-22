"""One mail as a PNG for social media (D214 to D217), with the persons in it blacked out.

    model.py    what an image is asked for: CardShape with its pixels, CardOptions, the
                categories of a redaction (RedactionKind) and its result (Redaction)
    redact.py   the one rule what is blacked out: the terms of the mail's participants, the
                entities of the chosen kinds and the team's own terms, every occurrence
                replaced by blocks in the text before anything is drawn (D216)
    render.py   the picture: a pseudo mail client window drawn with Pillow (D214)

api/social.py serves the PNG and, as JSON, what a redaction covers. Nothing of a blacked out
name reaches the image: redact() works on the text, render() draws only what it returns.
"""
