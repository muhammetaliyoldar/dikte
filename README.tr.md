# Dikte

`Ctrl+Space`'e bas, konuş, tekrar bas. Ses yazıya çevrilir, bir model transkripti
temizler (ıı'lar, tekrarlar, eksik noktalama), sonuç panoya kopyalanır ve o an
yazdığın pencereye yapıştırılır.

**Windows**'ta, ayrıca KDE Plasma 6 / Wayland, GNOME X11 ve macOS'ta çalışır.
Framework yok: sadece Python standart kütüphanesi (3.11 veya üstü) ve PyQt6.

*[English README](README.md)*

> Bu, **Yusuf İpek**'in ([yusufipk/dikte](https://github.com/yusufipk/dikte))
> orijinal *dikte* uygulamasının Windows sürümüdür. Tasarımın ve kodun büyük
> kısmının tüm kredisi ona aittir.

<p align="center">
  <img src="docs/settings-general.webp" width="820" alt="Dikte ayarları, Genel sekmesi">
</p>

|  |  |
|---|---|
| <img src="docs/settings-api.webp" width="410" alt="API ve modeller"> | <img src="docs/settings-cleanup.webp" width="410" alt="Temizleme kuralları"> |
| <img src="docs/settings-agent.webp" width="410" alt="Ajan"> | <img src="docs/settings-meeting.webp" width="410" alt="Toplantı"> |
| <img src="docs/settings-audio-file.webp" width="410" alt="Ses dosyası"> | <img src="docs/settings-shortcuts.webp" width="410" alt="Kısayollar"> |

## Gereksinimler

**Python 3.11 veya üstü** ve **PyQt6**. Dikte'nin ihtiyacı olan her şey (ffmpeg,
whisper.cpp, llama.cpp, wl-clipboard, xdotool, …) ya ayarlar penceresinden
indirilir ya da aşağıda platforma göre listelenir. Sesi yazıya çevirme ve
temizleme burada kendi modellerinle çalışabildiği için her işletim sistemindeki
tek zorunlu gereksinim Python ve PyQt6'dır.

## Kurulum (Windows)

