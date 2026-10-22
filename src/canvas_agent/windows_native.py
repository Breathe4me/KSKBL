"""Per-thread COM lifetime and bounded, non-sensitive Windows errors."""

from contextlib import contextmanager


class WindowsAPIError(RuntimeError):
    def __init__(self, code, hresult=None):
        self.code = code
        self.hresult = (hresult & 0xFFFFFFFF) if isinstance(hresult, int) else None
        # COM descriptions/arguments can contain local identities; never retain them.
        super().__init__(code)


def com_hresult(error):
    """IDispatch often wraps the real HRESULT inside EXCEPINFO's last field."""
    info = getattr(error, "excepinfo", None)
    if info and len(info) > 5 and isinstance(info[5], int) and info[5]:
        return info[5] & 0xFFFFFFFF
    return error.hresult & 0xFFFFFFFF


@contextmanager
def apartment():
    import pythoncom

    initialized = False
    try:
        pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
        initialized = True
    except pythoncom.com_error as e:
        if e.hresult != -2147417850:  # RPC_E_CHANGED_MODE: existing STA is also usable
            raise WindowsAPIError("com_initialization_failed", e.hresult) from None
    try:
        yield
    finally:
        if initialized:
            pythoncom.CoUninitialize()
