"""
Read-only HID probe for the wireless mic receiver (VID 0x8888 / PID 0x1234).

Uses only Windows' built-in HID functions (hid.dll / setupapi.dll) through ctypes,
so nothing needs to be installed and it works on any Python version.

What it does
  1. Finds every HID interface the receiver exposes and prints its strings,
     usage page and report sizes, as Windows reports them.
  2. Lists the report IDs and fields for input, output and feature reports.
  3. Listens for messages the receiver sends by itself (--listen N seconds).

What it never does
  * It never calls WriteFile, HidD_SetFeature, HidD_SetOutputReport or any other
    function that sends data to the device. Nothing on the receiver can change.

Usage:
  python tools\\hid_probe.py                 # describe the receiver
  python tools\\hid_probe.py --listen 15     # also listen 15 s (press the mic buttons meanwhile)
  python tools\\hid_probe.py --all           # list every HID device on the PC
Output is also saved to hid_probe_report.txt next to this script.
"""
import argparse
import ctypes
import re
import sys
import time
from ctypes import wintypes as wt
from pathlib import Path

VID, PID = 0x8888, 0x1234
OUT = []


def say(s=""):
    print(s)
    OUT.append(s)


if sys.platform != "win32":
    print("This probe runs on Windows only.")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Windows API
# ---------------------------------------------------------------------------
hid = ctypes.WinDLL("hid")
setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
k32 = ctypes.WinDLL("kernel32", use_last_error=True)

HANDLE = ctypes.c_void_p
INVALID_HANDLE = ctypes.c_void_p(-1).value
GENERIC_READ = 0x80000000
FILE_SHARE_RW = 0x1 | 0x2
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
DIGCF_PRESENT, DIGCF_DEVICEINTERFACE = 0x2, 0x10
ERROR_IO_PENDING = 997
HIDP_STATUS_SUCCESS = 0x00110000
CAPS_SIZE = 72  # sizeof(HIDP_VALUE_CAPS) == sizeof(HIDP_BUTTON_CAPS)


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("InterfaceClassGuid", GUID), ("Flags", wt.DWORD),
                ("Reserved", ctypes.c_size_t)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", wt.ULONG), ("VendorID", wt.USHORT), ("ProductID", wt.USHORT), ("VersionNumber", wt.USHORT)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [("Usage", wt.USHORT), ("UsagePage", wt.USHORT),
                ("InputReportByteLength", wt.USHORT), ("OutputReportByteLength", wt.USHORT),
                ("FeatureReportByteLength", wt.USHORT), ("Reserved", wt.USHORT * 17),
                ("NumberLinkCollectionNodes", wt.USHORT),
                ("NumberInputButtonCaps", wt.USHORT), ("NumberInputValueCaps", wt.USHORT),
                ("NumberInputDataIndices", wt.USHORT),
                ("NumberOutputButtonCaps", wt.USHORT), ("NumberOutputValueCaps", wt.USHORT),
                ("NumberOutputDataIndices", wt.USHORT),
                ("NumberFeatureButtonCaps", wt.USHORT), ("NumberFeatureValueCaps", wt.USHORT),
                ("NumberFeatureDataIndices", wt.USHORT)]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                ("Offset", wt.DWORD), ("OffsetHigh", wt.DWORD), ("hEvent", HANDLE)]


hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
hid.HidD_GetAttributes.argtypes = [HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
hid.HidD_GetAttributes.restype = wt.BOOLEAN
for fn in ("HidD_GetManufacturerString", "HidD_GetProductString", "HidD_GetSerialNumberString"):
    getattr(hid, fn).argtypes = [HANDLE, ctypes.c_void_p, wt.ULONG]
    getattr(hid, fn).restype = wt.BOOLEAN
hid.HidD_GetPreparsedData.argtypes = [HANDLE, ctypes.POINTER(ctypes.c_void_p)]
hid.HidD_GetPreparsedData.restype = wt.BOOLEAN
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidD_FreePreparsedData.restype = wt.BOOLEAN
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
hid.HidP_GetCaps.restype = ctypes.c_long
for fn in ("HidP_GetButtonCaps", "HidP_GetValueCaps"):
    getattr(hid, fn).argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wt.USHORT), ctypes.c_void_p]
    getattr(hid, fn).restype = ctypes.c_long

setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wt.LPCWSTR, wt.HWND, wt.DWORD]
setupapi.SetupDiGetClassDevsW.restype = HANDLE
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wt.DWORD,
                                                 ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiEnumDeviceInterfaces.restype = wt.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
                                                      ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD),
                                                      ctypes.c_void_p]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wt.BOOL
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [HANDLE]

