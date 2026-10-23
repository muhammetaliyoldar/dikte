# Dikte

Press `Ctrl+Space`, talk, press again. The recording is transcribed, a model
cleans it up (dropping the *uh*s, the restarts, the missing punctuation), and
the result lands in your clipboard and is pasted into whatever window you were
typing in.

Runs on **Windows**, and on KDE Plasma 6 / Wayland, GNOME X11 and macOS. No
framework: just the Python standard library, 3.11 or newer, and PyQt6.

*[Türkçe README](README.tr.md)*

> This is a Windows port of the original *dikte* by **Yusuf İpek**
> ([yusufipk/dikte](https://github.com/yusufipk/dikte)). All credit for the
> design and most of the code goes to him.

<p align="center">
  <img src="docs/settings-general.webp" width="820" alt="Dikte settings, General tab">
</p>

|  |  |
|---|---|
| <img src="docs/settings-api.webp" width="410" alt="API and models"> | <img src="docs/settings-cleanup.webp" width="410" alt="Cleanup rules"> |
| <img src="docs/settings-agent.webp" width="410" alt="Agent"> | <img src="docs/settings-meeting.webp" width="410" alt="Meeting"> |
| <img src="docs/settings-audio-file.webp" width="410" alt="Audio file"> | <img src="docs/settings-shortcuts.webp" width="410" alt="Shortcuts"> |

## Requirements

**Python 3.11 or newer** and **PyQt6**. Everything else Dikte needs (ffmpeg,
whisper.cpp, llama.cpp, wl-clipboard, xdotool, …) is either fetched from the
settings window itself or listed below per platform. Recording, transcribing
and cleaning up all work here on models of your own, so the only hard
requirement on any OS is Python and PyQt6.

## Install (Windows)

Requirements: **Python 3.11+** (from python.org, with *Add to PATH* ticked),
**PyQt6** (`pip install PyQt6`) and **ffmpeg** (`winget install Gyan.FFmpeg`).
Recording and meetings are captured through ffmpeg's DirectShow backend.

```powershell
./install.ps1       # launchers, PATH, Start menu entry, autostart
dikte               # the settings window opens on first run
```

`install.ps1` adds the `dikte` command, a Start menu entry and an autostart
entry. `./update.ps1` pulls the latest source from git and puts all of that
back; `./uninstall.ps1` takes it away again and leaves your settings and
dictations alone unless you pass `-Purge`.

The global shortcuts arrive through Dikte's built-in listener (`RegisterHotKey`),
which is always on on Windows — there is no shortcut registry to write to, so
nothing else to install. The keys are the `shortcut` and `cancel_shortcut`
settings (defaults `Ctrl+Space` and `Ctrl+Alt+Space`); change them in
Settings → Shortcuts.

## Install (Ubuntu)

Ubuntu 22.04 and later, on GNOME X11. Recording uses PulseAudio, clipboard and
pasting use the X11 tools, and the global shortcuts are caught by Dikte's own
built-in listener (which reads the keys itself, so there is nothing to install
into the desktop):

```sh
sudo apt update
sudo apt install -y git ffmpeg pulseaudio-utils xclip xdotool python3-venv
pip install --user PyQt6

git clone https://github.com/muhammetaliyoldar/dikte.git && cd dikte
python dikte.py       # the settings window opens on first run
```

A Wayland session needs the corresponding tools instead, plus the `input` group
for the hotkey listener (see the shortcut section below):

```sh
sudo apt install -y git ffmpeg pipewire-audio wl-clipboard ydotool python3-venv
sudo usermod -aG input $USER     # then log out and back in
```

On Linux, keys and settings are stored in `~/.config/dikte/config.json` (mode
600) and dictations in `~/.local/share/dikte`.

## Install (Other Linux and macOS)

On Arch/Manjaro, KDE Plasma 6 / Wayland:

```sh
sudo pacman -S --needed pipewire-audio wl-clipboard ydotool ffmpeg python-pyqt6
systemctl --user enable --now ydotool     # needed for auto-paste

./install.sh                 # or:  ./install.sh "Meta+Space" "Meta+Shift+Space"
dikte                        # the settings window opens on first run
```

On Fedora the packages are named differently, `ffmpeg-free` out of Fedora's own
repositories is enough because Dikte only ever takes the audio track of a video
file, and `ydotool` takes one step more: it ships as a system service, whose
socket stays root-owned and out of your session's reach, so auto-paste fails
with the daemon running. Point it at the path the client already looks at and
hand the socket over:

```sh
sudo dnf install pipewire-utils wl-clipboard ydotool ffmpeg-free python3-pyqt6
sudo mkdir -p /etc/systemd/system/ydotool.service.d
printf '[Service]\nExecStart=\nExecStart=/usr/bin/ydotoold --socket-path=%s/.ydotool_socket --socket-own=%s:%s\n' \
  "$XDG_RUNTIME_DIR" "$(id -u)" "$(id -g)" \
  | sudo tee /etc/systemd/system/ydotool.service.d/override.conf >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now ydotool
```

macOS has no shortcut registry for `install.sh` to install into, so the listener
that catches the keys is the mechanism there and there is nothing to run:
`brew install ffmpeg`, `pip install PyQt6`, then `python dikte.py`. A meeting
needs BlackHole or Loopback, because nothing else offers what the speakers are
playing. On macOS settings and dictations live in
`~/Library/Application Support/Dikte`.

## API keys

Speech to text and cleanup each pick a provider in the settings window. Both can
run here on models of your own (whisper.cpp and llama.cpp, fetched and verified
from the settings window), or in the cloud: speech to text on **OpenAI**,
**Groq** or **OpenRouter**, cleanup on OpenRouter or, when either is installed,
on Claude Code or Codex.

The out-of-the-box speech-to-text provider is `local`, which needs no key. For
the cloud providers a key is looked up in this order:

1. the key entered in Settings → API, kept in `config.json` (written with mode
   600 on Linux and macOS);
2. the environment variable of the same name: `OPENAI_API_KEY`, `GROQ_API_KEY`,
   `OPENROUTER_API_KEY`;
3. **on Windows only**, the user environment in the registry
   (`HKCU\Environment`), so a variable set after Dikte's parent process
   started is still found.

To keep the keys out of the config file on Linux, leave the fields empty and
export them in `~/.bashrc` (or `~/.zshrc`):

```sh
export GROQ_API_KEY="gsk_…"
export OPENROUTER_API_KEY="sk-or-…"
```

then restart Dikte. A cheap cloud setup is **Groq** for speech to text
(default model `whisper-large-v3-turbo`) and **OpenRouter** for cleanup
(default model `google/gemini-3.5-flash-lite`). Settings are stored in
`%APPDATA%\Dikte\config.json` on Windows, `~/.config/dikte/config.json` on
Linux; downloaded programs and models in `%LOCALAPPDATA%\Dikte` and
`~/.local/share/dikte`.

## Using it

| What | How |
| --- | --- |
| Start / stop recording | `Ctrl+Space`, or click the recording indicator |
| Discard the recording | `Ctrl+Alt+Space`, tray menu, or `dikte cancel` |
| Speak a command to an agent | Tray menu → *Ask Claude*, or `dikte ask` |
| Start / end a meeting | Tray menu → *Record a meeting*, or `dikte meeting` |
| Settings | Tray menu → *Settings*, or `dikte settings` |
| Reload after an update | Tray menu → *Restart*, or `dikte restart` |
| Quit | Tray menu → *Quit*, or `dikte quit` |

An indicator in the screen corner shows a live waveform, the elapsed time and
the stage it is on. It never takes focus, and clicking the recording indicator
ends the recording, the same way the toggle key does. Pressing `Ctrl+Space`
again while Dikte is still working does nothing; nothing queues up. A dictation
and a command to the agent do wait on each other for the microphone, which is
one device, but for nothing else: each has its own indicator, and the second one
stacks above the first while both are up.

Everything the settings window holds has a verb of its own too, so a script or
an agent can work the whole thing: `dikte record --seconds 8` says back what was
said, `dikte transcribe talk.mp4 --srt` writes subtitles, and the settings, the
history and the meetings are there beside them. `dikte --help` lists them, they
all take `--json`, and only the ones needing the microphone need the application
running.

## What it does

- **It can all run on this machine.** Speech to text on whisper.cpp and cleanup
  on llama.cpp, neither installed beforehand: the settings window fetches the
  program and the model, verifies the sha256 and refuses a download published
  without one, then keeps a server alive while you dictate. The graphics card is
  reached through CUDA, ROCm or Vulkan where the build allows. No key, no
  account, nothing leaving the machine.
- **Silence never reaches the API.** Handed near-silence, a transcription model
  invents a sentence instead of returning nothing ("Thanks for watching", or in
  Turkish "Altyazı M.K."). A recording is dropped when nothing rose 10 dB above
  *that recording's own* noise floor for at least 0.3 s, which is also what
  removes steady fan noise however loud, or when its loud end sits below
  -55 dBFS. The indicator reports the level it measured, which is what you
  calibrate the threshold against.
- **Misheard words are repaired.** Speech models fail phonetically on proper
  nouns, so the cleanup model is asked to fix those from context, and to leave
  the word alone when the context does not make the intended one clear. The names
  you list under Cleanup rules go to the transcription model as a hint and to the
  cleanup model as a glossary, which is what lets it recognise "kuber netis":

  ```
  raw    ıı bugün şey kuber netis üzerinde çalışan servisleri güncelledim
         yani sonra grafanada bir panel açtım hani ve pay kut ile arayüzü
         şey bitirdim işte

  result Bugün Kubernetes üzerinde çalışan servisleri güncelledim. Sonra
         Grafana'da bir panel açtım ve PyQt ile arayüzü bitirdim.
  ```
- **A failed cleanup is never silent.** The raw transcript is still pasted so the
  dictation is not lost, but the indicator turns amber with the reason instead of
  looking like a normal run.
- **A dictation can be a command instead.** Its own shortcut sends the
  transcript to Claude Code (`claude -p`) rather than pasting it, and pastes back
  what comes of it: the answer, or a sentence saying what was done. It is the
  session you would have opened yourself, so your skills and connected services
  are there, which is what makes "put that in my calendar on Thursday at three"
  a thing you can say to a window that is not Claude. Codex (`codex exec`) runs
  the same way, and OpenRouter is there as a plain question-and-answer fallback
  for a machine with neither CLI on it. Provider, model, permissions and working
  directory are under Settings → Agent, and commands close together stay in one
  conversation.
- **Meetings** are recorded from the microphone and the speaker output at the
  same time, which settles who said what by the channel a voice arrived on
  instead of guessing at it. The two sides are transcribed separately and
  interleaved into one timestamped transcript, and a second model, configured
  under Settings → Meeting along with its own instruction, turns that into
  minutes: decisions, action items, open questions. A run that fails keeps its
  recording, and a retry resumes from the transcript it already paid for.
- **Audio and video files** run through the same models under Settings → Audio
  file, optionally with `[mm:ss]` timestamps, chunked through ffmpeg when long,
  and saved as `.txt` or as `.srt` subtitles; their cleanup follows its own rules,
  written for subtitles, so the lines keep their place and nothing is shortened.
- **History** of every dictation under Settings → History, with a size limit and
  right-click to delete.
- **Turkish and English interface**, following the system locale by default.

## The global shortcuts on Linux need one logout

KWin only reads `kglobalshortcutsrc` at startup, so the shortcuts `install.sh`
writes will not fire until you log out and back in. Until then, Settings →
Shortcuts → **built-in listener** reads `/dev/input` and catches the combination
itself. The difference: it does not swallow the key, so `Ctrl+Space` also reaches
the focused application (some editors will pop up autocomplete). The listener
needs your user in the `input` group: `sudo usermod -aG input $USER`.
(Windows has no such step: the built-in listener is the mechanism there.)

## Layout

```
dikte.py          entry point, tray icon, state machine
cli.py            the command line: every verb, and what it answers with
ipc.py            one request and one reply over the local socket
audio.py          PCM capture: pw-record or ffmpeg/dshow for dictation and meetings
meeting.py        channel split, speaker labelling, cleanup, minutes
assistant.py      running a dictation through Claude Code, Codex or OpenRouter
api.py            transcription and cleanup requests (stdlib only)
cleanup.py        who rewrites the transcript: OpenRouter, here, Claude or Codex
ggml.py           whisper.cpp and llama.cpp here: fetch, verify, keep serving
hub.py            what GitHub and Hugging Face have on offer today
worker.py         transcribe → clean up → clipboard → paste
vad.py            deciding whether a recording holds speech at all
filetranscribe.py file transcription: ffmpeg, chunking, timestamps
overlay.py        the corner indicator
settings_ui.py    settings window
hotkey.py         shortcut installation and the built-in hotkey listener
paste.py          clipboard and key-press wrappers
i18n.py           the string table
```

## Command line

`dikte --help` lists every verb; each takes `--json` and `-q`. The main ones:

| Verb | Does |
| --- | --- |
| `record [--seconds N] [--paste]` | record and print what was said |
| `toggle` / `start` / `stop` / `cancel` | drive the recording like the shortcut does |
| `ask [text] [--provider claude\|codex\|openrouter]` | put a command to the agent |
| `session [status\|reset]` | the agent's conversation |
| `transcribe FILE [-o OUT] [--srt] [--timestamps]` | transcribe an audio or video file |
| `meeting`, `meetings …` | start/end a meeting, list and retry past ones |
| `history …`, `config …`, `shortcut …` | past dictations, settings and global shortcuts |
| `prompt`, `models` | the prompt a run would send; model ids a provider offers |
| `devices`, `status`, `doctor`, `test-key` | inspection and diagnostics |
| `settings`, `restart`, `quit` | the tray menu |

## Development

```sh
python -m unittest discover          # the whole suite; no network, no sound device
```

The tests need only PyQt6 and run offscreen. GitHub Actions
(`.github/workflows/tests.yml`) runs them on Ubuntu and Windows with Python
3.11, 3.12 and 3.13. See [CONTRIBUTING.md](CONTRIBUTING.md) for the test helpers
and the pitfalls of this codebase.

## Project status

Upstream history by Yusuf İpek and contributors runs from 25 July 2026 to
10 August 2026. This fork adds the Windows port, Ubuntu/macOS notes, the
PowerShell installers and the Windows CI job (15 August 2026), on the `master`
branch. `update.sh` / `update.ps1` pull new commits from this repository.

## License

GPL-3.0, see [LICENSE](LICENSE).