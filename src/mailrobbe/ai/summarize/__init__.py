"""Summaries, AI tags and theme hints (milestone 17, D300 to D311): the run's step summarize.

    input     ai.summarize.inputs: what the model reads of a mail or a document, from the
              database only (D302), with the way back from its text to the stored text
    parts     ai.summarize.parts: a text too long for the context cut into parts (D303)
    ask       ai.summarize.prompt fills the prompts of ai.toml [summarize] with the vocabulary of
              the run and frames the material (D305, D306); ai.services.chat_text sends them with
              the answer schema
    check     ai.summarize.answer: the JSON answer read and checked, tags normalised, quotes
              found in the text or dropped (D304)
    store     ai.store.store_summary_result: ai_result with its tags and theme hints
    step      ai.summarize.step: the waiting summarize tasks one at a time, for ai.run, which
              checks the text service and runs the step's loop

Everything a model writes here is a reading that can be wrong ("Maschinell erzeugt", D311): it is
stored apart from the archive's texts, never searched as full text (D309), and discarded with its
result.
"""