k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, HANDLE]
k32.CreateFileW.restype = HANDLE
k32.CloseHandle.argtypes = [HANDLE]
k32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
k32.CreateEventW.restype = HANDLE
k32.ResetEvent.argtypes = [HANDLE]
k32.ReadFile.argtypes = [HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.POINTER(OVERLAPPED)]
k32.ReadFile.restype = wt.BOOL
k32.WaitForSingleObject.argtypes = [HANDLE, wt.DWORD]
k32.WaitForSingleObject.restype = wt.DWORD
k32.GetOverlappedResult.argtypes = [HANDLE, ctypes.POINTER(OVERLAPPED), ctypes.POINTER(wt.DWORD), wt.BOOL]
k32.GetOverlappedResult.restype = wt.BOOL
k32.CancelIo.argtypes = [HANDLE]


# ---------------------------------------------------------------------------
USAGE_PAGES = {0x01: "Generic Desktop", 0x07: "Keyboard", 0x08: "LED", 0x09: "Button",
               0x0B: "Telephony", 0x0C: "Consumer"}
CONSUMER = {0x01: "Consumer Control", 0xB5: "Next Track", 0xB6: "Previous Track", 0xB7: "Stop",
            0xCD: "Play/Pause", 0xE2: "Mute", 0xE9: "Volume Up", 0xEA: "Volume Down"}
TELEPHONY = {0x05: "Headset", 0x20: "Hook Switch", 0x2F: "Phone Mute"}


def page_name(p):
    return f"Vendor-defined 0x{p:04X}" if p >= 0xFF00 else USAGE_PAGES.get(p, f"0x{p:04X}")


def usage_name(page, u):
    return {0x0C: CONSUMER, 0x0B: TELEPHONY}.get(page, {}).get(u, f"0x{u:02X}")


def list_hid_paths():
    guid = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(guid))
    h = setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if h in (None, INVALID_HANDLE):
        return []
    paths = []
    try:
        i = 0
        while True:
            ifd = SP_DEVICE_INTERFACE_DATA()
            ifd.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not setupapi.SetupDiEnumDeviceInterfaces(h, None, ctypes.byref(guid), i, ctypes.byref(ifd)):
                break
            i += 1
            need = wt.DWORD(0)
            setupapi.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(ifd), None, 0, ctypes.byref(need), None)
            if not need.value:
                continue
            buf = ctypes.create_string_buffer(need.value + 4)
            # cbSize of SP_DEVICE_INTERFACE_DETAIL_DATA_W: 8 on 64-bit, 6 on 32-bit
            ctypes.c_uint32.from_buffer(buf).value = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if setupapi.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(ifd), buf, need, None, None):
                paths.append(ctypes.wstring_at(ctypes.addressof(buf) + 4))
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(h)
    return paths


def open_query(path, access=0, flags=0):
    h = k32.CreateFileW(path, access, FILE_SHARE_RW, None, OPEN_EXISTING, flags, None)
    return None if h in (None, INVALID_HANDLE) else h


def get_string(h, fn):
    buf = ctypes.create_unicode_buffer(256)
    return buf.value if getattr(hid, fn)(h, buf, ctypes.sizeof(buf)) else None


def read_caps(pp, kind, report_type, n_buttons, n_values):
    """Return lines describing button and value fields of one report type."""
    lines = []
    for fn, n, is_value in (("HidP_GetButtonCaps", n_buttons, False), ("HidP_GetValueCaps", n_values, True)):
        if not n:
            continue
        raw = ctypes.create_string_buffer(CAPS_SIZE * n)
        cnt = wt.USHORT(n)
        if getattr(hid, fn)(report_type, raw, ctypes.byref(cnt), pp) != HIDP_STATUS_SUCCESS:
            continue
        for j in range(cnt.value):
            b = raw.raw[j * CAPS_SIZE:(j + 1) * CAPS_SIZE]
            page = int.from_bytes(b[0:2], "little")
            rid = b[2]
            is_range = b[12]
            u0 = int.from_bytes(b[56:58], "little")
            u1 = int.from_bytes(b[58:60], "little") if is_range else u0
            usages = usage_name(page, u0) if u0 == u1 else f"{usage_name(page, u0)}..{usage_name(page, u1)}"
            if is_value:
                bits = int.from_bytes(b[18:20], "little")
                count = int.from_bytes(b[20:22], "little")
                lmin = int.from_bytes(b[40:44], "little", signed=True)
                lmax = int.from_bytes(b[44:48], "little", signed=True)
                lines.append(f"    {kind:7s} report id {rid:3d}: value  {count} x {bits} bit, range {lmin}..{lmax}, "
                             f"page {page_name(page)}, usage {usages}")
            else:
                lines.append(f"    {kind:7s} report id {rid:3d}: button(s) page {page_name(page)}, usage {usages}")
    return lines


