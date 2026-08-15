"""Clipboard and key injection, through whatever this machine gives us.

A Wayland session has wl-clipboard and ydotool, an X11 one has xclip and
xdotool, and macOS has pbcopy with the key press going straight to
CoreGraphics. Which of them is here gets decided in one place, and each is a
small group of functions below it: another desktop, or another operating
system, adds a group and a line to the chooser rather than a branch inside
every function here.
"""

import collections
import ctypes
import functools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from i18n import t

# Linux input event codes (linux/input-event-codes.h), which is what ydotool
# takes. They are also the list of keys a paste shortcut may be built from, so
# xdotool is held to the same table rather than being handed the text as typed.
KEYCODES = {
    "ctrl": 29, "control": 29, "shift": 42, "alt": 56, "super": 125, "meta": 125,
    "v": 47, "insert": 110, "enter": 28, "return": 28,
}

# xdotool speaks X keysyms, which spell some of those differently.
KEYSYMS = {"control": "ctrl", "meta": "super", "insert": "Insert",
           "enter": "Return", "return": "Return"}

# Apple virtual key codes, which say where a key sits rather than what is
# printed on it: the same numbers on a Turkish and a US keyboard.
MAC_KEYCODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7,
    "c": 8, "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15,
    "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22,
    "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29,
    "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "l": 37,
    "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44,
    "n": 45, "m": 46, ".": 47, "`": 50, "enter": 36, "return": 36,
}
MAC_FLAGS = {"shift": 1 << 17, "ctrl": 1 << 18, "alt": 1 << 19, "command": 1 << 20}
# What the same modifier is called on a Mac keyboard.
MAC_ALIASES = {"cmd": "command", "meta": "command", "super": "command",
               "control": "ctrl", "option": "alt"}
HID_EVENT_TAP = 0   # kCGHIDEventTap: the event goes in where the keyboard does


# pbpaste only reads text, EPS and RTF.  In particular, an image on a Mac's
# clipboard comes back as an empty byte string and pbcopy then replaces it with
# empty plain text.  Keep every NSPasteboard representation in short-lived
# files instead.  The manifest stays small even when the clipboard holds a
# large TIFF, and no additional Python package is needed.
_MAC_SNAPSHOT = collections.namedtuple("MacClipboardSnapshot", "directory manifest")

_MAC_SNAPSHOT_SCRIPT = r'''
ObjC.import("AppKit");
const root = ObjC.unwrap(
  $.NSProcessInfo.processInfo.environment.objectForKey("DIKTE_PASTEBOARD_DIR")
);
const pasteboard = $.NSPasteboard.generalPasteboard;
const items = pasteboard.pasteboardItems;
const result = [];
for (let i = 0; i < items.count; i++) {
  const item = items.objectAtIndex(i);
  const representations = [];
  const types = item.types;
  for (let j = 0; j < types.count; j++) {
    const type = ObjC.unwrap(types.objectAtIndex(j));
    const data = item.dataForType(type);
    if (!data) continue;
    const file = `${i}-${j}.bin`;
    if (data.writeToFileAtomically(`${root}/${file}`, true)) {
      representations.push({type, file});
    }
  }
  result.push(representations);
}
JSON.stringify(result);
'''

_MAC_RESTORE_SCRIPT = r'''
ObjC.import("AppKit");
const root = ObjC.unwrap(
  $.NSProcessInfo.processInfo.environment.objectForKey("DIKTE_PASTEBOARD_DIR")
);
const input = $.NSFileHandle.fileHandleWithStandardInput.readDataToEndOfFile;
const source = $.NSString.alloc.initWithDataEncoding(input, $.NSUTF8StringEncoding);
const rows = JSON.parse(ObjC.unwrap(source));
const items = [];
for (const representations of rows) {
  const item = $.NSPasteboardItem.alloc.init;
  for (const representation of representations) {
    const data = $.NSData.dataWithContentsOfFile(
      `${root}/${representation.file}`
    );
    if (data) item.setDataForType(data, representation.type);
  }
  items.push(item);
}
const pasteboard = $.NSPasteboard.generalPasteboard;
pasteboard.clearContents;
pasteboard.writeObjects($(items));
'''


