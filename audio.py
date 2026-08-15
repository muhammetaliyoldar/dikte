"""Raw PCM capture with a live level meter.

Dictation records one source. A meeting records two of them at once, the
microphone and what comes out of the speakers, and for that it goes through
ffmpeg: one process reading both devices and merging them into the two channels
of a single stream, which is the only way the two stay aligned with each other
over an hour.

Which programs do the capturing is a property of the machine, not of the code
above: PulseAudio or PipeWire on Linux, AVFoundation through ffmpeg on macOS.
They are gathered into one group each near the bottom of this file, and a
chooser picks between them.
"""

import array
import collections
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import wave

from PyQt6.QtCore import QObject, pyqtSignal

from i18n import t

RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # s16
CHUNK_FRAMES = 1024
CHUNK_BYTES = CHUNK_FRAMES * SAMPLE_WIDTH * CHANNELS
CHUNK_LATENCY_MS = round(CHUNK_FRAMES / RATE * 1000)
MIN_FRAMES = int(RATE * 0.25)


class Recorder(QObject):
    """Runs the available sound-server recorder and reads raw PCM from stdout."""

    level = pyqtSignal(float)              # 0.0 - 1.0, for the waveform
    stopped = pyqtSignal(str, float, object)  # wav path, duration (s), per-chunk RMS
    failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc = None
        self._thread = None
        self._buffer = bytearray()
        self._rms = []
        self._cancelled = False
        self._stopping = False
        self._lock = threading.Lock()

    @property
    def active(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, target="", max_seconds=300):
        if self.active:
            return
        cmd = recording_command(target)
        if not cmd:
            self.failed.emit(t(sound().missing))
            return

        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
                **_dshow_flags(),
            )
        except OSError as exc:
            self.failed.emit(t("Could not start recording: {error}", error=exc))
            return

        self._buffer = bytearray()
        self._rms = []
        self._cancelled = False
        self._stopping = False
        self._max_bytes = int(max_seconds * RATE * SAMPLE_WIDTH * CHANNELS)
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self):
        proc = self._proc
        stdout = proc.stdout
        try:
            while True:
                chunk = stdout.read(CHUNK_BYTES)
                if not chunk:
                    break
                peak, rms = chunk_levels(chunk)
                with self._lock:
                    self._buffer.extend(chunk)
                    self._rms.append(rms)
                    too_long = len(self._buffer) >= self._max_bytes
                self.level.emit(peak)
                if too_long:
                    self._terminate()
                    break
        except (OSError, ValueError):
            pass
        # Nobody asked it to end and it captured nothing: the recorder is not
        # installed properly, or the device was refused. Said out loud here,
        # because stop() would otherwise report it as a recording that was too
        # short, which sends the user looking in the wrong place.
        with self._lock:
            captured = bool(self._buffer)
        if self._stopping or self._cancelled or captured:
            return
        try:
            detail = proc.stderr.read().decode("utf-8", "replace").strip()
        except (AttributeError, OSError):
            detail = ""
        self.failed.emit(t(
            "Audio recorder stopped before receiving sound: {error}",
            error=detail or f"exit code {proc.returncode}",
        ))

    def _terminate(self):
        self._stopping = True
        _terminate_process(self._proc)

    def cancel(self):
        self._cancelled = True
        self._terminate()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        self._proc = None
        with self._lock:
            self._buffer = bytearray()

    def stop(self):
        """End the recording and write the WAV file."""
        if not self._proc:
            return
        self._terminate()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        self._proc = None

        with self._lock:
            pcm = bytes(self._buffer)
            rms = list(self._rms)
            self._buffer = bytearray()

        if self._cancelled:
            return

        frames = len(pcm) // (SAMPLE_WIDTH * CHANNELS)
        if frames < MIN_FRAMES:  # a stray keypress, not speech
            self.failed.emit(t("Recording too short, speak for at least 0.3 s"))
            return

        path = write_wav(pcm)
        self.stopped.emit(path, frames / RATE, rms)