Gereksinimler: **Python 3.11+** (python.org'dan, *Add to PATH* işaretli),
**PyQt6** (`pip install PyQt6`) ve **ffmpeg** (`winget install Gyan.FFmpeg`).
Kayıt ve toplantılar ffmpeg'in DirectShow altyapısıyla yapılır.

```powershell
./install.ps1       # başlatıcılar, PATH, Başlat menüsü girdisi, otomatik başlatma
dikte               # ilk açılışta ayarlar penceresi gelir
```

`install.ps1` `dikte` komutunu, Başlat menüsü girdisini ve oturum açılışında
otomatik başlatmayı kurar. `./update.ps1` en son kaynağı git'ten çeker ve hepsini
yerine koyar; `./uninstall.ps1` hepsini geri alır, `-Purge` demedikçe ayarlarına
ve diktelerine dokunmaz.

Global kısayollar Dikte'nin kendi dinleyicisiyle (`RegisterHotKey`) gelir ve
Windows'ta her zaman açıktır — yazılacak bir kısayol kaydı yok, başka kurulacak
bir şey de yok. Tuşlar `shortcut` ve `cancel_shortcut` ayarlarıdır (varsayılan
`Ctrl+Space` ve `Ctrl+Alt+Space`); Ayarlar → Kısayollar'dan değiştirilir.

## Kurulum (Ubuntu)

Ubuntu 22.04 ve sonrası, GNOME X11 oturumunda. Kayıt PulseAudio üzerinden,
pano ve yapıştırma X11 araçlarıyla yapılır; global kısayolları da Dikte'nin
kendi yerleşik dinleyicisi yakalar (tuşları kendisi okur, masaüstüne kurulacak
bir şey yok):

```sh
sudo apt update
sudo apt install -y git ffmpeg pulseaudio-utils xclip xdotool python3-venv
pip install --user PyQt6

git clone <repo-adresin> dikte && cd dikte
python dikte.py       # ilk açılışta ayarlar penceresi gelir
```

Wayland oturumunda karşılık gelen araçlar ve kısayol dinleyicisi için `input`
grubu gerekir (aşağıdaki kısayol bölümüne bak):

```sh
sudo apt install -y git ffmpeg pipewire-audio wl-clipboard ydotool python3-venv
sudo usermod -aG input $USER     # sonra oturumu kapatıp yeniden aç
```

Linux'ta anahtarlar ve ayarlar `~/.config/dikte/config.json` içinde (izin 600),
dikteler `~/.local/share/dikte` altında.

## Kurulum (Diğer Linux ve macOS)

Arch/Manjaro, KDE Plasma 6 / Wayland:

```sh
sudo pacman -S --needed pipewire-audio wl-clipboard ydotool ffmpeg python-pyqt6
systemctl --user enable --now ydotool     # otomatik yapıştırma için

./install.sh                 # ya da:  ./install.sh "Meta+Space" "Meta+Shift+Space"
dikte                        # ilk açılışta ayarlar penceresi gelir
```

Fedora'da paket adları farklı, Fedora'nın kendi depolarındaki `ffmpeg-free`
yetiyor çünkü Dikte video dosyasının yalnızca ses izini alıyor, `ydotool` da
bir adım fazla istiyor: sistem servisi olarak geliyor, soketi de root'a ait
kalıp oturumun erişemediği yerde durduğu için servis çalışırken bile otomatik
yapıştırma tutmuyor. Soketi istemcinin zaten baktığı yola al ve sahipliğini
devret:

```sh
sudo dnf install pipewire-utils wl-clipboard ydotool ffmpeg-free python3-pyqt6
sudo mkdir -p /etc/systemd/system/ydotool.service.d
printf '[Service]\nExecStart=\nExecStart=/usr/bin/ydotoold --socket-path=%s/.ydotool_socket --socket-own=%s:%s\n' \
  "$XDG_RUNTIME_DIR" "$(id -u)" "$(id -g)" \
  | sudo tee /etc/systemd/system/ydotool.service.d/override.conf >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now ydotool
```

macOS'ta `install.sh`'ın kuracağı bir kısayol kaydı yok, tuşları yakalayan
dinleyici orada mekanizmanın kendisi, dolayısıyla kurulacak bir şey de yok:
`brew install ffmpeg`, `pip install PyQt6`, sonra `python dikte.py`. Toplantı
için BlackHole ya da Loopback gerekiyor, hoparlörden çıkanı kimse vermiyor.
macOS'ta ayarlar ve dikteler `~/Library/Application Support/Dikte` içinde.

## API anahtarları

Sesi yazıya çevirme ve temizleme, ayarlar penceresinde ayrı ayrı sağlayıcı
seçer. İkisi de bu makinede kendi modellerinle çalışabilir (whisper.cpp ve
llama.cpp; ayarlar penceresinden indirilir ve doğrulanır) ya da bulutta:
sesi yazıya çevirme **OpenAI**, **Groq** veya **OpenRouter**'da; temizleme
OpenRouter'da veya kuruluysa Claude Code ya da Codex'te.

Anahtarlar ortam değişkenlerinden okunur — `OPENAI_API_KEY`, `GROQ_API_KEY`,
`OPENROUTER_API_KEY` — ve hiçbir dosyada saklanmaz:

- **Windows'ta** Ayarlar'da girdiğin anahtarlar kurulum betiği tarafından
  kullanıcı ortam değişkeni olarak kayıt defterine (`HKCU\Environment`)
  yazılır; daha önce açılmış bir kabuk bile onları böyle bulur.
- **Linux'ta** `~/.bashrc` (ya da `~/.zshrc`) içine export ekle:

  ```sh
  export GROQ_API_KEY="gsk_…"
  export OPENROUTER_API_KEY="sk-or-…"
  source ~/.bashrc
  ```

  ve Dikte'yi yeniden başlat. Önerilen en ucuz düzen: sesi yazıya çevirmede
  **Groq** (`openai/whisper-large-v3-turbo`, ses saati başına ~$0.04, cömert
  ücretsiz kotasıyla) ve temizlemede **OpenRouter**
  (`google/gemini-2.5-flash-lite`, dikte başına sentin yüzde biri). Ayarlar
  Windows'ta `%APPDATA%\Dikte\config.json`, Linux'ta `~/.config/dikte/config.json`
  içinde; indirilen modeller `%LOCALAPPDATA%\Dikte` ve `~/.local/share/dikte`
  altında.

## Kullanım

| Ne | Nasıl |
| --- | --- |
| Kaydı başlat / bitir | `Ctrl+Space`, ya da kayıt göstergesine tıkla |
| Kaydı iptal et | `Ctrl+Alt+Space`, tepsi menüsü, ya da `dikte cancel` |
| Ajana sesle komut ver | Tepsi menüsü → *Claude'a sor*, ya da `dikte ask` |
| Toplantıyı başlat / bitir | Tepsi menüsü → *Toplantı kaydet*, ya da `dikte meeting` |
| Ayarlar | Tepsi menüsü → *Ayarlar*, ya da `dikte settings` |
| Güncelleme sonrası yeniden yükle | Tepsi menüsü → *Yeniden başlat*, ya da `dikte restart` |
| Çık | Tepsi menüsü → *Çık*, ya da `dikte quit` |

Ekranın köşesindeki gösterge canlı ses dalgasını, süreyi ve hangi aşamada
olunduğunu gösterir. Odak almaz; kayıt göstergesine tıklamak da kaydı bitirir,
tıpkı `Ctrl+Space` gibi. Dikte çalışırken `Ctrl+Space`'e tekrar basmak bir şey
yapmaz, sıraya da girmez. Dikte ile ajana verilen komut yalnızca mikrofon için
birbirini bekler, o da tek aygıt olduğu için; başka hiçbir şeyde beklemezler.
Her birinin kendi göstergesi var, ikisi birden ekrandayken ikincisi birincinin
üstüne yerleşir.

Ayarlar penceresindeki her şeyin bir de komutu var; bir betik ya da bir ajan
yazılımın tamamını çalıştırabilsin diye: `dikte record --seconds 8` söyleneni
geri verir, `dikte transcribe konusma.mp4 --srt` altyazıyı yazar, ayarlar,
geçmiş ve toplantılar da yanlarında durur. Hepsini `dikte --help` sayar, hepsi
`--json` kabul eder, yalnızca mikrofona ihtiyacı olanlar uygulamanın açık
olmasını ister.

## Neler yapıyor

- **Her şey bu makinede çalışabilir.** Sesi yazıya çevirme whisper.cpp,
  temizleme llama.cpp üzerinde; ikisini de önceden kurman gerekmez: ayarlar
  penceresi programı ve modeli indirir, sha256'sını doğrular, checksum'suz
  yayınlanmış bir indirmeyi reddeder, sen dikte ettikçe sunucuyu ayakta tutar.
  Derleme destekliyorsa ekran kartına CUDA, ROCm ya da Vulkan üzerinden ulaşılır.
  Anahtar yok, hesap yok, makineden çıkan bir şey yok.
- **Sessizlik API'ye gitmez.** Sessize yakın bir ses verildiğinde model boş dize
  döndürmez, bir cümle uydurur ("Altyazı M.K.", "Thanks for watching"). *O
  kaydın kendi* gürültü tabanının 10 dB üstüne en az 0,3 saniye çıkan bir şey
  yoksa kayıt atılır; ne kadar yüksek olursa olsun sabit fanı ya da cızırtıyı
  eleyen de budur. Kaydın gürültülü ucu -55 dBFS altındaysa da atılır. Gösterge
  ölçtüğü seviyeyi yazar, eşiği ona bakarak ayarlarsın.
- **Yanlış duyulan kelimeler düzeltilir.** Konuşma modelleri özel isimlerde sesçe
  benzer bir şeye kayıyor; temizleme modelinden bunları bağlamdan onarması,
  bağlam netleştirmiyorsa dokunmaması isteniyor. Temizleme kuralları sekmesine
  yazdığın isimler transkripsiyon modeline ipucu, temizleme modeline sözlük
  olarak gidiyor; "kuber netis"i tanımasını sağlayan da bu:

  ```
  ham    ıı bugün şey kuber netis üzerinde çalışan servisleri güncelledim
         yani sonra grafanada bir panel açtım hani ve pay kut ile arayüzü
         şey bitirdim işte

  sonuç  Bugün Kubernetes üzerinde çalışan servisleri güncelledim. Sonra
         Grafana'da bir panel açtım ve PyQt ile arayüzü bitirdim.
  ```
- **Başarısız temizleme sessizce geçmez.** Dikte kaybolmasın diye ham transkript
  yine yapıştırılır ama gösterge kehribar rengine döner ve nedenini söyler,
  normal bir çalışma gibi görünmez.
- **Dikte bunun yerine bir komut da olabilir.** Kendi kısayolu transkripti
  yapıştırmak yerine Claude Code'a (`claude -p`) gönderir ve oradan döneni
  yapıştırır: cevabı ya da ne yapıldığını söyleyen bir cümle. Kendi açacağın
  oturumun aynısıdır, yani skill'lerin ve bağlı servislerin oradadır; "bunu
  perşembe üçe takvime koy" cümlesini Claude olmayan bir pencerede söyleyebilir
  olmanı sağlayan da budur. Codex (`codex exec`) da aynı şekilde çalışır;
  OpenRouter ise ikisi de kurulu olmayan bir makinede düz soru cevap için
  duruyor. Sağlayıcı, model, izinler ve çalışma dizini Ayarlar → Ajan
  sekmesinde; arka arkaya verilen komutlar tek bir konuşmada kalır.
- **Toplantılar** mikrofonla hoparlör çıkışından aynı anda kaydedilir; kimin ne
  dediği tahmin edilmez, sesin hangi kanaldan geldiğiyle belli olur. İki taraf
  ayrı ayrı yazıya çevrilip tek bir zaman damgalı transkriptte birleştirilir,
  ardından Ayarlar → Toplantı sekmesinden seçtiğin ikinci bir model kendi
  talimatıyla bunu tutanağa çevirir: kararlar, aksiyonlar, açık sorular. Yarıda
  kalan bir işlem ses kaydını saklar, yeniden denemede parası ödenmiş
  transkriptin üstünden devam eder.
- **Ses ve video dosyaları** Ayarlar → Ses dosyası sekmesinde aynı modellerden
  geçer; istersen `[dd:ss]` zaman damgalarıyla, uzun dosyalar ffmpeg ile
  parçalanarak, sonuç `.txt` ya da `.srt` altyazı olarak kaydedilerek; temizleme
  burada kendi kurallarıyla, altyazı için yazılmış haliyle çalışır: satırlar
  yerinde kalır, hiçbir şey kısaltılmaz.
- **Geçmiş** Ayarlar → Geçmiş sekmesinde; boyut sınırı var, sağ tıklayıp
  silebilirsin.
- **Türkçe ve İngilizce arayüz**, varsayılan olarak sistem dilini izler.

## Linux'ta global kısayollar için bir kez oturum kapatmak gerekir

KWin `kglobalshortcutsrc` dosyasını yalnızca açılışta okur, yani `install.sh`'ın
yazdığı kısayollar oturumu yeniden açana kadar tetiklenmez. O zamana kadar Ayarlar →
Kısayollar → **yerleşik dinleyici** `/dev/input` üzerinden kombinasyonu kendisi
yakalar. Tek farkı: tuşu yutmaz, yani `Ctrl+Space` odaktaki uygulamaya da iletilir
(bazı editörlerde otomatik tamamlama açılabilir). Dinleyici kullanıcının `input`
grubunda olmasını gerektirir: `sudo usermod -aG input $USER`.
(Windows'ta böyle bir adım yok: yerleşik dinleyici oradaki mekanizmanın ta
kendisi.)

## Dosyalar

```
dikte.py          giriş noktası, tepsi simgesi, durum makinesi
cli.py            komut satırı: bütün fiiller ve verdikleri cevap
ipc.py            yerel sokette bir istek, bir cevap
audio.py          PCM kaydı: pw-record ya da ffmpeg/dshow, dikte ve toplantı
meeting.py        kanal ayırma, konuşmacı etiketi, temizleme, tutanak
assistant.py      dikteyi Claude Code, Codex ya da OpenRouter'dan geçirme
api.py            transkript ve temizleme istekleri (yalnız stdlib)
cleanup.py        transkripti kim temizler: OpenRouter, burası, Claude ya da Codex
ggml.py           whisper.cpp ve llama.cpp'yi indirip burada çalıştırma
hub.py            GitHub ve Hugging Face'te bugün ne olduğu
worker.py         transkript → temizleme → pano → yapıştırma
vad.py            kayıtta gerçekten konuşma var mı kararı
filetranscribe.py dosyadan transkript: ffmpeg, parçalama, zaman damgaları
overlay.py        köşedeki gösterge
settings_ui.py    ayarlar penceresi
hotkey.py         kısayol kurulumu ve yerleşik dinleyici
paste.py          pano ve tuş basma sarmalayıcıları
i18n.py           metin tablosu
```

## Lisans

GPL-3.0, [LICENSE](LICENSE) dosyasına bak.