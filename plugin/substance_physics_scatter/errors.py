"""Catch Designer's non-standard SDK exception without swallowing process control exceptions."""
try:
    from sd.api.apiexception import APIException
except ImportError:
    class APIException(BaseException):
        """Unavailable SDK placeholder for host-independent development tests."""

HOST_ERRORS = (Exception, APIException)

def optional_metadata(getter, missing_code):
    try:
        return getter()
    except APIException as error:
        if error.mErrorCode==missing_code:return None
        raise

def rollback_or_raise(original, rollback):
    try:
        rollback()
    except HOST_ERRORS as recovery:
        raise RuntimeError(f"Operation failed: {original!r}; rollback also failed: {recovery!r}") from original
    raise original
