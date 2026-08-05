import ctypes
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
import queue
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
import utils
import generate_report

VENV_PYTHON = BASE_DIR / "venv" / "Scripts" / "python.exe"
PYTHON_EXE = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable

NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


def is_port_listening(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def find_pid_on_port(port):
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"], creationflags=NO_WINDOW
        ).decode("mbcs", errors="replace")
    except Exception:
        return None
    needle = f":{port}"
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 5 and parts[0] == "TCP" and parts[1].endswith(needle) and parts[3] == "LISTENING":
            try:
                return int(parts[4])
            except ValueError:
                continue
    return None


def kill_port(port):
    pid = find_pid_on_port(port)
    if pid:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                        creationflags=NO_WINDOW, capture_output=True)


# ---------- 丟進資源回收筒（不是直接抹掉） ----------
# 移除工地會連同那個工地的照片、報告一起刪掉。工地照片是補拍不回來的東西——等發現按錯，
# 路面早就鋪完了。所以這裡走 Windows 的資源回收筒，按錯還能從回收筒還原。
# 用系統內建的 shell API（ctypes），不額外裝套件，requirements.txt 維持原樣不動。
class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_uint),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


_FO_DELETE = 3
_FOF_SILENT = 0x0004
_FOF_NOCONFIRMATION = 0x0010
_FOF_ALLOWUNDO = 0x0040       # 這一個才是「丟進回收筒」的關鍵
_FOF_NOERRORUI = 0x0400


def send_to_recycle_bin(path: Path):
    """把一個資料夾（含裡面所有東西）丟進資源回收筒。失敗時丟出 OSError。"""
    func = ctypes.windll.shell32.SHFileOperationW
    func.argtypes = [ctypes.POINTER(_SHFILEOPSTRUCTW)]
    func.restype = ctypes.c_int

    op = _SHFILEOPSTRUCTW()
    op.wFunc = _FO_DELETE
    # pFrom 要用兩個 \0 結尾：這個 API 可以一次收好幾個路徑，用單一個 \0 分隔、
    # 兩個 \0 代表整串結束。只丟一個路徑時也一樣要補。
    op.pFrom = str(path) + "\0\0"
    op.fFlags = _FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_SILENT | _FOF_NOERRORUI

    result = func(ctypes.byref(op))
    if result != 0:
        raise OSError(f"移到資源回收筒失敗（代碼 {result}）")
    if op.fAnyOperationsAborted:
        raise OSError("移到資源回收筒的動作被中斷")


def site_data_summary(data_dir: Path):
    """數一數這個工地資料夾裡有幾張照片、幾份報告，用在刪除前的確認訊息上。

    講「這個工地有 34 張照片、2 份報告」比講「確定要刪除嗎」有用得多：後者每個人都是
    直接按確定。
    """
    photos = reports = 0
    if not data_dir.exists():
        return 0, 0
    for path in data_dir.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in utils.IMAGE_EXTENSIONS:
            photos += 1
        elif suffix == ".docx":
            reports += 1
    return photos, reports


def wait_for_port_closed(port, timeout_seconds=10):
    """等伺服器真的關掉。Windows 不讓你刪掉還有程式開著檔案的資料夾，
    kill_port 送出關閉指令之後要留一點時間，不然刪除會直接失敗。"""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not is_port_listening(port):
            return True
        time.sleep(0.25)
    return not is_port_listening(port)


def tailscale_url_for_port(port):
    """從 `tailscale serve status` 反查「對應到這個埠」的公開網址。

    不能只用 `tailscale funnel` 啟動時印出來的第一個網址：一台電腦服務好幾個工地時，
    那段輸出會把「目前所有工地的網址」全部列出來，直接抓第一個會拿到別的工地的網址。
    這裡改成照埠號去比對，拿到的一定是自己的。
    """
    try:
        out = subprocess.run(
            ["tailscale", "serve", "status"], capture_output=True, creationflags=NO_WINDOW
        ).stdout.decode("utf-8", errors="replace")
    except Exception:
        return None

    base = None
    for raw in out.splitlines():
        line = raw.strip()
        m_base = re.match(r"^(https://\S+)\s+\(Funnel on\)", line)
        if m_base:
            base = m_base.group(1).rstrip("/")
            continue
        m_route = re.match(r"^\|--\s+(\S+)\s+proxy\s+http://127\.0\.0\.1:(\d+)", line)
        if m_route and base and int(m_route.group(2)) == port:
            path = m_route.group(1)
            return base if path == "/" else base + path
    return None