class PasteError(Exception):
    pass


# --- the key press, one group per system ----------------------------------

def _keys(shortcut):
    """'Ctrl+V' -> ['ctrl', 'v'], every one of them a key we know."""
    parts = [key.strip().lower() for key in str(shortcut).split("+") if key.strip()]
    for key in parts:
        if key not in KEYCODES:
            raise PasteError(t("Unknown key: {key}", key=key))
    return parts


def _ydotool_command(shortcut):
    """ydotool wants a press event per key, then a release in reverse."""
    codes = [KEYCODES[key] for key in _keys(shortcut)]
    return ["ydotool", "key", *[f"{code}:1" for code in codes],
            *[f"{code}:0" for code in reversed(codes)]]


def _xdotool_command(shortcut):
    """xdotool takes the whole combination as one argument."""
    keys = [KEYSYMS.get(key, key) for key in _keys(shortcut)]
    return ["xdotool", "key", "--clearmodifiers", "+".join(keys)]


def _program_keyboard(program, command, hint=""):
    """A desktop that presses keys by running another program.

    Returns the three fields an entry below is built from: the program's name,
    whether it is here at all, and the press itself.
    """

    def ready():
        return shutil.which(program) is not None

    def press(shortcut, delay):
        if not ready():
            raise PasteError(t("{tool} not found, cannot paste automatically.",
                               tool=program))
        argv = command(shortcut)
        time.sleep(delay)  # let the selection settle and focus come back
        try:
            res = subprocess.run(argv, capture_output=True, text=True, timeout=10)
        except (subprocess.SubprocessError, OSError) as exc:
            raise PasteError(t("Could not run {tool}: {error}",
                               tool=program, error=exc)) from exc
        if res.returncode != 0:
            message = t("{tool} failed: {error}", tool=program,
                        error=res.stderr.strip() or "unknown error")
            raise PasteError(f"{message}\n{t(hint)}" if hint else message)

    return {"keyboard": program, "ready": ready, "press": press}


def _macos_keys(shortcut):
    """'Cmd+V' -> (9, 0x100000): where the key sits, and the modifiers on it."""
    parts = [key.strip().lower() for key in str(shortcut).split("+") if key.strip()]
    parts = [MAC_ALIASES.get(part, part) for part in parts]
    if not parts or parts[-1] not in MAC_KEYCODES:
        raise PasteError(t("Unknown key: {key}", key=parts[-1] if parts else shortcut))
    flags = 0
    for part in parts[:-1]:
        if part not in MAC_FLAGS:
            raise PasteError(t("Unknown key: {key}", key=part))
        flags |= MAC_FLAGS[part]
    return MAC_KEYCODES[parts[-1]], flags


@functools.lru_cache(maxsize=1)
def _macos_api():
    """The bit of CoreGraphics and Accessibility a paste goes through.

    Loaded on the first paste rather than at import: this module is read on
    every system, and these two frameworks exist on one of them.
    """
    try:
        services = ctypes.CDLL(
            "/System/Library/Frameworks/ApplicationServices.framework"
            "/ApplicationServices"
        )
        core = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
    except OSError as exc:
        raise PasteError(t("Could not run {tool}: {error}",
                           tool="CoreGraphics", error=exc)) from exc
    services.AXIsProcessTrusted.argtypes = []
    services.AXIsProcessTrusted.restype = ctypes.c_bool
    services.CGEventCreateKeyboardEvent.argtypes = [
        ctypes.c_void_p, ctypes.c_ushort, ctypes.c_bool,
    ]
    services.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
    services.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    services.CGEventSetFlags.restype = None
    services.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    services.CGEventPost.restype = None
    core.CFRelease.argtypes = [ctypes.c_void_p]
    core.CFRelease.restype = None
    return services, core


