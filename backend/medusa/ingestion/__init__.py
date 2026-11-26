"""Document ingestion: validate an upload, store it safely, extract text, read header metadata."""


class IngestionError(Exception):
    """A document was accepted for processing but could not be processed. Recorded as status 'failed'."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
