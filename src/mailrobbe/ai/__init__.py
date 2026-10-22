"""AI services (milestone 15, D180 to D189): text of scanned PDFs and images, later audio (M16)
and summaries (M17), from services on the own machine by default.

    select      ai.queue: documents someone chose (a work list, the document list's filter, one
                document) become ai_task rows, one open task per kind and content (D186)
    run         `mailrobbe ai run` (ai.run, ai.cli), a run of kind ai in the job table with its
                steps (D187): check the services, ocr, then entities, entity figures and signals
                for the new texts; stoppable at any page, it continues there
    prepare     ai.ocr.render: the original opened only in a child process with limits, pages and
                pictures made PNG (D183); nothing else goes to a service
    recognise   ai.ocr.tesseract (in the container) and ai.ocr.vision (a vision model behind
                ai.services), with the guards of D184
    store       ai.store: ai_result is the source, document.extracted_text the copy the search,
                the hit marks, the entities and the signals read (D185)

ai.model holds what the modules hand each other and the settings' services with their locality
(D181); ai.toml the prompts with their version (D189). The API is api/ai.py.
"""