def _macos_trusted():
    """Whether macOS lets this process type into another application."""
    try:
        return bool(_macos_api()[0].AXIsProcessTrusted())
    except PasteError:
        return False


_asked_for_permission = False


def _ask_for_permission():
    """Open the one settings pane that grants it, and only the first time.

    Every dictation would otherwise reopen it until the box is ticked, which is
    a window in the user's face on top of the paste that did not happen.
    """
    global _asked_for_permission
    if _asked_for_permission:
        return
    _asked_for_permission = True
    try:
        subprocess.Popen(
            ["open", ("x-apple.systempreferences:com.apple.preference.security"
                      "?Privacy_Accessibility")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
        )
    except OSError:
        pass


def _macos_press(shortcut, delay):
    """Post the key down and up straight into the window system.

    Nothing is typed anywhere until macOS has been told to trust Dikte, and it
    only asks once, when the paste it was granted for is first tried.
    """
    keycode, flags = _macos_keys(shortcut)
    services, core = _macos_api()
    if not _macos_trusted():
        _ask_for_permission()
        raise PasteError(t(
            "macOS has not been told to let Dikte press keys. Turn Dikte on "
            "under System Settings → Privacy & Security → Accessibility."
        ))

    time.sleep(delay)  # let the selection settle and focus come back
    down = services.CGEventCreateKeyboardEvent(None, keycode, True)
    up = services.CGEventCreateKeyboardEvent(None, keycode, False)
    if not down or not up:
        for event in (down, up):
            if event:
                core.CFRelease(event)
        raise PasteError(t("Could not run {tool}: {error}", tool="CoreGraphics",
                           error="it would not make a keyboard event"))
    try:
        for event in (down, up):
            services.CGEventSetFlags(event, flags)
            services.CGEventPost(HID_EVENT_TAP, event)
            time.sleep(0.01)
    finally:
        core.CFRelease(down)
        core.CFRelease(up)


# --- Windows ---------------------------------------------------------------

# Virtual-key codes (winuser.h). A single letter or digit is its ASCII code;
# these are the named keys a paste shortcut is built from.
WIN_KEYS = {
    "v": 0x56, "insert": 0x2D, "enter": 0x0D, "return": 0x0D,
    "space": 0x20, "tab": 0x09, "home": 0x24, "end": 0x23,
    "pgup": 0x21, "pgdown": 0x22, "up": 0x26, "down": 0x28,
    "left": 0x25, "right": 0x27,
}
WIN_MODS = {
    "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "menu": 0x12,
    "meta": 0x5B, "super": 0x5B, "win": 0x5B,
}
# Keys that only exist as an "extended" key on the Windows keyboard.
WIN_EXTENDED = {0x2D, 0x24, 0x23, 0x22, 0x21, 0x26, 0x28, 0x25, 0x27}

_WINDOWS_SNAPSHOT = collections.namedtuple(
    "WindowsClipboardSnapshot", "directory manifest")

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_size_t),
                ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    # Windows keeps a MOUSEINPUT of the same size in this union; the union has
    # to be its size for SendInput to accept the structure.
    _fields_ = [("ki", _KEYBDINPUT), ("_pad", ctypes.c_byte * 32)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", _INPUTUNION)]


@functools.lru_cache(maxsize=1)
def _windows_api():
    """user32 and kernel32, with the clipboard and input calls typed.

    Loaded on the first use rather than at import, like the macOS frameworks:
    this module is read on every system, and these live on one of them.
    """
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except OSError as exc:
        raise PasteError(t("Could not reach the Windows clipboard: {error}",
                           error=exc)) from exc
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_bool
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = ctypes.c_bool
    user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
    user32.IsClipboardFormatAvailable.restype = ctypes.c_bool
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.EnumClipboardFormats.argtypes = [ctypes.c_uint]
    user32.EnumClipboardFormats.restype = ctypes.c_uint
    user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(_INPUT), ctypes.c_int]
    user32.SendInput.restype = ctypes.c_uint
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_bool
    kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
    kernel32.GlobalSize.restype = ctypes.c_size_t
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.restype = ctypes.c_void_p
    return user32, kernel32


