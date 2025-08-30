import os, sys, re, shutil, zipfile, threading, subprocess, configparser, pyperclip, yt_dlp, urllib.request
from urllib.parse import urlparse
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QFileDialog, QLabel, QTextEdit, QProgressBar, QHBoxLayout, QMessageBox
)
from PyQt5.QtCore import QTimer, pyqtSignal, QObject, Qt, QPoint
from PyQt5.QtGui import QIcon

CFG_FILE = "tad.ini"
LOG_FILE = "tad.log"
QSS_FILE = "tad.qss"
URL_FILE = "tad.txt"

class EmittingStream:
    def __init__(self, write_func, file_stream):
        self.write_func = write_func
        self.file_stream = file_stream

    def write(self, text):
        if text.strip():
            self.write_func(text)
            self.file_stream.write(text)
            self.file_stream.flush()

    def flush(self):
        self.file_stream.flush()

class ProgressSignal(QObject):
    update = pyqtSignal(int)
    log = pyqtSignal(str)

class AutoYTDownloader(QWidget):
    class QuietLogger:
        def debug(self, msg): pass
        def warning(self, msg): pass
        def error(self, msg):
            print(f"❌ CHYBA: {msg}")

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setGeometry(200,200,500,320)
        self.moving = False
        self.offset = QPoint()
        self.download_path = None
        self.last_clip = ""
        self.queue = []
        self.downloading = False
        self.progress_signal = ProgressSignal()
        self.progress_signal.update.connect(self.update_progress)
        self.progress_signal.log.connect(self.safe_log)
        self.load_config()
        self.setup_ui()
        self.log_file = open(LOG_FILE, "a", encoding="utf-8")
        sys.stdout = EmittingStream(self.progress_signal.log.emit, self.log_file)
        self.clip_timer = QTimer()
        self.clip_timer.timeout.connect(self.check_clipboard)
        self.clip_timer.start(250)
        self.check_ffmpeg()
        
        self.progress_signal.log.emit("❔ Pokud ještě nemáš, nastav nejprve cílovou složku. Program začne se stahováním teprve po jejím výběru.")
        self.progress_signal.log.emit("❔ Zkopíruj odkaz na video do schránky a program jej sám přidá do fronty.")
        self.progress_signal.log.emit("❔ Stahování začne automaticky, jakmile program detekuje odkaz. Vždy se stahuje nejvyšší dostupná kvalita audia i videa.")
        self.progress_signal.log.emit("❔ Kde to je možné, bere program celé playlisty. Nejedná se o chybu ale nastavení.")
        self.progress_signal.log.emit("🛑 Program by měl být používán střídmě. Pokud provozovatel služby, na které jsou uložena videa, zjistí abnormální provoz, může tě označit za BOTa a zablokovat tvou IP a k ní přidružený účet.")
        

    def setup_ui(self):
        main = QVBoxLayout()
        main.setContentsMargins(0,0,0,0)
        self.title_bar = QWidget()
        self.title_bar.setObjectName("TitleBar")
        self.title_bar.setFixedHeight(30)
        tlay = QHBoxLayout(); tlay.setContentsMargins(10,0,5,0)
        self.title_label = QLabel("Tube Auto Downloader"); self.title_label.setObjectName("TitleLabel")
        tlay.addWidget(self.title_label); tlay.addStretch()
        btns = [("?", self.showHelp), ("—", self.showMinimized), ("×", self.close)]
        for txt,func in btns:
            b = QPushButton(txt); b.setFixedSize(30,24); 
            if txt=="?": b.setObjectName("HelpButton")
            elif txt=="—": b.setObjectName("MinimizeButton")
            else: b.setObjectName("CloseButton")
            b.clicked.connect(func); tlay.addWidget(b)
        self.title_bar.setLayout(tlay); main.addWidget(self.title_bar)
        content = QVBoxLayout()
        
        self.folder_button = QPushButton("Změnit cílovou složku"); self.folder_button.clicked.connect(self.select_folder)
        self.progress_bar = QProgressBar(); self.progress_bar.setValue(0)
        self.log = QTextEdit(); self.log.setReadOnly(True); content.addWidget(self.folder_button)
        content.addWidget(self.progress_bar); content.addWidget(self.log)
        wrap = QWidget(); wrap.setLayout(content); main.addWidget(wrap)
        self.setLayout(main)
        if self.download_path:
            self.progress_signal.log.emit(f"⬇️ Načtená cílová složka: {self.download_path}")
        else:
            self.progress_signal.log.emit("⚠️ Cílová složka není nastavena. Nestahuji!")

    def showHelp(self):
        licence_text = (
            "O PROGRAMU:<br>Tento program slouží ke stahování videí z webů, jako je YouTube, Vimeo a dalších. "
            "Je postavený s cílem umožnit pohodlné a efektivní stažení obsahu pro offline použití. "
            "Pokud z nějakého důvodu nelze stáhnout video z některého webu, je pravděpodobné, že tento web není (nebo přestal být) podporován, nebo je video chráněno či omezeno věkem.<br><br>"
            "<b>UPOZORNĚNÍ:</b><br>Používání tohoto programu může být v rozporu s VOP / TOS služeb, ze kterých obsah stahujete. "
            "Některé weby mohou aktivně blokovat stahování a porušení těchto podmínek může vést k:<br>"
            "- dočasnému nebo trvalému zablokování vaší IP adresy,<br>"
            "- zrušení uživatelského účtu,<br>"
            "- právním krokům ze strany poskytovatele obsahu.<br><br>"
            "Tento program byl vytvořen pro osobní, vzdělávací a testovací účely. Je na každém uživateli, jakým způsobem jej použije. "
            "Jakékoliv použití v rozporu se zákony vaší země nebo s podmínkami jednotlivých služeb je čistě na vaše triko.<br><br>"
            "<b>Autor tohoto programu:</b><br>"
            "- nenese žádnou odpovědnost za škody způsobené používáním programu,<br>"
            "- nenese odpovědnost za porušení podmínek třetích stran ze strany uživatele,<br>"
            "- neposkytuje žádné záruky funkčnosti, dostupnosti nebo přesnosti výsledků.<br><br>"
            "Používáním tohoto programu výslovně souhlasíte s tím, že jej používáte na vlastní riziko. "
            "Pokud s tím nesouhlasíte, program okamžitě smažte a přestaňte jej používat.<br><br>"
            "Program je povoleno distribuovat pouze v nezměněné podobě tak, jak jste jej stáhli z webu "
            "<a href='https://powerack.cz'>https://powerack.cz/projekty</a>.<br>"
            "Program je  zakázáno upravovat bez výslovného souhlasu autora!"
        )

        msg = QMessageBox(self)
        msg.setWindowTitle("LICENCE")
        msg.setTextFormat(Qt.RichText)
        msg.setTextInteractionFlags(Qt.TextBrowserInteraction)
        msg.setText(licence_text)
        msg.setStandardButtons(QMessageBox.Ok)

        msg.setStandardButtons(QMessageBox.NoButton)
        custom_button = QPushButton("Souhlasím")
        msg.addButton(custom_button, QMessageBox.AcceptRole)

        msg.exec_()


    def mousePressEvent(self, e):
        self.setWindowOpacity(1.0)
        if e.button()==Qt.LeftButton and e.pos().y()<30:
            self.moving=True; self.offset=e.pos()
    def mouseMoveEvent(self, e):
        if self.moving: self.move(self.pos()+e.pos()-self.offset)
    def mouseReleaseEvent(self, e):
        self.moving=False
        

    def check_ffmpeg(self):
        def have():
            return shutil.which("ffmpeg") or os.path.isfile(os.path.join(os.getcwd(),"ffmpeg.exe"))
        if have(): pass; return
        pass
        try:
            url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
            tmp, _ = urllib.request.urlretrieve(url)
            with zipfile.ZipFile(tmp) as z:
                root = z.namelist()[0].split("/")[0]
                for f in z.namelist():
                    if f.startswith(f"{root}/bin/"):
                        fn = os.path.basename(f)
                        if not fn: continue
                        with z.open(f) as src, open(fn,"wb") as dst:
                            dst.write(src.read())
            pass
        except Exception as e:
            pass

    def safe_log(self, text): self.log.append(text)

    def select_folder(self):
        d = QFileDialog.getExistingDirectory(self,"Vyber složku")
        if d: self.download_path=d; pass; self.save_config()

    def check_clipboard(self):
        if not self.download_path: return
        clip = pyperclip.paste().strip()
        if clip and clip != self.last_clip:
            urls = re.findall(r'https?://\S+', clip)  # vytahne vsechny http/https odkazy
            new_urls = [u for u in urls if any(k in u for k in self.supported_sites)]
            if new_urls:
                self.last_clip = clip
                for u in new_urls:
                    self.queue.append(u)
                    self.append_url_to_file(u)
                    self.progress_signal.log.emit(f"🧷 Přidáno do fronty: {u}")
                if not self.downloading:
                    threading.Thread(target=self.process_queue, daemon=True).start()


    def process_queue(self):
        self.downloading=True
        while self.queue:
            self.download_video(self.queue.pop(0))
        self.downloading=False
        self.progress_signal.update.emit(0)

    def update_progress(self, pct):
        self.progress_bar.setValue(pct)


    def download_video(self, url):
        fmt = "bv*+ba/b"
        host = urlparse(url).netloc.lower()
        origin = host.split('.')[-2] if host else "unknown"

        def hook(d):
            if d['status'] == "downloading":
                tb = d.get('total_bytes') or d.get('total_bytes_estimate')
                dl = d.get('downloaded_bytes', 0)
                if tb:
                    self.progress_signal.update.emit(int(dl / tb * 100))
            elif d['status'] == "finished":
                self.progress_signal.log.emit(f"✅ Staženo: {os.path.basename(d.get('filename', ''))}")

        # složka podle služby
        service_dir = os.path.join(self.download_path, origin)
        os.makedirs(service_dir, exist_ok=True)
        filename_template = os.path.join(service_dir, "%(title).200s.%(ext)s")

        ydl_opts = {
            'outtmpl': filename_template,
            'format': fmt,
            'merge_output_format': 'mp4',
            'quiet': True,
            'no_warnings': True,
            'logger': self.QuietLogger(),
            'noplaylist': False,
            'progress_hooks': [hook],
            'postprocessor_args': ['-loglevel', 'error'],
            'ignoreerrors': True,
            'overwrites': False
        }

        try:
            self.progress_signal.log.emit(f"▶️ Stahuji z {origin}: {url}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
            if info is None:
                self.progress_signal.log.emit(f"⚠️ Přeskočeno neexistující nebo smazané video: {url}. Je možné, že server blokuje stahování. ")
            else:
                self.progress_signal.log.emit(f"✅ Hotovo: {info.get('title', 'video')}")
        except Exception as e:
            err_str = str(e).lower()
            if "unavailable" in err_str or "terminated" in err_str:
                self.progress_signal.log.emit(f"⚠️ Video bylo smazáno nebo zabanováno ({url}) – přeskočeno.")
            else:
                self.progress_signal.log.emit(f"❌ Neočekávaná chyba při stahování: {e}")


    def append_url_to_file(self, url):
        try:
            with open("tad.txt", "a", encoding="utf-8") as f:
                f.write(url + "\n")
        except Exception as e:
            pass


    def load_config(self):
        self.supported_sites = []
        default_sites = "youtube.com/watch; youtu.be; .pornhub.; vimeo.com; redtube.com; xvideos.com; spankbang.com; tube8.com; xnxx.com; brazzers.com; youjizz.com; tnaflix.com; porn.com; dailymotion.com; facebook.com; twitter.com; instagram.com; twitch.tv; liveleak.com; metacafe.com; soundcloud.com; bandcamp.com; mixcloud.com; vocaroo.com; vevo.com; bilibili.com; nicovideo.jp; rutube.ru; ok.ru; vid.me; vidble.com; vzaar.com; mixer.com; peertube.tv; mediafire.com; ted.com; archive.org; pornhubpremium.com; nhentai.net; erome.com; imdb.com; pbs.org; gfycat.com; tumblr.com; xhamster.com"

        cfg = configparser.ConfigParser()
        if os.path.exists(CFG_FILE):
            cfg.read(CFG_FILE)

        if not cfg.has_section('Settings'):
            cfg.add_section('Settings')

        # Nastavení cesty ke složce
        p = cfg.get('Settings', 'download_path', fallback=None)
        if p and os.path.isdir(p):
            self.download_path = p

        # Získání nebo fallback + zapsání pokud chybí
        if cfg.has_option('Settings', 'supported_sites'):
            sites_raw = cfg.get('Settings', 'supported_sites')
        else:
            sites_raw = default_sites
            cfg.set('Settings', 'supported_sites', default_sites)
            with open(CFG_FILE, 'w', encoding='utf-8') as f:
                cfg.write(f)
            pass

        self.supported_sites = [s.strip() for s in re.split(r'[,\s;]+', sites_raw) if s.strip()]




    def save_config(self):
        cfg = configparser.ConfigParser()
        cfg['Settings'] = {
            'download_path': self.download_path,
            'supported_sites': '; '.join(self.supported_sites)
        }
        with open(CFG_FILE, 'w', encoding='utf-8') as f:
            cfg.write(f)


    def closeEvent(self, e):
        self.log_file.close(); e.accept()

def apply_qss(app):
    if os.path.isfile(QSS_FILE):
        try:
            with open(QSS_FILE,"r",encoding="utf-8") as f:
                app.setStyleSheet(f.read()); pass
        except Exception as e:
            pass


if __name__ == "__main__":
    app = QApplication(sys.argv)

    if os.path.isfile(QSS_FILE):
        with open(QSS_FILE, "r", encoding="utf-8") as f:
            style = f.read()
            app.setStyleSheet(style)

    window = AutoYTDownloader()
    window.show()

    exit_code = app.exec_()

    try:
        if hasattr(sys.stdout, 'close'):
            sys.stdout.close()
    except Exception as e:
        pass

    try:
        if os.path.exists(LOG_FILE):
            os.remove(LOG_FILE)
    except Exception as e:
        pass

    sys.exit(exit_code)
