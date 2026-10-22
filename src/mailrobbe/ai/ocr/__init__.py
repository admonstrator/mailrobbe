"""OCR of scanned PDFs and images (D182 to D184).

    render      the original opened only in a fresh child process with time and memory limits;
                out come PNGs of its pages (300 dpi for Tesseract, 1,600 px for a vision model)
    tesseract   one PNG page through Tesseract in the container: text and mean word confidence
    vision      one PNG page through a vision model (ai.services), the answer through the guards
                of ai.ocr.guards

All of it is blocking and free of the database; ai.run calls it in threads and stores the pages.
"""