def _windows_keys(shortcut):
    """'Ctrl+V' -> [0x11, 0x56]: modifiers first, then the key."""
    parts = [key.strip().lower() for key in str(shortcut).split("+") if key.strip()]
    mods, key = [], None
    for part in parts:
        if part in WIN_MODS:
            mods.append(WIN_MODS[part])
        elif key is None:
            code = WIN_KEYS.get(part)
            if code is None and len(part) == 1 and part.isalnum():
                code = ord(part.upper())
            if code is None:
                raise PasteError(t("Unknown key: {key}", key=part))
            key = code
        else:
            raise PasteError(t("Unknown key: {key}", key=part))
    if key is None:
        raise PasteError(t("Unknown key: {key}", key=shortcut))
    return mods + [key]


def _key_input(vk, flags):
    ki = _KEYBDINPUT()
    ki.wVk = vk
    ki.dwFlags = flags
    if vk in WIN_EXTENDED:
        ki.dwFlags |= KEYEVENTF_EXTENDEDKEY
    entry = _INPUT()
    entry.type = INPUT_KEYBOARD
    entry.union.ki = ki
    return entry


def _windows_press(shortcut, delay):
    """Press a paste combination by injecting key events into the system.

    SendInput types into whatever has focus, which is what ydotool and xdotool
    do on the other systems, and needs no permission beyond running on the same
    desktop.
    """
    codes = _windows_keys(shortcut)
    time.sleep(delay)  # let the selection settle and focus come back
    events = ([_key_input(code, 0) for code in codes]
              + [_key_input(code, KEYEVENTF_KEYUP) for code in reversed(codes)])
    user32, _ = _windows_api()
    buffer = (_INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), buffer, ctypes.sizeof(_INPUT))
    if sent != len(events):
        raise PasteError(t("Windows would not type {shortcut}.",
                           shortcut=shortcut))


def _windows_formats(user32, kernel32):
    """{format number: bytes} for everything on the open Windows clipboard."""
    out, fmt = {}, 0
    while True:
        fmt = user32.EnumClipboardFormats(fmt)
        if not fmt:
            break
        handle = user32.GetClipboardData(fmt)
        if not handle:
            continue
        size = kernel32.GlobalSize(handle)
        if not size:
            continue
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            continue
        try:
            blob = ctypes.string_at(ptr, size)
        finally:
            kernel32.GlobalUnlock(handle)
        if blob:
            out[fmt] = blob
    return out


def _windows_read():
    """The text on the Windows clipboard as bytes, or a full snapshot.

    Windows, like macOS, holds more than text, so a dictation takes the whole
    clipboard and puts it back: every format, filed into short-lived files.
    """
    try:
        user32, kernel32 = _windows_api()
    except PasteError:
        return None
    if not user32.OpenClipboard(None):
        return None
    try:
        if user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if handle:
                size = kernel32.GlobalSize(handle)
                ptr = kernel32.GlobalLock(handle)
                if ptr and size:
                    try:
                        text = ctypes.string_at(
                            ptr, size).decode("utf-16-le", "replace")
                        return text.split("\x00", 1)[0].encode("utf-8")
                    finally:
                        kernel32.GlobalUnlock(handle)
        formats = _windows_formats(user32, kernel32)
        if formats:
            directory = tempfile.mkdtemp(prefix="dikte-clipboard-")
            manifest = []
            for fmt, blob in formats.items():
                name = f"{fmt}.bin"
                try:
                    with open(os.path.join(directory, name), "wb") as fh:
                        fh.write(blob)
                    manifest.append({"format": fmt, "file": name})
                except OSError:
                    continue
            if manifest:
                return _WINDOWS_SNAPSHOT(directory, manifest)
    finally:
        user32.CloseClipboard()
    return None