class App:
    def __init__(self, root):
        self.root = root
        root.title("工地照片系統控制台")
        root.geometry("780x660")
        root.minsize(700, 600)

        self.ui_queue = queue.Queue()
        # 舊的 sites.json 沒有 office_port 這一欄，先補齊再讀，
        # 不然每個工地的辦公室版都會退回 8501、互相搶同一個埠。
        utils.ensure_office_ports()
        self.sites = utils.load_sites()
        self.office_processes = {}   # slug -> Popen（辦公室版伺服器）
        self.site_processes = {}     # slug -> Popen（手機版伺服器）
        self.site_links = {}         # slug -> 公開網址
        self._link_lookups = set()   # 正在背景查網址的 slug，避免重複開執行緒

        self._build_ui()
        self.refresh_site_rows()
        self.refresh_office_rows()
        self.refresh_dates()
        self.load_settings()
        self.root.after(200, self._drain_queue)
        self.root.after(500, self.poll_status)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- UI ----------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        site_frame = ttk.LabelFrame(self.root, text="工地（手機拍照連結）")
        site_frame.pack(fill="x", **pad)

        self.tree = ttk.Treeview(
            site_frame, columns=("name", "status", "link"), show="headings", height=4,
            selectmode="browse",
        )
        self.tree.heading("name", text="工地")
        self.tree.heading("status", text="狀態")
        self.tree.heading("link", text="手機網址")
        self.tree.column("name", width=150, anchor="w")
        self.tree.column("status", width=80, anchor="w")
        self.tree.column("link", width=480, anchor="w")
        self.tree.pack(fill="x", padx=8, pady=(8, 4))
        self.tree.bind("<<TreeviewSelect>>", self.on_site_selected)

        site_buttons = ttk.Frame(site_frame)
        site_buttons.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(site_buttons, text="啟動", command=self.start_site).pack(side="left", padx=(0, 4))
        ttk.Button(site_buttons, text="停止", command=self.stop_site).pack(side="left", padx=4)
        ttk.Button(site_buttons, text="複製網址", command=self.copy_link).pack(side="left", padx=4)
        ttk.Button(site_buttons, text="改名", command=self.rename_site).pack(side="left", padx=4)
        ttk.Button(site_buttons, text="＋ 新增工地", command=self.add_site).pack(side="left", padx=(16, 4))
        ttk.Button(site_buttons, text="移除工地", command=self.remove_site).pack(side="left", padx=4)

        # 辦公室版做成跟上面的工地清單一樣的一份清單：一個工地一個埠、一個網址。
        # 這樣「開啟」開的一定是你點的那一個，不會有「選單指著 A、開出來是 B」的問題，
        # 而且兩個工地可以同時開著各自的分頁。
        office_frame = ttk.LabelFrame(self.root, text="辦公室版（標記、產生報告）")
        office_frame.pack(fill="x", **pad)
        self.office_tree = ttk.Treeview(
            office_frame, columns=("name", "status", "url"), show="headings",
            # 列數跟上面手機版的清單一樣（4 列），兩個方框才會一樣高、看起來是成對的。
            height=4, selectmode="browse",
        )
        for key, text, width in (("name", "工地", 150), ("status", "狀態", 80), ("url", "網址", 480)):
            self.office_tree.heading(key, text=text)
            self.office_tree.column(key, width=width, anchor="w")
        self.office_tree.pack(fill="x", padx=8, pady=(8, 4))

        office_buttons = ttk.Frame(office_frame)
        office_buttons.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(office_buttons, text="開啟", command=self.open_office).pack(side="left", padx=(0, 4))
        ttk.Button(office_buttons, text="停止", command=self.stop_office).pack(side="left", padx=4)

        self.settings_frame = ttk.LabelFrame(self.root, text="工程設定")
        settings_frame = self.settings_frame
        settings_frame.pack(fill="x", **pad)
        settings_frame.columnconfigure(1, weight=1)

        ttk.Label(settings_frame, text="工程名稱：").grid(row=0, column=0, sticky="e", padx=(8, 4), pady=4)
        self.project_name_var = tk.StringVar()
        ttk.Entry(settings_frame, textvariable=self.project_name_var).grid(row=0, column=1, sticky="we", padx=4, pady=4)

        ttk.Label(settings_frame, text="承攬廠商：").grid(row=1, column=0, sticky="e", padx=(8, 4), pady=4)
        self.contractor_var = tk.StringVar()
        ttk.Entry(settings_frame, textvariable=self.contractor_var).grid(row=1, column=1, sticky="we", padx=4, pady=4)

        ttk.Label(settings_frame, text="報告標題：").grid(row=2, column=0, sticky="e", padx=(8, 4), pady=4)
        self.report_title_var = tk.StringVar()
        ttk.Entry(settings_frame, textvariable=self.report_title_var).grid(row=2, column=1, sticky="we", padx=4, pady=4)

        ttk.Button(settings_frame, text="儲存設定", command=self.save_settings).grid(
            row=0, column=2, rowspan=3, padx=8, pady=4, sticky="ns"
        )

        report_frame = ttk.LabelFrame(self.root, text="產生報告")
        report_frame.pack(fill="x", **pad)
        ttk.Label(report_frame, text="工地：").pack(side="left", padx=(8, 0), pady=8)
        self.report_site_var = tk.StringVar(value="")
        self.report_site_combo = ttk.Combobox(
            report_frame, textvariable=self.report_site_var, state="readonly", width=16
        )
        self.report_site_combo.pack(side="left", padx=(2, 10), pady=8)
        self.report_site_combo.bind("<<ComboboxSelected>>", self.on_report_site_selected)
        ttk.Label(report_frame, text="施工日期：").pack(side="left", pady=8)
        self.date_var = tk.StringVar()
        self.date_combo = ttk.Combobox(report_frame, textvariable=self.date_var, state="readonly", width=14)
        self.date_combo.pack(side="left", padx=4)
        ttk.Button(report_frame, text="重新整理", command=self.refresh_dates).pack(side="left", padx=4)
        ttk.Button(report_frame, text="📄 產生報告", command=self.generate_report_action).pack(side="left", padx=4)

        log_frame = ttk.LabelFrame(self.root, text="訊息記錄")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(log_frame, height=10, state="disabled", wrap="word")
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        scrollbar.pack(side="right", fill="y", pady=8)

        ttk.Label(
            self.root,
            text="關閉這個視窗不會停止已經啟動的伺服器；下次要停止請重新打開這個程式再按「停止」。",
            foreground="#666666", wraplength=740, justify="left",
        ).pack(fill="x", padx=12, pady=(0, 8))

    def log(self, text):
        self.ui_queue.put(("log", text))

    def _drain_queue(self):
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()
                if kind == "log":
                    ts = datetime.now().strftime("%H:%M:%S")
                    self.log_text.configure(state="normal")
                    self.log_text.insert("end", f"[{ts}] {payload}\n")
                    self.log_text.see("end")
                    self.log_text.configure(state="disabled")
                elif kind == "site_link":
                    slug, url = payload
                    self.site_links[slug] = url
                    self._link_lookups.discard(slug)
                    self.refresh_site_rows()
                elif kind == "sites_changed":
                    self.sites = utils.load_sites()
                    self.refresh_site_rows()
        except queue.Empty:
            pass
        self.root.after(200, self._drain_queue)

    # ---------- 工地清單 ----------
    def current_site(self):
        """畫面上目前選取的工地；沒選的話就用清單裡第一個。"""
        selected = self.tree.selection()
        if selected:
            site = utils.find_site(selected[0], self.sites)
            if site:
                return site
        return self.sites[0] if self.sites else None

    def on_site_selected(self, _event=None):
        site = self.current_site()
        if site:
            self.report_site_var.set(site["name"])
            self.refresh_dates()
            # 工程設定是每個工地各自一份，換工地就要重新載入，
            # 不然畫面上留著上一個工地的工程名稱，一按「儲存設定」就存到錯的工地去了。
            self.load_settings()

    def on_report_site_selected(self, _event=None):
        """從「產生報告」的下拉選單換工地，效果跟直接在上面的工地清單點選完全一樣。

        刻意讓兩邊共用同一個「目前選取的工地」，而不是各記各的：如果產生報告有自己的
        一份選擇、上面的清單又有另一份，遲早會出現「畫面上看到的是 A、產出來的是 B」，
        而且那份報告從頭到尾都長得很正常，沒有任何地方會提示你弄錯了。
        """
        name = self.report_site_var.get()
        site = next((s for s in self.sites if s.get("name") == name), None)
        if not site:
            return
        self.tree.selection_set(site["slug"])
        self.tree.see(site["slug"])
        self.on_site_selected()

    def refresh_site_rows(self):
        """更新工地清單的每一列。刻意只改內容、不整個重建，不然使用者選到一半的那一列
        會在每 2 秒的狀態更新時被清掉。"""
        existing = set(self.tree.get_children())
        wanted = []
        for site in self.sites:
            slug = site["slug"]
            wanted.append(slug)
            up = is_port_listening(int(site["port"]))
            status = "● 執行中" if up else "○ 未啟動"
            link = self.site_links.get(slug) or ("（正在取得網址…）" if up else "—")
            values = (site["name"], status, link)
            if slug in existing:
                self.tree.item(slug, values=values)
            else:
                self.tree.insert("", "end", iid=slug, values=values)
        for stale in existing - set(wanted):
            self.tree.delete(stale)

        # 讓「產生報告」的工地下拉選單跟著工地清單走（新增／移除／改名都會反映上去）。
        # 只在真的不一樣時才寫入：這個函式每 2 秒就會被狀態輪詢呼叫一次，每次都重設
        # values 會讓選單在使用者正想點的時候閃一下。
        names = [site["name"] for site in self.sites]
        if list(self.report_site_combo["values"]) != names:
            self.report_site_combo["values"] = names

        if not self.tree.selection() and wanted:
            self.tree.selection_set(wanted[0])
            self.on_site_selected()

    def _apply_site(self, site):
        """把控制台自己接下來要讀寫的資料切換到這個工地。

        報告檔名要不要帶工地名稱，跟手機標題用同一個判斷（site_display_name）：
        還沒改過名字的預設工地不帶，檔名維持原本的「查驗照片_日期.docx」。
        """
        utils.use_site(site)
        utils.SITE_NAME = utils.site_display_name(site)

    def _site_env(self, site):
        """啟動這個工地的手機版時要帶的環境變數。"""
        env = os.environ.copy()
        data_dir = utils.site_data_dir(site)
        if site["slug"] != utils.DEFAULT_SITE_SLUG:
            env["INSPECTION_SITE_DIR"] = str(data_dir)
        # 名稱只有在「已經改成真正的路段名稱」時才傳給手機版，剛安裝好還叫「主要工地」
        # 的時候不傳，手機畫面跟以前一模一樣。
        label = utils.site_display_name(site)
        if label:
            env["INSPECTION_SITE_NAME"] = label
        return env, data_dir

    def start_site(self):
        site = self.current_site()
        if not site:
            return
        port = int(site["port"])
        if is_port_listening(port):
            self.log(f"「{site['name']}」的手機版已經在執行中。")
            return

        env, data_dir = self._site_env(site)
        utils.ensure_dirs(data_dir)
        self.log(f"正在啟動「{site['name']}」的手機拍照畫面伺服器（port {port}）...")
        proc = subprocess.Popen(
            [PYTHON_EXE, "-m", "streamlit", "run", str(BASE_DIR / "mobile_app.py"),
             "--server.port", str(port), "--server.address", "0.0.0.0", "--server.headless", "true"],
            cwd=str(BASE_DIR), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=NO_WINDOW,
        )
        self.site_processes[site["slug"]] = proc
        threading.Thread(target=self._pump, args=(proc, site["name"]), daemon=True).start()
        threading.Thread(target=self._setup_tailscale, args=(site,), daemon=True).start()

    def stop_site(self):
        """只關掉這個工地的伺服器，Tailscale 的路徑設定刻意保留。

        路徑留著的話，伺服器沒開時連進來會看到 502，這是誠實的「這個工地現在沒開」；
        真的要把路徑收掉是「移除工地」的事。每次停止都去動 Tailscale 設定風險太高——
        指令下錯一個參數就可能把整台機器所有工地的連結一起關掉。
        """
        site = self.current_site()
        if not site:
            return
        port = int(site["port"])
        self.log(f"正在關閉「{site['name']}」的手機版伺服器...")
        kill_port(port)
        self.site_processes.pop(site["slug"], None)
        self.log(f"已關閉「{site['name']}」。手機網址仍然保留，下次按「啟動」就會恢復。")

    def _setup_tailscale(self, site):
        if shutil.which("tailscale") is None:
            self.log("[注意] 偵測不到 Tailscale，正在幫你打開下載頁面...")
            webbrowser.open("https://tailscale.com/download/windows")
            self.log("裝好 Tailscale 後，重新按一次「啟動」即可。")
            return

        status = subprocess.run(["tailscale", "status"], capture_output=True, creationflags=NO_WINDOW)
        if status.returncode != 0:
            self.log("第一次使用，需要先登入 Tailscale（會跳出瀏覽器視窗，登入完成即可）...")
            subprocess.run(["tailscale", "up"], creationflags=NO_WINDOW)

        port = int(site["port"])
        self.log(f"正在設定「{site['name']}」的手機遠端連結...")

        # 用 --bg：指令設定完就結束，Tailscale 自己把設定記在背景，重開機後也還在。
        # 第一個工地掛在網址根目錄（維持原本的網址不變），其他工地各自掛在 /site2、/site3
        # 這種路徑底下。Funnel 對外只開放 443／8443／10000 三個埠，用路徑才能無限增加工地，
        # 而且全部走 443，工地訊號再差的行動網路也不會因為埠號被擋而連不上。
        cmd = ["tailscale", "funnel", "--bg", "--yes"]
        if site["slug"] != utils.DEFAULT_SITE_SLUG:
            cmd.append(f"--set-path={site['url_path']}")
        cmd.append(str(port))

        result = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW)
        out = (result.stdout or b"").decode("utf-8", errors="replace").strip()
        if out:
            for line in out.splitlines():
                if line.strip():
                    self.log(f"[遠端連結] {line.strip()}")
        if result.returncode != 0:
            err = (result.stderr or b"").decode("utf-8", errors="replace").strip()
            self.log(f"[注意] 設定遠端連結失敗：{err or '請檢查 Tailscale 狀態'}")
            return

        url = tailscale_url_for_port(port)
        if url:
            self.ui_queue.put(("site_link", (site["slug"], url)))

    def _lookup_link(self, slug, port):
        """查不到就不要把 slug 從 _link_lookups 拿掉：留著代表「這一輪已經問過了」。

        拿掉的話，每 2 秒的狀態輪詢會再問一次，伺服器有開但還沒設定遠端連結時，
        就會變成無止盡地每 2 秒開一個 tailscale 行程。伺服器停掉時才會清掉這個記號
        （見 poll_status），所以重新啟動後還是會再查一次。
        """
        url = tailscale_url_for_port(port)
        if url:
            self.ui_queue.put(("site_link", (slug, url)))

    def copy_link(self):
        site = self.current_site()
        if not site:
            return
        url = self.site_links.get(site["slug"])
        if not url:
            messagebox.showinfo("還沒有網址", f"「{site['name']}」還沒啟動，或還在設定遠端連結，請稍等。")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self.log(f"已複製「{site['name']}」的網址到剪貼簿。")

    def add_site(self):
        name = simpledialog.askstring(
            "新增工地", "工地名稱（例如：光復路段）：", parent=self.root
        )
        if not name or not name.strip():
            return
        name = name.strip()
        if any(s.get("name") == name for s in self.sites):
            messagebox.showwarning("名稱重複", f"已經有一個工地叫「{name}」了，請換一個名字。")
            return

        created = {}

        def mutator(sites):
            slug = utils.next_site_slug(sites)
            port = utils.next_site_port(sites)
            created.update({
                "slug": slug,
                "name": name,
                "port": port,
                "url_path": f"/{slug}",
            })
            sites.append(dict(created))
            # 辦公室版的埠要在手機版的埠已經進清單之後才挑，才不會兩個挑到同一個號碼
            created["office_port"] = utils.next_office_port(sites)
            sites[-1]["office_port"] = created["office_port"]
            return True

        try:
            utils.update_sites(mutator)
        except Exception as e:
            messagebox.showerror("新增失敗", f"新增工地失敗：{e}")
            return

        self.sites = utils.load_sites()
        utils.ensure_dirs(utils.site_data_dir(created))
        self.refresh_site_rows()
        self.tree.selection_set(created["slug"])
        self.on_site_selected()
        self.log(f"已新增工地「{name}」（網址代號 {created['slug']}，port {created['port']}）。")

        if messagebox.askyesno("新增完成", f"已新增「{name}」。\n\n要現在啟動並取得手機網址嗎？"):
            self.start_site()

    def rename_site(self):
        """改工地名稱。網址代號（slug）刻意不跟著改：工人手機上存的書籤才不會失效。"""
        site = self.current_site()
        if not site:
            return
        current = site.get("name", "")
        new_name = simpledialog.askstring(
            "工地改名",
            "工地名稱（例如：中山路段）：\n\n"
            "手機網址不會改變，工人已經存的書籤照樣能用。\n"
            "改完之後要按「停止」再「啟動」，手機標題才會更新。",
            initialvalue=current,
            parent=self.root,
        )
        if not new_name or not new_name.strip():
            return
        new_name = new_name.strip()
        if new_name == current:
            return
        if any(s.get("name") == new_name for s in self.sites):
            messagebox.showwarning("名稱重複", f"已經有一個工地叫「{new_name}」了，請換一個名字。")
            return

        def mutator(sites):
            for s in sites:
                if s.get("slug") == site["slug"]:
                    s["name"] = new_name
                    return True
            return False

        try:
            utils.update_sites(mutator)
        except Exception as e:
            messagebox.showerror("改名失敗", f"改名失敗：{e}")
            return

        self.sites = utils.load_sites()
        self.refresh_site_rows()
        self.tree.selection_set(site["slug"])
        self.on_site_selected()
        self.log(f"已把「{current}」改名為「{new_name}」。")

        if is_port_listening(int(site["port"])):
            messagebox.showinfo(
                "改名完成",
                f"已改名為「{new_name}」。\n\n"
                "手機畫面上的標題是伺服器啟動時決定的，現在還是舊的名稱。\n"
                "請按「停止」再按「啟動」，然後在手機上重新整理一次。",
            )

    def remove_site(self):
        site = self.current_site()
        if not site:
            return
        if site["slug"] == utils.DEFAULT_SITE_SLUG:
            # 這個擋，是「刪除工地」跟「整個安裝被刪掉」之間唯一的一道防線：
            # 預設工地的資料夾就是程式所在的資料夾，照片、報告、config.json、venv 全都在裡面。
            messagebox.showwarning(
                "不能移除",
                "「主要工地」的資料夾就是程式本身所在的資料夾，移除它會把整套程式一起刪掉，"
                "所以不開放從這裡移除。\n\n如果只是想改名字，請用「改名」。",
            )
            return

        data_dir = utils.site_data_dir(site)
        photos, reports = site_data_summary(data_dir)
        if photos or reports:
            confirm_text = (
                f"確定要移除「{site['name']}」嗎？\n\n"
                f"這個工地目前有 {photos} 張照片、{reports} 份報告，會跟著一起刪掉。\n"
                f"（會移到「資源回收筒」，按錯還可以還原）\n\n"
                f"資料夾：{data_dir}"
            )
        else:
            confirm_text = (
                f"確定要移除「{site['name']}」嗎？\n\n"
                f"這個工地裡面沒有任何照片或報告，資料夾會直接移到資源回收筒。"
            )
        if not messagebox.askyesno("移除工地", confirm_text):
            return

        kill_port(int(site["port"]))
        kill_port(utils.office_port_for(site))
        try:
            subprocess.run(
                ["tailscale", "funnel", f"--set-path={site['url_path']}", "off"],
                capture_output=True, creationflags=NO_WINDOW,
            )
        except Exception as e:
            self.log(f"[注意] 收回遠端連結失敗（不影響移除）：{e}")

        # 先等伺服器真的關掉再刪：Windows 不讓你刪掉還有程式開著檔案的資料夾。
        wait_for_port_closed(int(site["port"]))

        deleted = True
        if data_dir.exists():
            last_error = None
            for attempt in range(5):
                try:
                    send_to_recycle_bin(data_dir)
                    last_error = None
                    break
                except OSError as e:
                    last_error = e
                    time.sleep(0.5)
            if last_error is not None:
                deleted = False
                self.log(f"[注意] 資料夾刪不掉：{last_error}")
                messagebox.showwarning(
                    "資料夾沒刪掉",
                    f"「{site['name']}」已經從清單移除，但資料夾刪不掉：\n{data_dir}\n\n"
                    f"原因：{last_error}\n\n"
                    "通常是還有程式開著裡面的檔案。可以稍後自己手動刪除。",
                )

        def mutator(sites):
            before = len(sites)
            sites[:] = [s for s in sites if s.get("slug") != site["slug"]]
            return len(sites) != before

        utils.update_sites(mutator)
        self.sites = utils.load_sites()
        self.site_processes.pop(site["slug"], None)
        self.office_processes.pop(site["slug"], None)
        self.site_links.pop(site["slug"], None)
        self._link_lookups.discard(site["slug"])
        self.refresh_site_rows()
        self.refresh_office_rows()
        if deleted:
            self.log(f"已移除工地「{site['name']}」，資料夾已移到資源回收筒。")

    # ---------- 狀態輪詢 ----------
    def poll_status(self):
        # 辦公室版現在一個工地一個埠，狀態直接照埠去看就好，不需要記「剛剛啟動的是哪一個」。
        # 以前那份記錄會在伺服器還在啟動、埠還沒開的那幾秒被狀態輪詢清掉，
        # 結果之後永遠顯示「不確定是哪個工地」。
        self.refresh_office_rows()

        for site in self.sites:
            slug, port = site["slug"], int(site["port"])
            if is_port_listening(port):
                if slug not in self.site_links and slug not in self._link_lookups:
                    # 伺服器在跑但這個視窗還不知道網址（例如剛重開控制台），去問 Tailscale 撿回來。
                    self._link_lookups.add(slug)
                    threading.Thread(target=self._lookup_link, args=(slug, port), daemon=True).start()
            else:
                self.site_links.pop(slug, None)
                self._link_lookups.discard(slug)

        self.refresh_site_rows()
        self.root.after(2000, self.poll_status)

    # ---------- 辦公室版 ----------
    def current_office_site(self):
        """辦公室版清單裡目前選取的工地。"""
        selected = self.office_tree.selection()
        if selected:
            site = utils.find_site(selected[0], self.sites)
            if site:
                return site
        return self.sites[0] if self.sites else None

    def refresh_office_rows(self):
        """更新辦公室版清單。只改內容不重建，不然每 2 秒的狀態更新會把選取清掉。"""
        existing = set(self.office_tree.get_children())
        wanted = []
        for site in self.sites:
            slug = site["slug"]
            wanted.append(slug)
            port = utils.office_port_for(site)
            up = is_port_listening(port)
            values = (
                site["name"],
                "● 執行中" if up else "○ 未啟動",
                f"http://localhost:{port}" if up else f"（未啟動，port {port}）",
            )
            if slug in existing:
                self.office_tree.item(slug, values=values)
            else:
                self.office_tree.insert("", "end", iid=slug, values=values)
        for stale in existing - set(wanted):
            self.office_tree.delete(stale)
        if not self.office_tree.selection() and wanted:
            self.office_tree.selection_set(wanted[0])

    def open_office(self):
        """一個按鈕做完「要開這個工地的辦公室版」這件事。

        還沒啟動就先啟動再開分頁；已經在跑就直接開分頁。分成「啟動」和「開啟畫面」兩個
        按鈕的時候，分頁關掉之後按「啟動」只會說已經在執行中而什麼都不做，等於回不去；
        而且兩個按鈕各自看不同的東西，很容易變成「選單指著 A、開出來是 B」。
        """
        site = self.current_office_site()
        if not site:
            return
        port = utils.office_port_for(site)
        url = f"http://localhost:{port}"

        if is_port_listening(port):
            self.log(f"「{site['name']}」的辦公室版已經在執行中，開啟分頁。")
            webbrowser.open(url)
            return

        env, data_dir = self._site_env(site)
        utils.ensure_dirs(data_dir)
        self.log(f"正在啟動「{site['name']}」的辦公室版（port {port}）...")
        proc = subprocess.Popen(
            [PYTHON_EXE, "-m", "streamlit", "run", str(BASE_DIR / "app.py"),
             "--server.port", str(port), "--server.headless", "true"],
            cwd=str(BASE_DIR), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=NO_WINDOW,
        )
        self.office_processes[site["slug"]] = proc
        threading.Thread(target=self._pump, args=(proc, f"辦公室版-{site['name']}"), daemon=True).start()
        self.root.after(2500, lambda: webbrowser.open(url))

    def stop_office(self):
        site = self.current_office_site()
        if not site:
            return
        port = utils.office_port_for(site)
        self.log(f"正在關閉「{site['name']}」的辦公室版...")
        kill_port(port)
        self.office_processes.pop(site["slug"], None)
        self.log(f"已關閉「{site['name']}」的辦公室版。")

    def _pump(self, process, name):
        for raw in process.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                self.log(f"[{name}] {line}")

    # ---------- 工程設定（每個工地各自一份） ----------
    def load_settings(self):
        """載入目前選取工地的工程設定。切換工地時會重新載入，所以畫面上看到的一定是那個工地的。"""
        site = self.current_site()
        if not site:
            return
        self.settings_frame.configure(text=f"工程設定（{site['name']}）")
        try:
            self._apply_site(site)
            config = utils.load_config()
        except Exception as e:
            self.log(f"[注意] 讀取設定失敗：{e}")
            return
        self.project_name_var.set(config.get("project_name", ""))
        self.contractor_var.set(config.get("contractor", ""))
        self.report_title_var.set(config.get("report_title", ""))

    def save_settings(self):
        """只存進這個工地自己的資料夾，不會動到其他工地。

        分類與常用說明清單不在這裡，那個仍然是所有工地共用的 config.json。
        """
        site = self.current_site()
        if not site:
            return
        new_project_name = self.project_name_var.get().strip()
        new_contractor = self.contractor_var.get().strip()
        new_report_title = self.report_title_var.get().strip()
        if not new_project_name or not new_contractor:
            messagebox.showwarning("請填寫完整", "工程名稱和承攬廠商不能空白。")
            return

        try:
            self._apply_site(site)
            utils.save_site_overrides({
                "project_name": new_project_name,
                "contractor": new_contractor,
                "report_title": new_report_title,
            })
        except Exception as e:
            messagebox.showerror("儲存失敗", f"儲存設定失敗：{e}")
            return
        self.log(f"已儲存「{site['name']}」的工程設定（只影響這個工地的報告頁首）。")

    # ---------- 產生報告 ----------
    def refresh_dates(self):
        site = self.current_site()
        if not site:
            return
        self._apply_site(site)
        rows = utils.load_manifest()
        dates = sorted({r["date"] for r in rows}, reverse=True)
        self.date_combo["values"] = dates
        if dates and self.date_var.get() not in dates:
            self.date_var.set(dates[0])
        if not dates:
            self.date_var.set("")

    def generate_report_action(self):
        site = self.current_site()
        if not site:
            return
        date_str = self.date_var.get()
        if not date_str:
            messagebox.showwarning(
                "請選擇日期", f"「{site['name']}」還沒有已標記完成的照片，無法產生報告。"
            )
            return
        try:
            self._apply_site(site)
            config = utils.load_config()
            rows = [r for r in utils.load_manifest() if r["date"] == date_str]
            if not rows:
                messagebox.showwarning("沒有照片", f"「{site['name']}」在 {date_str} 沒有已標記的照片。")
                return
            out_path = generate_report.build_report(date_str, config, rows)
            self.log(f"已產生報告（{site['name']}）：{out_path}")
            if messagebox.askyesno("完成", f"報告已產生：\n{out_path.name}\n\n要打開所在資料夾嗎？"):
                os.startfile(out_path.parent)
        except Exception as e:
            self.log(f"[注意] 產生報告失敗：{e}")
            messagebox.showerror("失敗", f"產生報告失敗：{e}")

    def on_close(self):
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