def write_wav(pcm, rate=RATE, channels=CHANNELS, width=SAMPLE_WIDTH):
    fd, path = tempfile.mkstemp(prefix="dikte-", suffix=".wav")
    with open(fd, "wb") as raw, wave.open(raw, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return path


def recording_command(target=""):
    """A raw-s16 capture command for the sound system on this machine."""
    return sound().record(target)


def meeting_command(mic_target, system_target):
    """One ffmpeg reading both devices and merging them into two channels."""
    return sound().meeting(mic_target, system_target)


class MeetingRecorder(QObject):
    """Microphone and speaker output into one stereo file: left is you, right is
    everyone else.

    Who said what then needs no guessing at all, because the two voices never
    shared a channel to begin with. The recording is written to disk as it
    arrives rather than held in memory, so length is not a problem and a crash
    costs the tail of the meeting instead of all of it.
    """

    levels = pyqtSignal(float, float)      # mine, theirs
    stopped = pyqtSignal(str, float)       # wav path, duration (s)
    died = pyqtSignal()                    # ffmpeg quit on its own
    failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc = None
        self._thread = None
        self._wav = None
        self._log = None
        self._path = ""
        self._frames = 0
        self._cancelled = False
        self._stopping = False
        self._lock = threading.Lock()

    @property
    def active(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, path, mic_target="", system_target="", max_seconds=14400):
        if self.active:
            return
        if not shutil.which("ffmpeg"):
            self.failed.emit(t("ffmpeg not found. Install it to record a meeting."))
            return
        if not system_target:
            system_target = default_monitor()
        if not system_target:
            self.failed.emit(t("Could not work out which speaker output to record. "
                               "Pick one in Settings → Meeting."))
            return

        cmd = meeting_command(mic_target, system_target)

        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self._wav = wave.open(path, "wb")
            self._wav.setnchannels(2)
            self._wav.setsampwidth(SAMPLE_WIDTH)
            self._wav.setframerate(RATE)
            # ffmpeg keeps talking to stderr for as long as it runs; a pipe
            # nobody drains would eventually block it, so it writes to a file.
            self._log = tempfile.TemporaryFile()
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=self._log, bufsize=0,
                **_dshow_flags(),
            )
        except (OSError, wave.Error) as exc:
            self._close_file()
            self._drop_log()
            try:
                os.unlink(path)   # an empty header nobody will ever read
            except OSError:
                pass
            self.failed.emit(t("Could not start recording: {error}", error=exc))
            return

        self._path = path
        self._frames = 0
        self._cancelled = False
        self._stopping = False
        self._max_frames = int(max_seconds * RATE)
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self):
        stdout = self._proc.stdout
        block = CHUNK_FRAMES * SAMPLE_WIDTH * 2
        try:
            while True:
                chunk = stdout.read(block)
                if not chunk:
                    break
                mine, theirs = stereo_levels(chunk)
                with self._lock:
                    if self._wav is None:
                        break
                    self._wav.writeframes(chunk)
                    self._frames += len(chunk) // (SAMPLE_WIDTH * 2)
                    too_long = self._frames >= self._max_frames
                self.levels.emit(mine, theirs)
                if too_long:
                    self._terminate()
                    break
        except (OSError, ValueError, wave.Error):
            pass
        # Nobody asked it to end: the sound device went away, or ffmpeg fell
        # over. An hour into a meeting that has to be said out loud rather than
        # discovered afterwards.
        if not self._stopping:
            self.died.emit()

    def _terminate(self):
        self._stopping = True
        _terminate_process(self._proc)

    def _close_file(self):
        with self._lock:
            wav, self._wav = self._wav, None
        if wav is not None:
            try:
                wav.close()
            except (OSError, wave.Error):
                pass

    def _error_tail(self):
        if self._log is None:
            return ""
        try:
            self._log.seek(0)
            text = self._log.read().decode("utf-8", "replace").strip()
        except OSError:
            return ""
        lines = [line for line in text.splitlines() if line.strip()]
        return lines[-1] if lines else ""

    def _finish_process(self):
        self._terminate()
        if self._thread:
            self._thread.join(timeout=3)
        self._thread = None
        code = self._proc.poll() if self._proc else 0
        self._proc = None
        self._close_file()
        return code

    def cancel(self):
        self._cancelled = True
        self._finish_process()
        self._drop_log()
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def stop(self):
        if not self._proc:
            return
        # The count is read after the join: the pump thread is still appending
        # the last blocks up to the moment it ends.
        code = self._finish_process()
        frames = self._frames
        if self._cancelled:
            self._drop_log()
            return

        # SIGINT is how the recording ends, and ffmpeg reports being interrupted
        # as a failure; only complain when nothing was captured either.
        if frames < MIN_FRAMES:
            tail = self._error_tail()
            self._drop_log()
            try:
                os.unlink(self._path)
            except OSError:
                pass
            self.failed.emit(
                t("Nothing was recorded: {error}", error=tail or f"ffmpeg → {code}")
                if tail or code else t("Recording too short, speak for at least 0.3 s")
            )
            return
        self._drop_log()
        self.stopped.emit(self._path, frames / RATE)

    def _drop_log(self):
        if self._log is not None:
            try:
                self._log.close()
            except OSError:
                pass
            self._log = None


