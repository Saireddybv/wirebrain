"""WinINet connection options, kept consistent with the registry proxy values."""
import ctypes
from ctypes import wintypes


class Value(ctypes.Union):
    _fields_ = [('number', wintypes.DWORD), ('text', wintypes.LPWSTR), ('time', wintypes.FILETIME)]


class Option(ctypes.Structure):
    _fields_ = [('option', wintypes.DWORD), ('value', Value)]


class Options(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('connection', wintypes.LPWSTR),
                ('count', wintypes.DWORD), ('error', wintypes.DWORD), ('options', ctypes.POINTER(Option))]


def connection_options(flags=None, proxy='', bypass=''):
    """Read original flags, or apply explicit flags and proxy strings to LAN."""
    api = ctypes.WinDLL('wininet', use_last_error=True)
    values = (Option * (1 if flags is None else 3))()
    values[0].option = 10 if flags is None else 1  # FLAGS_UI / FLAGS
    options = Options(ctypes.sizeof(Options), None, len(values), 0, values)
    size = wintypes.DWORD(ctypes.sizeof(options))
    if flags is None:
        if not api.InternetQueryOptionW(None, 75, ctypes.byref(options), ctypes.byref(size)):
            values[0].option = 1
            if not api.InternetQueryOptionW(None, 75, ctypes.byref(options), ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
        return values[0].value.number
    values[0].value.number = flags
    values[1].option, values[1].value.text = 2, proxy
    values[2].option, values[2].value.text = 3, bypass
    if not api.InternetSetOptionW(None, 75, ctypes.byref(options), ctypes.sizeof(options)):
        raise ctypes.WinError(ctypes.get_last_error())
