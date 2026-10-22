"""Summaries, AI tags and theme hints (milestone 17, D300 to D311): the run's step summarize.

    input     ai.summarize.inputs: what the model reads of a mail or a document, from the
              database only (D302)
    parts     ai.summarize.parts: a text too long for the context cut into parts (D303)
    ask       ai.services.chat_text with the prompts of ai.toml [summarize] and the vocabulary
              of the run (D305, D306)
    check     ai.summarize.answer: the JSON answer read and checked, tags normalised, quotes
              found in the text or dropped (D304)
    store     ai.store.store_summary_result: ai_result with its tags and theme hints
    step      ai.summarize.step: the waiting summarize tasks one at a time, called by ai.run

Contract: the modules are filled by the work on the run.
"""