def chunk_levels(chunk):
    """(peak, rms) in 0..1. Peak drives the waveform, RMS drives the silence check."""
    samples = array.array("h")
    usable = len(chunk) - (len(chunk) % 2)
    if usable <= 0:
        return 0.0, 0.0
    samples.frombytes(chunk[:usable])
    peak = max(abs(min(samples)), abs(max(samples))) / 32768.0
    rms = math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768.0
    return min(1.0, peak), min(1.0, rms)


def stereo_levels(chunk):
    """(left peak, right peak) in 0..1 from interleaved stereo s16."""
    samples = array.array("h")
    usable = len(chunk) - (len(chunk) % 4)
    if usable <= 0:
        return 0.0, 0.0
    samples.frombytes(chunk[:usable])
    left, right = samples[0::2], samples[1::2]
    return _peak(left), _peak(right)


def _peak(samples):
    if not samples:
        return 0.0
    return min(1.0, max(abs(min(samples)), abs(max(samples))) / 32768.0)


def _terminate_process(proc):
    """Ask a recorder to end, then insist.

    SIGINT is how pw-record, parec and ffmpeg end a pipe gracefully. Windows
    has no POSIX signals: terminate() is a hard stop, which is fine here because
    nothing the recorder is writing needs to be finalised on its side — the PCM
    comes out of its stdout and is written to disk by Dikte itself.
    """
    if proc is None or proc.poll() is not None:
        return
    if sys.platform == "win32":
        try:
            proc.terminate()
            proc.wait(timeout=2)
            return
        except (subprocess.TimeoutExpired, OSError):
            pass
    else:
        try:
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=1.5)
            return
        except (subprocess.TimeoutExpired, OSError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


# --- the sound system, one group per machine -------------------------------

# Both meeting commands merge the same way: each input down to mono at our own
# rate, then the two of them into the left and right of one stream.
MERGE_FILTER = (
    f"[0:a]aresample={RATE}:async=1,aformat=sample_fmts=s16:channel_layouts=mono[m];"
    f"[1:a]aresample={RATE}:async=1,aformat=sample_fmts=s16:channel_layouts=mono[s];"
    "[m][s]amerge=inputs=2[out]"
)


def _pulse_record(target):
    """parec, or pw-record where PulseAudio's tools were left out.

    parec works with both PulseAudio and PipeWire's PulseAudio compatibility
    service, and its source names are the same ones shown by list_sources().
    Keep pw-record as the fallback for minimal native-PipeWire installations.
    """
    if shutil.which("parec"):
        cmd = [
            "parec", "--record", "--raw", f"--rate={RATE}",
            f"--channels={CHANNELS}", "--format=s16le",
            # Left alone, parec holds about two seconds before handing anything
            # over, and then hands over all of it at once: the level meter sits
            # still and jumps, and the tail of a recording can be lost on the
            # way out. A chunk of the meter is the unit the rest of this file
            # is measured in, so ask for that.
            f"--latency-msec={CHUNK_LATENCY_MS}",
        ]
        if target:
            cmd.append(f"--device={target}")
        return cmd
    if shutil.which("pw-record"):
        cmd = [
            "pw-record", *_pw_record_raw_option(), f"--rate={RATE}",
            f"--channels={CHANNELS}", "--format=s16",
        ]
        if target:
            cmd.append(f"--target={target}")
        cmd.append("-")
        return cmd
    return []


def _pw_record_raw_option():
    """Use --raw only on pw-record releases that provide it.

    PipeWire gained --raw in 1.4, and in the same release stopped treating a
    filename of "-" as raw on its own: before it, the option is refused and the
    recorder dies before any sound arrives; after it, leaving the option out
    wraps the stream in a container the rest of this file would read as noise.
    Ubuntu 24.04 and anything else still on 1.0 or 1.2 sit on the near side of
    that line, so ask the installed binary which form it understands.
    """
    try:
        result = subprocess.run(
            ["pw-record", "--help"], capture_output=True, text=True, timeout=2
        )
        help_text = (result.stdout or "") + (result.stderr or "")
    except (subprocess.SubprocessError, OSError):
        return ["--raw"]  # preserve the existing command when probing itself fails
    if not help_text.strip():
        return ["--raw"]
    return ["--raw"] if "--raw" in help_text else []


def _pulse_meeting(mic_target, system_target):
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
        "-f", "pulse", "-thread_queue_size", "4096", "-i", mic_target or "default",
        "-f", "pulse", "-thread_queue_size", "4096", "-i", system_target,
        "-filter_complex", MERGE_FILTER, "-map", "[out]",
        "-f", "s16le", "-ar", str(RATE), "-",
    ]