def _windows_write(text):
    """Put text on the Windows clipboard as CF_UNICODETEXT."""
    user32, kernel32 = _windows_api()
    data = (str(text) + "\x00").encode("utf-16-le")
    if not user32.OpenClipboard(None):
        raise PasteError(t("Could not open the Windows clipboard."))
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(data))
        if not handle:
            raise PasteError(t("Could not allocate clipboard memory."))
        ptr = kernel32.GlobalLock(handle)
        if ptr:
            ctypes.memmove(ptr, data, len(data))
            kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            raise PasteError(t("Could not put the text on the clipboard."))
    finally:
        user32.CloseClipboard()


def _windows_restore(snapshot):
    """Put a Windows snapshot back, then discard its short-lived files."""
    user32, kernel32 = _windows_api()
    formats = {}
    for row in snapshot.manifest:
        try:
            with open(os.path.join(snapshot.directory, row["file"]), "rb") as fh:
                formats[row["format"]] = fh.read()
        except OSError:
            continue
    if formats and user32.OpenClipboard(None):
        try:
            user32.EmptyClipboard()
            for fmt, blob in formats.items():
                handle = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(blob))
                if not handle:
                    continue
                ptr = kernel32.GlobalLock(handle)
                if ptr:
                    ctypes.memmove(ptr, blob, len(blob))
                    kernel32.GlobalUnlock(handle)
                if not user32.SetClipboardData(fmt, handle):
                    kernel32.GlobalFree(handle)
        finally:
            user32.CloseClipboard()
    shutil.rmtree(snapshot.directory, ignore_errors=True)


# --- which of them is here -------------------------------------------------

Desktop = collections.namedtuple(
    "Desktop",
    # The clipboard program and the two commands it is run with, what to
    # install when it is missing, the paste combinations Settings offers, and
    # the key press: the program that does it, whether it can happen at all,
    # and the pressing itself.
    "clipboard packages read_command copy_command shortcuts keyboard ready press",
)

WAYLAND = Desktop(
    clipboard="wl-copy",
    packages="wl-clipboard and ydotool",
    read_command=["wl-paste", "--no-newline"],
    copy_command=["wl-copy"],
    shortcuts=["ctrl+v", "ctrl+shift+v", "shift+insert"],
    **_program_keyboard(
        "ydotool", _ydotool_command,
        hint="Is ydotoold running? (systemctl --user status ydotool)",
    ),
)

X11 = Desktop(
    clipboard="xclip",
    packages="xclip and xdotool",
    read_command=["xclip", "-selection", "clipboard", "-out"],
    copy_command=["xclip", "-selection", "clipboard", "-in"],
    shortcuts=["ctrl+v", "ctrl+shift+v", "shift+insert"],
    **_program_keyboard("xdotool", _xdotool_command),
)

MACOS = Desktop(
    clipboard="pbcopy",
    packages="",   # both are part of macOS; there is nothing to install
    read_command=["pbpaste"],
    copy_command=["pbcopy"],
    shortcuts=["cmd+v", "cmd+shift+v", "cmd+alt+shift+v"],
    keyboard="",   # no program: the key press is a call into the system
    ready=_macos_trusted,
    press=_macos_press,
)

WINDOWS = Desktop(
    clipboard="",
    packages="",   # the clipboard and the key press are part of Windows itself
    read_command=[""],
    copy_command=[""],
    shortcuts=["ctrl+v", "ctrl+shift+v", "shift+insert"],
    keyboard="",   # no program: the key press is a call into the system
    ready=lambda: True,
    press=_windows_press,
)