def describe(path, listen):
    m = re.search(r"mi_([0-9a-f]{2})", path, re.I)
    c = re.search(r"col([0-9a-f]{2})", path, re.I)
    h = open_query(path)  # access 0 = query only; works even for devices Windows keeps locked
    if not h:
        say(f"  could not open {path} (error {ctypes.get_last_error()})")
        return
    caps = HIDP_CAPS()
    try:
        attrs = HIDD_ATTRIBUTES()
        attrs.Size = ctypes.sizeof(HIDD_ATTRIBUTES)
        hid.HidD_GetAttributes(h, ctypes.byref(attrs))
        pp = ctypes.c_void_p()
        have_pp = hid.HidD_GetPreparsedData(h, ctypes.byref(pp))
        if have_pp:
            hid.HidP_GetCaps(pp, ctypes.byref(caps))
        say("-" * 72)
        say(f"Interface {m.group(1) if m else '?'}" + (f", collection {c.group(1)}" if c else "")
            + f"  |  {page_name(caps.UsagePage)}  usage {usage_name(caps.UsagePage, caps.Usage)}")
        say(f"  Manufacturer : {get_string(h, 'HidD_GetManufacturerString')!r}")
        say(f"  Product      : {get_string(h, 'HidD_GetProductString')!r}")
        say(f"  Serial       : {get_string(h, 'HidD_GetSerialNumberString')!r}")
        say(f"  VID/PID/ver  : {attrs.VendorID:04X} / {attrs.ProductID:04X} / {attrs.VersionNumber:04X}")
        say(f"  Path         : {path}")
        if have_pp:
            say(f"  Report sizes : input {caps.InputReportByteLength} B, output {caps.OutputReportByteLength} B, "
                f"feature {caps.FeatureReportByteLength} B  (each includes the 1-byte report id)")
            say("  Fields:")
            fields = (read_caps(pp, "Input", 0, caps.NumberInputButtonCaps, caps.NumberInputValueCaps)
                      + read_caps(pp, "Output", 1, caps.NumberOutputButtonCaps, caps.NumberOutputValueCaps)
                      + read_caps(pp, "Feature", 2, caps.NumberFeatureButtonCaps, caps.NumberFeatureValueCaps))
            for ln in fields or ["    (none reported)"]:
                say(ln)
            hid.HidD_FreePreparsedData(pp)
    finally:
        k32.CloseHandle(h)
    if listen and caps.InputReportByteLength:
        listen_to(path, caps.InputReportByteLength, listen)


def listen_to(path, size, seconds):
    h = open_query(path, GENERIC_READ, FILE_FLAG_OVERLAPPED)
    if not h:
        say(f"  Listening skipped: Windows didn't allow read access (error {ctypes.get_last_error()}). "
            "Normal for buttons/keyboards that Windows itself is using.")
        return
    say(f"  Listening {seconds} s (read only)...")
    ev = k32.CreateEventW(None, True, False, None)
    buf = ctypes.create_string_buffer(size)
    ov = OVERLAPPED()
    ov.hEvent = ev
    got, n = 0, wt.DWORD(0)
    start = time.time()
    try:
        pending = False
        while time.time() - start < seconds:
            if not pending:
                k32.ResetEvent(ev)
                if k32.ReadFile(h, buf, size, None, ctypes.byref(ov)):
                    pending = True  # completed immediately; event is signalled
                elif ctypes.get_last_error() == ERROR_IO_PENDING:
                    pending = True
                else:
                    say(f"  Read failed (error {ctypes.get_last_error()}).")
                    break
            if k32.WaitForSingleObject(ev, 100) == 0:
                pending = False
                if k32.GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(n), False) and n.value:
                    got += 1
                    say(f"    +{time.time() - start:6.2f}s  {buf.raw[:n.value].hex(' ')}")
        if pending:
            k32.CancelIo(h)
            k32.GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(n), True)  # wait for cancel before freeing
    finally:
        k32.CloseHandle(ev)
        k32.CloseHandle(h)
    say(f"  {got} message(s) received.")


def main():
    ap = argparse.ArgumentParser(description="Read-only HID probe for the mic receiver")
    ap.add_argument("--listen", type=int, default=0, help="seconds to passively listen for input reports")
    ap.add_argument("--all", action="store_true", help="list every HID device on the PC")
    ap.add_argument("--vid", type=lambda s: int(s, 16), default=VID)
    ap.add_argument("--pid", type=lambda s: int(s, 16), default=PID)
    a = ap.parse_args()

    say(f"HID probe (read-only, Windows built-in API)  {time.strftime('%Y-%m-%d %H:%M:%S')}  Python {sys.version.split()[0]}")
    paths = list_hid_paths()
    if a.all:
        for p in paths:
            say(p)
    else:
        tag = f"vid_{a.vid:04x}&pid_{a.pid:04x}"
        mine = sorted(p for p in paths if tag in p.lower())
        if not mine:
            say(f"No HID interface found for VID {a.vid:04X} / PID {a.pid:04X} among {len(paths)} HID devices. "
                "Is the receiver plugged in?")
        else:
            say(f"Found {len(mine)} HID interface(s) on VID {a.vid:04X} / PID {a.pid:04X}")
            for p in mine:
                describe(p, a.listen)
    out = Path(__file__).with_name("hid_probe_report.txt")
    out.write_text("\n".join(OUT), encoding="utf-8")
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