def _pactl_sources():
    if not shutil.which("pactl"):
        return []
    try:
        out = subprocess.run(
            ["pactl", "-f", "json", "list", "sources"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout
        return json.loads(out)
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
        return []


def _pulse_inputs():
    return [
        (src.get("name", ""), src.get("description") or src.get("name", ""))
        for src in _pactl_sources()
        if not src.get("name", "").endswith(".monitor")
    ]


def _pulse_outputs():
    return [
        (src.get("name", ""), src.get("description") or src.get("name", ""))
        for src in _pactl_sources()
        if src.get("name", "").endswith(".monitor")
    ]


def _pulse_default_output():
    if not shutil.which("pactl"):
        return ""
    try:
        sink = subprocess.run(
            ["pactl", "get-default-sink"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""
    if not sink:
        return ""
    monitor = f"{sink}.monitor"
    names = {name for name, _ in _pulse_outputs()}
    return monitor if not names or monitor in names else ""


# macOS hands out no monitor of its own: what the speakers are playing is not
# an input, and the only way to record it is a driver that pretends to be one.
# These are the three people install.
LOOPBACK_DEVICES = ("blackhole", "loopback", "soundflower")


def _avfoundation_record(target):
    if not shutil.which("ffmpeg"):
        return []
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
        # AVFoundation names an input "video:audio", so the empty half in front
        # of the colon is what says this recording has no picture in it.
        "-f", "avfoundation", "-i", f":{target or 'default'}",
        "-ac", str(CHANNELS), "-ar", str(RATE), "-f", "s16le", "-",
    ]


def _avfoundation_meeting(mic_target, system_target):
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
        "-thread_queue_size", "4096",
        "-f", "avfoundation", "-i", f":{mic_target or 'default'}",
        "-thread_queue_size", "4096",
        "-f", "avfoundation", "-i", f":{system_target}",
        "-filter_complex", MERGE_FILTER, "-map", "[out]",
        "-f", "s16le", "-ar", str(RATE), "-",
    ]


def _avfoundation_inputs():
    """[(index, name)] for every capture device AVFoundation offers.

    The index is what the recorder is given, because that is what ffmpeg takes;
    it changes when devices are plugged in, which is why the name is shown.
    """
    if not shutil.which("ffmpeg"):
        return []
    try:
        # Listing devices is not a thing ffmpeg can do without an input, so it
        # is asked for one it cannot open: the list comes out on stderr and the
        # command then fails, which is the documented way of doing this.
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-f", "avfoundation",
             "-list_devices", "true", "-i", ""],
            capture_output=True, text=True, timeout=8, check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return []

    devices, listing = [], False
    for line in result.stderr.splitlines():
        if "AVFoundation audio devices:" in line:
            listing = True
            continue
        if not listing:
            continue
        match = re.search(r"\[(\d+)\]\s+(.+)$", line)
        if match:
            devices.append((match.group(1), match.group(2).strip()))
    return devices


def _avfoundation_default_output():
    for name, description in _avfoundation_inputs():
        if any(word in description.lower() for word in LOOPBACK_DEVICES):
            return name
    return ""


Sound = collections.namedtuple(
    "Sound",
    # How to capture one source and two at once, the two device lists, which
    # device a meeting records the far side from, and what to say when the
    # programs for any of it are not installed.
    "record meeting inputs outputs default_output missing",
)

PULSE = Sound(
    record=_pulse_record,
    meeting=_pulse_meeting,
    inputs=_pulse_inputs,
    outputs=_pulse_outputs,
    default_output=_pulse_default_output,
    missing="No audio recorder found. Install pulseaudio-utils or pipewire-audio.",
)

COREAUDIO = Sound(
    record=_avfoundation_record,
    meeting=_avfoundation_meeting,
    inputs=_avfoundation_inputs,
    # Every macOS capture device is offered as the far side of a meeting, the
    # loopback driver among them: there is no way to tell them apart, and an
    # empty list would leave nothing to pick.
    outputs=_avfoundation_inputs,
    default_output=_avfoundation_default_output,
    missing="ffmpeg not found. Install it with: brew install ffmpeg",
)

# --- Windows ---------------------------------------------------------------

# Windows has no native loopback source either: what the speakers are playing
# is not an input, and the only way to record it is a driver that pretends to
# be one. VB-Audio Virtual Cable is the one everyone installs, and many sound
# cards still offer a "Stereo Mix" recording device. These are what the name
# matching below looks for.
LOOPBACK_HINTS = ("cable output", "stereo mix", "virtual audio", "vb-audio",
                  "vb-cable", "aux ", "waveout", "loopback")


def _dshow_flags():
    # A console window per dictation would flash in the user's face.
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if sys.platform == "win32" else {}


def _dshow_record(target):
    """One capture device through ffmpeg's DirectShow backend.

    This is the one recorder that needs ffmpeg for a dictation as well as for
    a meeting, which is fine: the installer puts it there, and the settings
    window says why when it is missing.
    """
    if not shutil.which("ffmpeg"):
        return []
    cmd = [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
        "-f", "dshow", "-i", f"audio={target or _default_input()}",
        "-ac", str(CHANNELS), "-ar", str(RATE), "-f", "s16le", "-",
    ]
    return cmd


def _dshow_meeting(mic_target, system_target):
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
        "-thread_queue_size", "4096",
        "-f", "dshow", "-i", f"audio={mic_target or _default_input()}",
        "-thread_queue_size", "4096",
        "-f", "dshow", "-i", f"audio={system_target}",
        "-filter_complex", MERGE_FILTER, "-map", "[out]",
        "-f", "s16le", "-ar", str(RATE), "-",
    ]


