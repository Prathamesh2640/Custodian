"""Live machine readings through Windows APIs (no extra dependencies)."""
import ctypes
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32")


class _FILETIME(ctypes.Structure):
    _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


class _PDH_VALUE(ctypes.Structure):
    _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]


def _ft(f):
    return (f.hi << 32) | f.lo


class Monitor:
    """Call sample() about once a second. Disk counters are optional (PDH may be disabled)."""

    DISK = (r"\PhysicalDisk(_Total)\Disk Read Bytes/sec", r"\PhysicalDisk(_Total)\Disk Write Bytes/sec")

    def __init__(self):
        self._prev = self._cpu_times()
        self._query, self._counters = None, []
        try:
            pdh = ctypes.WinDLL("pdh")
            q = ctypes.c_void_p()
            if pdh.PdhOpenQueryW(None, None, ctypes.byref(q)) == 0:
                for path in self.DISK:
                    c = ctypes.c_void_p()
                    if pdh.PdhAddEnglishCounterW(q, path, None, ctypes.byref(c)) == 0:
                        self._counters.append(c)
                pdh.PdhCollectQueryData(q)
                self._pdh, self._query = pdh, q
        except OSError:
            pass

    @staticmethod
    def _cpu_times():
        idle, kernel, user = _FILETIME(), _FILETIME(), _FILETIME()
        kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
        return _ft(idle), _ft(kernel) + _ft(user)        # kernel time includes idle time

    def sample(self):
        idle, total = self._cpu_times()
        d_idle, d_total = idle - self._prev[0], total - self._prev[1]
        self._prev = (idle, total)
        cpu = max(0.0, min(100.0, 100.0 * (1 - d_idle / d_total))) if d_total else 0.0

        mem = _MEMORYSTATUSEX(dwLength=ctypes.sizeof(_MEMORYSTATUSEX))
        kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))

        read = write = 0.0
        if self._query and len(self._counters) == 2:
            self._pdh.PdhCollectQueryData(self._query)
            vals = []
            for c in self._counters:
                v = _PDH_VALUE()
                ok = self._pdh.PdhGetFormattedCounterValue(c, 0x200, None, ctypes.byref(v)) == 0
                vals.append(v.doubleValue if ok else 0.0)
            read, write = vals
        return dict(cpu=cpu, ram=float(mem.dwMemoryLoad), ram_total=mem.ullTotalPhys,
                    ram_used=mem.ullTotalPhys - mem.ullAvailPhys, disk_read=read, disk_write=write)
