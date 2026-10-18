"""Local source access. No media bytes are printed or sent to the agent."""
import contextlib
import hashlib
import os
from pathlib import Path


@contextlib.contextmanager
def protected_read(path, grant=None):
    path = Path(path)
    if os.name != "nt":
        with path.open("rb") as stream:
            yield stream
        return
    # Read data only; deny concurrent write/delete handles. The user explicitly
    # accepts Windows updating last-access time. Never request WRITE_ATTRIBUTES.
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path.resolve()), 0x80000000, 0x1, None, 3, 0x08000000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise OSError("Impossible d'ouvrir la source protégée.")
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    with os.fdopen(descriptor, "rb") as stream:
        yield stream


def stream_digest(stream):
    stream.seek(0)
    value = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        value.update(chunk)
    stream.seek(0)
    return value.hexdigest()