def _default_input():
    """The friendly name of Windows' current default capture device, or ''.

    ffmpeg's dshow needs a name where the sound servers take "the default", so
    the default has to be looked up rather than left blank. Asked of the Core
    Audio API through ctypes: IMMDeviceEnumerator → GetDefaultAudioEndpoint
    (eCapture) → the FriendlyName property. Falls back to the first real
    microphone DirectShow lists when the API is not reachable.
    """
    if sys.platform != "win32":
        return ""
    try:
        from ctypes import (CFUNCTYPE, HRESULT, Structure, Union, byref, c_ubyte,
                            c_ulong, c_ushort, c_void_p, c_wchar_p)
    except ImportError:
        return ""
    try:
        from ctypes import OleDLL, POINTER
        ole32 = OleDLL("ole32")
    except OSError:
        return _first_real_input()

    class GUID(Structure):
        _fields_ = [("Data1", c_ulong), ("Data2", c_ushort),
                    ("Data3", c_ushort), ("Data4", c_ubyte * 8)]

    def guid(hexdigits):
        value = GUID()
        from ctypes import memmove
        memmove(byref(value), bytes.fromhex(hexdigits), len(bytes.fromhex(hexdigits)))
        return value

    CLSID_MMDeviceEnumerator = guid("BCDE0395E52F467C8E3DC4579291692E")
    IID_IMMDeviceEnumerator = guid("A95664D296144F35A746DE8DB63617E6")
    PKEY_FriendlyName = guid("A45C254EDF1C4EFD802067D146A850E0")

    class PROPERTYKEY(Structure):
        _fields_ = [("fmtid", GUID), ("pid", c_ulong)]

    class PROPVARIANT(Structure):
        class _U(Union):
            _fields_ = [("pwszVal", c_wchar_p)]
        _fields_ = [("vt", c_ushort), ("wReserved1", c_ushort),
                    ("wReserved2", c_ushort), ("wReserved3", c_ushort), ("u", _U)]

    def method(prototype, obj, index):
        vtable = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
        return prototype(vtable[index])

    E_CAPTURE = 1
    ACTIVE = 0x00000001
    VT_LPWSTR = 31
    release_t = CFUNCTYPE(c_ulong, c_void_p)

    try:
        if ole32.CoInitialize(None) not in (0, 1):  # S_OK / S_FALSE
            return _first_real_input()
        enumerator = c_void_p()
        hr = ole32.CoCreateInstance(byref(CLSID_MMDeviceEnumerator), None, 1,
                                    byref(IID_IMMDeviceEnumerator), byref(enumerator))
        if hr != 0 or not enumerator:
            ole32.CoUninitialize()
            return _first_real_input()

        get_default = method(
            CFUNCTYPE(HRESULT, c_void_p, c_ulong, c_ulong, POINTER(c_void_p)),
            enumerator, 4)
        device = c_void_p()
        hr = get_default(enumerator, E_CAPTURE, ACTIVE, byref(device))
        release_t(enumerator.value)
        if hr != 0 or not device:
            ole32.CoUninitialize()
            return _first_real_input()

        open_store = method(
            CFUNCTYPE(HRESULT, c_void_p, c_ulong, POINTER(c_void_p)),
            device, 4)
        store = c_void_p()
        hr = open_store(device, 0, byref(store))
        if hr != 0 or not store:
            release_t(ctypes.cast(device, c_void_p).value)
            ole32.CoUninitialize()
            return _first_real_input()

        get_value = method(
            CFUNCTYPE(HRESULT, c_void_p, POINTER(PROPERTYKEY), POINTER(PROPVARIANT)),
            store, 5)
        key = PROPERTYKEY(PKEY_FriendlyName, 14)
        value = PROPVARIANT()
        name = ""
        if get_value(store, byref(key), byref(value)) == 0 and value.vt == VT_LPWSTR:
            name = value.u.pwszVal or ""
        ole32.PropVariantClear(byref(value))
        release_t(ctypes.cast(store, c_void_p).value)
        release_t(ctypes.cast(device, c_void_p).value)
        ole32.CoUninitialize()
        return _dshow_identifier_for(name)
    except (AttributeError, OSError, TypeError, ValueError):
        return _first_real_input()