def desktop():
    """The programs this session's clipboard and key press go through.

    Read every time rather than settled at import: a session started before the
    display server was up would otherwise be stuck with the wrong answer, and a
    test would have nowhere to say which one it means.
    """
    if sys.platform == "win32":
        return WINDOWS
    if sys.platform == "darwin":
        return MACOS
    if os.environ.get("XDG_SESSION_TYPE") == "x11":
        return X11
    if os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return X11
    return WAYLAND


# --- the clipboard ---------------------------------------------------------

def _macos_snapshot():
    """Copy every native pasteboard type to a temporary, file-backed snapshot."""
    directory = tempfile.mkdtemp(prefix="dikte-clipboard-")
    environment = dict(os.environ, DIKTE_PASTEBOARD_DIR=directory)
    try:
        result = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", _MAC_SNAPSHOT_SCRIPT],
            capture_output=True, text=True, timeout=15, env=environment,
        )
        manifest = result.stdout.strip()
        rows = json.loads(manifest) if result.returncode == 0 else None
        if not isinstance(rows, list):
            raise ValueError("the pasteboard helper returned no manifest")
        return _MAC_SNAPSHOT(directory, manifest)
    except (json.JSONDecodeError, OSError, subprocess.SubprocessError, ValueError):
        shutil.rmtree(directory, ignore_errors=True)
        return None


def _macos_restore(snapshot):
    """Put a native snapshot back, then discard its short-lived files."""
    environment = dict(os.environ, DIKTE_PASTEBOARD_DIR=snapshot.directory)
    try:
        subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", _MAC_RESTORE_SCRIPT],
            input=snapshot.manifest, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, text=True, timeout=15, env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        shutil.rmtree(snapshot.directory, ignore_errors=True)

def read_clipboard():
    here = desktop()
    if here is WINDOWS:
        return _windows_read()
    if here is MACOS and shutil.which("osascript"):
        snapshot = _macos_snapshot()
        if snapshot is not None:
            return snapshot
    if not shutil.which(here.read_command[0]):
        return None
    try:
        res = subprocess.run(here.read_command, capture_output=True, timeout=5)
    except (subprocess.SubprocessError, OSError):
        return None
    return res.stdout if res.returncode == 0 else None


def _run_copy(payload):
    """The clipboard owner forks to keep holding the selection; leaving its
    pipes open makes subprocess.run wait for EOF forever, hence DEVNULL."""
    return subprocess.run(
        desktop().copy_command,
        input=payload,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
    )


def copy(text):
    here = desktop()
    if here is WINDOWS:
        _windows_write(text)
        return
    if not shutil.which(here.clipboard):
        raise PasteError(
            t("{tool} not found. Install {packages}.",
              tool=here.clipboard, packages=here.packages) if here.packages
            else t("{tool} not found.", tool=here.clipboard)
        )
    try:
        res = _run_copy(text.encode("utf-8"))
    except (subprocess.SubprocessError, OSError) as exc:
        raise PasteError(t("Could not copy to clipboard: {error}", error=exc)) from exc
    if res.returncode != 0:
        raise PasteError(t("{tool} exited with code {code}.",
                           tool=here.clipboard, code=res.returncode))


def copy_bytes(data):
    if isinstance(data, _WINDOWS_SNAPSHOT):
        _windows_restore(data)
        return
    if isinstance(data, _MAC_SNAPSHOT):
        _macos_restore(data)
        return
    if data is None:
        return
    if sys.platform == "win32":
        _windows_write(data.decode("utf-8", "replace"))
        return
    if not shutil.which(desktop().clipboard):
        return
    try:
        _run_copy(data)
    except (subprocess.SubprocessError, OSError):
        pass


# --- the key press ---------------------------------------------------------

def paste_ready():
    """Whether a paste can be sent: the program is here, or macOS trusts us."""
    return desktop().ready()


def press(shortcut="", delay=0.12):
    """Press a paste combination, e.g. 'ctrl+v', or this desktop's own."""
    here = desktop()
    here.press(shortcut or here.shortcuts[0], delay)
