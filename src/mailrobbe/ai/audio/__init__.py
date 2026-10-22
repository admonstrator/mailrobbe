"""Transcription of audio and video (milestone 16, D290 to D297): what was said in a recording,
as lines with their time, read by Parakeet TDT 0.6B v3 in the container.

    decode      the original opened only in a fresh child process with time and memory limits
                (D292): PyAV decodes its first audio stream, out comes 16 kHz mono 16-bit PCM
    parakeet    the model files (pinned, checked, downloaded once into MAILROBBE_AI_MODEL_DIR,
                D291) and the Transcriber: Silero VAD finds the speech, pieces of at most
                PIECE_SECONDS are read with ONNX Runtime on the CPU (onnx-asr), their tokens with
                times become the lines of ai.model.TranscriptSegment (D293)

All of it is blocking and free of the database; ai.run calls it in threads and stores the lines.
"""