def _dshow_identifier_for(friendly_name):
    """The alternative name that belongs to a friendly name, or the name itself.

    The Core Audio API hands out the friendly name (and that is also what the
    listing shows), but ffmpeg can only match against it when every character
    fits the ANSI code page. Non-ASCII names are matched through the ASCII
    "Alternative name" instead, so the identifier for this device is looked up
    from the listing. A device whose friendly name is already pure ASCII gets
    it back unchanged, and one not in the listing keeps it too.
    """
    if not friendly_name:
        return _first_real_input()
    for identifier, name, _loopback in _dshow_devices():
        if name == friendly_name:
            return identifier
    return friendly_name


def _first_real_input():
    """The first microphone DirectShow lists, as a last-resort default."""
    for identifier, _name, loopback in _dshow_devices():
        if not loopback:
            return identifier
    return ""


def _dshow_devices():
    """[(identifier, name, is_loopback)] for every capture device DirectShow offers.

    The identifier is what the recorder is given, which is what ffmpeg compares
    against its device list. ffmpeg lists a friendly name and an "Alternative
    name" per device, and the two are not interchangeable: matching on the
    friendly name is done with bytes in the ANSI code page, so a name holding
    characters outside it (Turkish "ı", "ö" on a cp1252 system, say) never
    matches even though the listing shows it perfectly. The alternative name is
    plain ASCII and always matches, so that is the identifier. `name` stays for
    the settings window to show.
    """
    if not shutil.which("ffmpeg"):
        return []
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-f", "dshow", "-list_devices", "true", "-i", "dummy"],
            capture_output=True, text=True, timeout=8, check=False,
            **_dshow_flags(),
        )
    except (subprocess.SubprocessError, OSError):
        return []
    devices = []
    for line in result.stderr.splitlines():
        if "Alternative name" in line:
            # An alternative name always follows the device it belongs to, so
            # the friendly name parsed on the previous line is swapped for its
            # ASCII identifier. (ffmpeg 9 prints no section headers, so the
            # (video) lines and their names have simply been skipped above.)
            if devices:
                alt = re.search(r'"([^"]+)"', line)
                if alt:
                    _id, name, is_loopback = devices[-1]
                    devices[-1] = (alt.group(1).strip(), name, is_loopback)
            continue
        match = re.search(r'"([^"]+)"', line)
        if not match:
            continue
        name = match.group(1).strip()
        if not name:
            continue
        if " (video)" in line:
            continue          # the webcam, not a microphone
        lowered = name.lower()
        devices.append((name, name,
                        any(hint in lowered for hint in LOOPBACK_HINTS)))
    return devices


def _dshow_inputs():
    return [(identifier, name) for identifier, name, _loopback in _dshow_devices()]


def _dshow_outputs():
    return [(identifier, name) for identifier, name, loopback in _dshow_devices()
            if loopback]


def _dshow_default_output():
    for identifier, _name, loopback in _dshow_devices():
        if loopback:
            return identifier
    return ""


WINDOWS = Sound(
    record=_dshow_record,
    meeting=_dshow_meeting,
    inputs=_dshow_inputs,
    outputs=_dshow_outputs,
    default_output=_dshow_default_output,
    missing="ffmpeg not found. Install it with: winget install Gyan.FFmpeg",
)


def sound():
    """The programs this machine records through."""
    if sys.platform == "win32":
        return WINDOWS
    return COREAUDIO if sys.platform == "darwin" else PULSE


def list_sources():
    """[(name, description)] for every real input source."""
    return sound().inputs()


def list_monitors():
    """[(name, description)] for whatever can be recorded as the other side.

    On Linux that is the monitor of an output, and recording it is recording
    whatever is being played: in a meeting the other participants, and nothing
    of your own microphone.
    """
    return sound().outputs()


def default_monitor():
    """The device the far side of a meeting comes from, or ''."""
    return sound().default_output()
