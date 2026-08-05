# utils.py
# 這個檔案放共用的小工具函式，app.py 和 generate_report.py 都會用到。
# 你不需要修改這個檔案。

import contextlib
import csv
import json
import os
import re
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
import pillow_heif

# 讓 Pillow 能直接開啟 iPhone 常用的 HEIC/HEIF 照片，否則 Image.open() 遇到 .heic 檔會直接報錯。
pillow_heif.register_heif_opener()

BASE_DIR = Path(__file__).parent

# 同一天有兩個以上的工地在施工時，同一份程式可以同時服務好幾個工地：每個工地各自有一個
# 資料夾放自己的照片與紀錄，啟動時用環境變數 INSPECTION_SITE_DIR 指定是哪一個。
# 沒有設定這個環境變數時，DATA_DIR 就等於程式所在的資料夾，行為跟以前完全一樣。
#
# 為什麼一定要分開：manifest.csv 跟報告都是以「施工日期」當索引，兩個工地的照片如果混在
# 同一份資料裡，產生報告時會被當成同一個工地而合併成一份，交維照片的最低張數檢查也會把
# 兩邊的張數加在一起算（各拍 3 張會被當成 6 張通過），報告表面上看不出任何異常。
DATA_DIR = Path(os.environ["INSPECTION_SITE_DIR"]) if os.environ.get("INSPECTION_SITE_DIR") else BASE_DIR

# 這個工地在手機畫面上顯示的名字（例如「中山路段」），同樣由啟動時的環境變數指定。
# 沒設定就不顯示，畫面跟以前一樣。手機只看得到網址，畫面上不寫清楚的話，工人很容易在
# A 工地開著 B 工地的連結拍照，而且完全不會有任何地方提示他拍錯了。
SITE_NAME = os.environ.get("INSPECTION_SITE_NAME", "")

# config.json 刻意留在 BASE_DIR，不跟著 DATA_DIR 走：分類與常用說明是所有工地共用的一份，
# 這樣現場在 A 工地新增的說明，B 工地的手機也馬上看得到，不會兩邊各自長出不同的清單。
CONFIG_PATH = BASE_DIR / "config.json"

INCOMING_DIR = DATA_DIR / "incoming"
SORTED_DIR = DATA_DIR / "sorted"
OUTPUT_DIR = DATA_DIR / "output"
MANIFEST_PATH = DATA_DIR / "manifest.csv"

# 存放「不打算標記」的照片：incoming 資料夾照片很多時，可以用整理畫面把不需要的搬到這裡，
# 不會被算進「待標記」，但也不會真的刪除，之後想拿回來標記可以自己搬回 incoming。
IGNORED_DIR = DATA_DIR / "ignored"

# 存放「已經選好分類/說明，但還沒套用裁切和日期浮水印」的原始照片（一張都還沒被動過），
# 讓使用者可以在按「完成本次作業」之前，隨時回頭修改任何一張的拍照日期或裁切範圍。
STAGING_DIR = DATA_DIR / "staging"
SESSION_PENDING_PATH = DATA_DIR / "session_pending.csv"
SESSION_PENDING_FIELDS = [
    "staged_filename", "original_filename", "category", "caption",
    "date", "photo_date", "crop_left", "crop_top", "crop_width", "crop_height", "tagged_at",
]

# 注意：新增了 "photo_date"（實際拍照日期，跟 "date" 施工日期分開存）。
# 這一欄放在最後面，這樣舊的 manifest.csv（沒有這欄）還是可以正常讀取，不會壞掉。
MANIFEST_FIELDS = ["date", "category", "caption", "sorted_path", "original_filename", "tagged_at", "photo_date"]

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic"}

# 報告檔名的開頭。
REPORT_FILENAME_PREFIX = "查驗照片_"

# 報告裡照片格子的寬高（公分，來自 generate_report.py 的排版）。
# app.py 的裁切工具會鎖定同樣的比例，這樣裁切好的照片存進報告時才會剛好填滿格子，不會留白。
PHOTO_SLOT_WIDTH_CM = 7.6
PHOTO_SLOT_HEIGHT_CM = 6.3


def ensure_dirs(data_dir=None):
    """確保 incoming / sorted / output / staging / ignored 資料夾都存在。

    不指定 data_dir 就用這個行程目前的工地資料夾；控制台要幫「還沒啟動」的新工地
    先把資料夾建好時，才會另外指定。
    """
    base = DATA_DIR if data_dir is None else Path(data_dir)
    for name in ("incoming", "sorted", "output", "staging", "ignored"):
        (base / name).mkdir(parents=True, exist_ok=True)


def unique_path(directory: Path, filename: str) -> Path:
    """如果 directory/filename 已經存在，自動加上 _2、_3... 直到不衝突為止。"""
    target = directory / filename
    if not target.exists():
        return target
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 2
    while True:
        candidate = directory / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


# ---------- 檔案鎖：避免辦公室電腦跟手機（或好幾支手機）同時寫同一個檔案互相蓋掉 ----------
# config.json／session_pending.csv／manifest.csv 都是「整個檔案讀出來、改一改、整個寫回去」
# 的存法。平常只有一個人用完全沒問題，但如果兩支手機在同一秒各自新增一個新分類，或是
# 辦公室在編輯某張待確認照片的同時，手機剛好存了一張新照片進 session_pending.csv，
# 就可能發生「其中一邊的修改被另一邊覆蓋掉、憑空消失」的狀況，而且不會有任何錯誤訊息。
# 用一個 .lock 檔案的「獨佔建立」當鎖：搶得到就代表沒有人在寫，寫完馬上刪掉讓別人接手；
# 如果鎖檔案放太久沒被刪掉（例如前一個程式當掉），視為過期鎖直接接手，避免永遠卡住。
_LOCK_STALE_SECONDS = 10
_LOCK_RETRY_INTERVAL = 0.05

# os.replace 在 Windows 上，如果目標檔案剛好正在被別人開著讀（手機端在讀、或防毒軟體在掃描），
# 偶爾會丟 PermissionError。這種情況等一下就好了，所以重試幾次再放棄。
_REPLACE_RETRIES = 5


def _atomic_write_text(target_path: Path, write_fn, encoding: str = "utf-8", newline=None):
    """安全地整個覆寫一個文字檔：先寫進同資料夾的暫存檔，確定完整寫入磁碟後，
    再用 os.replace 一次把正式檔案換掉。

    為什麼一定要這樣寫：原本「open(path, 'w') 直接覆蓋」的做法，是先把檔案清空、再從頭寫入。
    如果在這中間程式當掉或停電（辦公室電腦 24 小時開著，夜間施工時段正好在寫），留下來的就是
    一個被清空或只寫到一半的檔案，裡面的東西再也救不回來——session_pending.csv 沒了，代表
    staging 裡的照片全部失去分類/說明/日期/裁切範圍，等於一整晚的標記白做；config.json 壞掉
    則是兩個程式都直接開不起來。

    os.replace 在 Windows 和 Linux 上都保證是「原子操作」：別的程式（手機端）來讀的時候，
    只會讀到「完整的舊版本」或「完整的新版本」，不可能讀到寫到一半的殘缺內容。這也順便讓
    load_config()／load_session_pending() 這些沒有上鎖的讀取變成安全的。

    write_fn: 一個函式，接受已經開好的檔案物件，把內容寫進去。
    """
    tmp_path = target_path.with_name(target_path.name + ".tmp")
    try:
        with open(tmp_path, "w", encoding=encoding, newline=newline) as f:
            write_fn(f)
            f.flush()
            os.fsync(f.fileno())  # 確保資料真的落到磁碟，不是還留在作業系統的寫入快取裡
        for attempt in range(_REPLACE_RETRIES):
            try:
                os.replace(tmp_path, target_path)
                break
            except PermissionError:
                if attempt == _REPLACE_RETRIES - 1:
                    raise
                time.sleep(_LOCK_RETRY_INTERVAL)
    except BaseException:
        # 寫暫存檔的過程中出錯：把沒寫完的暫存檔清掉，正式檔案完全沒被動過，維持原本的內容。
        tmp_path.unlink(missing_ok=True)
        raise


def _write_csv_rows(f, fieldnames, rows):
    """把 rows 依 fieldnames 寫成一份完整的 CSV（含標題列）到已經開好的檔案物件 f。"""
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)


@contextlib.contextmanager
def _file_lock(target_path: Path):
    lock_path = target_path.with_suffix(target_path.suffix + ".lock")
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except (FileExistsError, PermissionError):
            # Windows 上，搶同一個鎖檔的當下，另一個 thread/process 剛好在建立或刪除它，
            # 有時候不會是乾脆的 FileExistsError，而是 PermissionError（實測遇到過），
            # 兩種都當作「現在搶不到鎖，稍後重試」處理。
            try:
                if time.time() - lock_path.stat().st_mtime > _LOCK_STALE_SECONDS:
                    lock_path.unlink(missing_ok=True)
            except FileNotFoundError:
                pass
            time.sleep(_LOCK_RETRY_INTERVAL)
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def load_session_pending():
    """讀取這次工作階段裡「已經選好分類/說明，但還沒套用裁切和日期浮水印」的照片清單。"""
    if not SESSION_PENDING_PATH.exists():
        return []
    with open(SESSION_PENDING_PATH, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def append_session_pending(row: dict):
    """新增一筆待確認的照片紀錄。"""
    with _file_lock(SESSION_PENDING_PATH):
        file_exists = SESSION_PENDING_PATH.exists()
        with open(SESSION_PENDING_PATH, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=SESSION_PENDING_FIELDS)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)


def rewrite_session_pending(rows: list):
    """用新的 rows 整個覆蓋 session_pending.csv（用於修改某一筆的裁切/日期，或清空已完成的紀錄）。

    注意：這個函式本身不會重新讀取最新資料，只是單純整個覆蓋——如果呼叫端手上的 rows
    是稍早讀到的舊快照，中間有別人新增了新的一筆，這樣直接覆蓋就會把新的那筆蓋掉。
    需要「修改/移除特定幾筆、同時保留期間新增的其他筆」的情況，請改用
    update_session_pending_row() 或 remove_session_pending_rows()，這兩個才有處理這個問題。
    """
    with _file_lock(SESSION_PENDING_PATH):
        _atomic_write_text(
            SESSION_PENDING_PATH,
            lambda f: _write_csv_rows(f, SESSION_PENDING_FIELDS, rows),
            encoding="utf-8-sig", newline="",
        )


def update_session_pending_row(staged_filename: str, updates: dict):
    """安全地更新 session_pending.csv 裡「特定一張」照片的欄位（用 staged_filename 認）。

    在鎖保護下重新讀取最新的清單、只修改指定的那一筆，再整個寫回去，這樣即使在編輯這一筆的
    同時，手機端剛好新增了另一筆新照片，也不會被這次的寫入蓋掉。找不到那個 staged_filename
    （例如已經被「完成本次作業」處理掉了）就什麼都不做。
    """
    with _file_lock(SESSION_PENDING_PATH):
        rows = load_session_pending()
        for r in rows:
            if r["staged_filename"] == staged_filename:
                r.update(updates)
                break
        _atomic_write_text(
            SESSION_PENDING_PATH,
            lambda f: _write_csv_rows(f, SESSION_PENDING_FIELDS, rows),
            encoding="utf-8-sig", newline="",
        )


def remove_session_pending_rows(staged_filenames):
    """安全地把指定的幾筆（用 staged_filename 認）從 session_pending.csv 移除。

    在鎖保護下重新讀取最新的清單再移除，用於「完成本次作業」處理完一批照片後清掉這幾筆，
    這樣即使處理過程中手機端剛好新增了另一筆新照片，也不會被一起清掉。
    """
    with _file_lock(SESSION_PENDING_PATH):
        to_remove = set(staged_filenames)
        rows = load_session_pending()
        remaining = [r for r in rows if r["staged_filename"] not in to_remove]
        _atomic_write_text(
            SESSION_PENDING_PATH,
            lambda f: _write_csv_rows(f, SESSION_PENDING_FIELDS, remaining),
            encoding="utf-8-sig", newline="",
        )


# ---------- 每個工地自己的工程設定 ----------
# 工程名稱／承攬廠商／報告標題會印在報告頁首，不同工地可能屬於不同的工程或不同的工務段，
# 所以這三項各工地自己一份，存在自己的資料夾裡（site_config.json）。
#
# 分類與常用說明清單（categories）刻意不放進來，維持所有工地共用一份 config.json：
# 那是「這間公司怎麼拍檢查照片」的共同規則，在 A 工地新增的說明，B 工地也應該馬上看得到。
SITE_CONFIG_FILENAME = "site_config.json"
SITE_CONFIG_KEYS = ("project_name", "contractor", "report_title")


def site_config_path(data_dir=None) -> Path:
    return (DATA_DIR if data_dir is None else Path(data_dir)) / SITE_CONFIG_FILENAME


def load_site_overrides(data_dir=None) -> dict:
    """讀這個工地自己的工程設定。沒設定過就回傳空的，代表沿用 config.json 裡的值。

    檔案壞掉時回傳空的而不是報錯：頂多是報告頁首用到共用的預設值，比整個程式打不開好。
    """
    path = site_config_path(data_dir)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k in SITE_CONFIG_KEYS and v}


def save_site_overrides(values: dict, data_dir=None):
    """把這個工地的工程設定存進它自己的資料夾。空白的欄位不寫入，代表沿用共用的預設值。"""
    path = site_config_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {k: values[k] for k in SITE_CONFIG_KEYS if values.get(k)}
    with _file_lock(path):
        _atomic_write_text(
            path,
            lambda f: json.dump(clean, f, ensure_ascii=False, indent=2),
        )


def load_shared_config():
    """讀 config.json 原本的內容，不套用任何工地的個別設定。

    存回 config.json 的人（save_config／update_config）一定要用這個，不能用 load_config()：
    load_config() 回傳的是「已經套過這個工地的工程名稱／承攬廠商」的版本，拿那個存回去
    會把某一個工地的設定寫進所有工地共用的檔案裡，其他工地的報告頁首就會跟著被改掉。
    """
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_config():
    """讀取設定：共用的分類與說明清單，加上目前這個工地自己的工程名稱／承攬廠商／報告標題。"""
    config = load_shared_config()
    config.update(load_site_overrides())
    return config


def save_config(config: dict):
    """把 config 存回 config.json（在標記畫面新增分類或常用說明時使用）。

    注意：這個函式本身不會重新讀取最新資料，只是單純整個覆蓋——如果呼叫端手上的 config
    是稍早讀到的舊快照，中間有別人新增了新的分類/說明，這樣直接覆蓋就會把新的蓋掉。
    需要「新增/修改，同時保留期間別人新增的東西」的情況，請改用 update_config()。
    """
    with _file_lock(CONFIG_PATH):
        _atomic_write_text(
            CONFIG_PATH,
            lambda f: json.dump(config, f, ensure_ascii=False, indent=2),
        )


def update_config(mutator):
    """安全地修改 config.json：在鎖保護下重新讀取最新的 config、呼叫 mutator(fresh_config)
    直接在上面修改（例如新增分類、新增常用說明），有真的改到才存回去。

    這樣即使兩支手機在同一秒各自新增一個新分類，也不會有一邊的新增被另一邊蓋掉——因為
    每次呼叫都是「鎖住 → 讀最新的 → 改 → 存」，不是用呼叫端手上可能過期的舊快照去蓋。

    mutator: 一個函式，接受 fresh_config 這個 dict，直接在上面修改，回傳 True 代表有改到
    （需要存檔）、回傳 False 代表沒改到（不用存檔）。

    回傳 (fresh_config, changed)。
    """
    with _file_lock(CONFIG_PATH):
        # 一定要用 load_shared_config()：見它的說明，用 load_config() 會把某個工地的
        # 工程設定寫進所有工地共用的 config.json。
        fresh_config = load_shared_config()
        changed = mutator(fresh_config)
        if changed:
            _atomic_write_text(
                CONFIG_PATH,
                lambda f: json.dump(fresh_config, f, ensure_ascii=False, indent=2),
            )
        return fresh_config, changed


# ---------- 工地清單（同一天有兩個以上工地在施工時用） ----------
# sites.json 跟 config.json 一樣放在 BASE_DIR，是所有工地共用的一份清單，記錄每個工地叫
# 什麼名字、手機版跑在哪個埠、網址掛在哪個路徑底下。照片和 manifest 則各自分開放。
#
# 「main」是預設工地，代表本來就存在的那一個：資料直接放在程式所在的資料夾（不是 sites/
# 底下），網址是根目錄。這樣原本只有一個工地的安裝完全不用搬動任何檔案，就自動是清單裡的
# 第一個工地，多工地功能對它來說等於不存在。
SITES_PATH = BASE_DIR / "sites.json"
SITES_DIR = BASE_DIR / "sites"
DEFAULT_SITE_SLUG = "main"
# 預設工地一開始的名字。這是個佔位名稱，不是真的路段名稱——見 site_display_name()。
DEFAULT_SITE_NAME = "主要工地"
DEFAULT_SITE_PORT = 8502
_FIRST_EXTRA_SITE_PORT = 8503

# 辦公室版也是一個工地一個埠。以前只有一個固定的 8501，控制台得自己記住「現在跑的是哪個
# 工地」——結果只要記錯或忘記，畫面就會顯示錯的工地名稱，而且完全看不出來。改成一個工地
# 一個埠之後，埠號本身就是身分，不需要記，也就不可能記錯。
# 預設工地維持 8501（原本的網址不變），其他工地從 8511 開始往上找沒被用到的。
OFFICE_PORT = 8501           # 預設工地的辦公室版埠號（保留原名，舊的說明文件有提到）
DEFAULT_OFFICE_PORT = 8501
_FIRST_EXTRA_OFFICE_PORT = 8511


def default_sites():
    """還沒有 sites.json 時的預設內容：只有本來那一個工地。"""
    return [{
        "slug": DEFAULT_SITE_SLUG,
        "name": DEFAULT_SITE_NAME,
        "port": DEFAULT_SITE_PORT,
        "url_path": "/",
    }]


def site_display_name(site: dict) -> str:
    """手機畫面標題和報告檔名要用的工地名稱；還沒改過名字的預設工地回傳空字串。

    「主要工地」只是安裝時自動給的佔位名稱，不是真的路段。顯示在手機上既佔位子又沒有
    資訊，所以在改成真正的路段名稱（例如「中山路段」）之前都不顯示。改過之後就一定會
    顯示，不管系統裡總共有幾個工地——工人看的是自己手上那支手機的標題，跟總共開了幾個
    工地無關。
    """
    name = site.get("name", "")
    return "" if name == DEFAULT_SITE_NAME else name


def load_sites():
    """讀取 sites.json，回傳工地清單。檔案不存在或壞掉時回傳預設清單，不會直接報錯——
    工地清單壞掉不應該讓整個控制台開不起來，最差的情況也還能操作原本那個工地。"""
    if not SITES_PATH.exists():
        return default_sites()
    try:
        with open(SITES_PATH, "r", encoding="utf-8") as f:
            sites = json.load(f).get("sites", [])
    except (OSError, ValueError):
        return default_sites()
    return sites or default_sites()


def update_sites(mutator):
    """安全地修改 sites.json（鎖住 → 讀最新的 → 改 → 存），用法跟 update_config 一樣。

    回傳 (sites, changed)。
    """
    with _file_lock(SITES_PATH):
        sites = load_sites()
        changed = mutator(sites)
        if changed:
            _atomic_write_text(
                SITES_PATH,
                lambda f: json.dump({"sites": sites}, f, ensure_ascii=False, indent=2),
            )
        return sites, changed


def site_data_dir(site: dict) -> Path:
    """這個工地的照片與紀錄放在哪個資料夾。預設工地就是程式所在的資料夾。"""
    if site.get("slug") == DEFAULT_SITE_SLUG:
        return BASE_DIR
    return SITES_DIR / site["slug"]


def find_site(slug: str, sites=None):
    """依代號找出工地設定，找不到回傳 None。"""
    for s in (load_sites() if sites is None else sites):
        if s.get("slug") == slug:
            return s
    return None


def next_site_slug(sites) -> str:
    """新工地的網址代號一律自動產生成 site2、site3……

    刻意不從工地名稱轉：名稱是中文（例如「光復路段」），放進網址會變成一長串百分號編碼，
    既不好記也不好貼；而且名稱之後可能會改，改了網址就變了，工人手機上存的書籤會失效。
    代號是給機器用的，畫面上和手機上顯示的一律是中文名稱。
    """
    used = {s.get("slug") for s in sites}
    n = 2
    while f"site{n}" in used:
        n += 1
    return f"site{n}"


def _used_ports(sites) -> set:
    """目前工地清單裡已經占用的所有埠（手機版和辦公室版都算）。"""
    used = {DEFAULT_OFFICE_PORT, DEFAULT_SITE_PORT}
    for s in sites:
        for key in ("port", "office_port"):
            try:
                used.add(int(s.get(key)))
            except (TypeError, ValueError):
                continue
    return used


def next_site_port(sites) -> int:
    """挑一個還沒被用掉的手機版埠。"""
    used = _used_ports(sites)
    port = _FIRST_EXTRA_SITE_PORT
    while port in used:
        port += 1
    return port


def next_office_port(sites) -> int:
    """挑一個還沒被用掉的辦公室版埠。"""
    used = _used_ports(sites)
    port = _FIRST_EXTRA_OFFICE_PORT
    while port in used:
        port += 1
    return port


def office_port_for(site: dict) -> int:
    """這個工地的辦公室版跑在哪個埠。預設工地永遠是 8501，網址跟以前一樣。"""
    if site.get("slug") == DEFAULT_SITE_SLUG:
        return DEFAULT_OFFICE_PORT
    try:
        return int(site["office_port"])
    except (KeyError, TypeError, ValueError):
        return DEFAULT_OFFICE_PORT


def ensure_office_ports():
    """幫還沒有 office_port 的工地補上一個。

    這一欄是後來才加的，之前建立的工地（還有 sites.json 不存在時的預設清單）都沒有。
    沒補的話 office_port_for 會全部退回 8501，兩個工地的辦公室版就會搶同一個埠。
    """
    def mutator(sites):
        changed = False
        for site in sites:
            if site.get("slug") == DEFAULT_SITE_SLUG:
                if site.get("office_port") != DEFAULT_OFFICE_PORT:
                    site["office_port"] = DEFAULT_OFFICE_PORT
                    changed = True
            elif not site.get("office_port"):
                site["office_port"] = next_office_port(sites)
                changed = True
        return changed

    return update_sites(mutator)


def use_site(site: dict):
    """把這個行程接下來要讀寫的工地資料夾切換成指定的工地。

    只有控制台會呼叫：控制台是一支長時間開著的程式，要輪流看不同工地的 manifest、
    產生不同工地的報告，沒辦法像 app.py／mobile_app.py 那樣在啟動時用環境變數決定一次。

    app.py 和 mobile_app.py 一律不要呼叫這個函式：那兩支是「一個行程只服務一個工地」，
    啟動時就固定下來、中途不會變。如果讓網頁程式中途切換工地，兩個瀏覽器分頁會共用同一個
    行程的全域變數，A 分頁切到 B 工地會讓還開著 A 工地的分頁在不知不覺中存到 B 工地去。
    """
    global DATA_DIR, SITE_NAME, INCOMING_DIR, SORTED_DIR, OUTPUT_DIR
    global MANIFEST_PATH, IGNORED_DIR, STAGING_DIR, SESSION_PENDING_PATH
    DATA_DIR = site_data_dir(site)
    SITE_NAME = site.get("name", "")
    INCOMING_DIR = DATA_DIR / "incoming"
    SORTED_DIR = DATA_DIR / "sorted"
    OUTPUT_DIR = DATA_DIR / "output"
    MANIFEST_PATH = DATA_DIR / "manifest.csv"
    IGNORED_DIR = DATA_DIR / "ignored"
    STAGING_DIR = DATA_DIR / "staging"
    SESSION_PENDING_PATH = DATA_DIR / "session_pending.csv"


def caption_counts(rows, category_name: str, date_str: str):
    """算出某個分類在某個施工日期，每一種「說明文字」各拍了幾張，回傳 Counter。

    重複判定就是看這個：同一個施工日期、同一個分類、一模一樣的說明文字有 2 張以上，
    才算重複。刻意用「完整的說明文字」比對，而不是比對它來自清單裡的哪一個模板：
    「AC刨除厚度5cm」跟「AC刨除厚度7cm」是兩個不同的量測點，材料別不同（DGAC／PAC）
    也是不同的東西，這些都不該被當成重複，否則現場很快就會學會忽略這個提醒。

    rows 請把 manifest 和 session_pending 兩邊都傳進來：還沒按「完成本次作業」的照片
    也要算，不然標記到一半時看起來會像什麼都還沒拍。
    """
    return Counter(
        r["caption"] for r in rows
        if r.get("category") == category_name and r.get("date") == date_str
    )


def load_manifest():
    """讀取 manifest.csv，回傳一個 list of dict。如果檔案還不存在，回傳空 list。"""
    if not MANIFEST_PATH.exists():
        return []
    with open(MANIFEST_PATH, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def append_manifest(row: dict):
    """把一筆照片紀錄加進 manifest.csv 最後面。"""
    with _file_lock(MANIFEST_PATH):
        file_exists = MANIFEST_PATH.exists()
        needs_newline_first = False
        if file_exists:
            with open(MANIFEST_PATH, "rb") as f:
                f.seek(0, os.SEEK_END)
                if f.tell() > 0:
                    f.seek(-1, os.SEEK_END)
                    needs_newline_first = f.read(1) not in (b"\n", b"\r")

        with open(MANIFEST_PATH, "a", encoding="utf-8-sig", newline="") as f:
            if needs_newline_first:
                # 檔案最後一行沒有換行符號（例如被其他程式改過），
                # 直接接著寫會跟前一行黏在一起，先補一個換行避免資料錯位。
                f.write("\n")
            writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)


def rewrite_manifest(rows: list):
    """用新的 rows 整個覆蓋 manifest.csv（用於「復原上一步」）。"""
    with _file_lock(MANIFEST_PATH):
        _atomic_write_text(
            MANIFEST_PATH,
            lambda f: _write_csv_rows(f, MANIFEST_FIELDS, rows),
            encoding="utf-8-sig", newline="",
        )


def list_incoming_photos():
    """列出 incoming 資料夾裡還沒被分類的照片，依拍攝時間排序（沒有拍攝時間就用檔名排序）。"""
    files = [
        p for p in INCOMING_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    ]

    def sort_key(p: Path):
        dt = get_exif_datetime(p)
        return (dt is None, dt or datetime.max, p.name)

    files.sort(key=sort_key)
    return files


def get_exif_datetime(path: Path):
    """嘗試讀取照片的 EXIF 拍攝時間，讀不到就回傳 None。

    用 getexif()/get_ifd() 這組新版 API，而不是舊版的 _getexif()，
    因為 HEIC（iPhone 常用格式）的圖片物件沒有 _getexif() 這個方法。
    """
    try:
        img = Image.open(path)
        exif = img.getexif()
        if not exif:
            return None
        exif_ifd = exif.get_ifd(0x8769)  # Exif SubIFD，DateTimeOriginal 在這裡面
        value = exif_ifd.get(36867)  # 36867 = ExifTags.Base.DateTimeOriginal
        if not value:
            return None
        return datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
    except Exception:
        return None
    return None


def safe_filename(text: str) -> str:
    """把說明文字轉成安全的檔名（去掉不能用在檔名的符號）。"""
    text = text.strip()
    text = re.sub(r'[\\/:*?"<>|]', "", text)
    return text or "photo"


def get_best_guess_date(path: Path):
    """猜測照片的拍攝日期。
    優先用照片的 EXIF 拍攝時間（例如手機相機拍的照片通常都有）。
    如果照片沒有 EXIF 資料（例如螢幕截圖、LINE 下載的圖片常常沒有），
    就用檔案的修改時間當作備用猜測，並回傳 confident=False，
    代表這個日期不一定準確，畫面上會提醒使用者要自己確認。

    回傳: (猜測的日期, confident: bool)
    """
    exif_dt = get_exif_datetime(path)
    if exif_dt:
        return exif_dt.date(), True
    try:
        mtime = os.path.getmtime(path)
        return datetime.fromtimestamp(mtime).date(), False
    except Exception:
        return datetime.now().date(), False


def sorted_dir_for(date_str: str, category: str) -> Path:
    return SORTED_DIR / date_str / category


def display_name(category: dict) -> str:
    """分類在 UI 選單跟報告標題上要顯示的名稱。

    大部分分類就是它自己的 name。但像「鋪築施工照片」實際上在 config.json 裡是
    兩個獨立項目（鋪築施工照片01／02，各自帶不同的說明清單），這樣報告產生時才能各自
    分頁；這種情況底層項目會多帶一個 display_name，UI 選單跟報告標題都只顯示這個名稱，
    使用者完全看不到 01／02 的差異。
    """
    return category.get("display_name", category["name"])


# ---------- 說明文字模板（材料別 / 標線種類 / 需填入數值） ----------

def render_caption(caption, selections: dict):
    """把一個 caption（純字串或模板物件）轉成畫面上要顯示的樣子。

    selections 可能包含 {"material": "DGAC"} 或 {"type": "熱聚酯標線"}，
    分別對應模板裡的 {material} / {type} 佔位字。{value} 佔位字（需填入的 cm 數字）
    在這一步先不代換：下拉選單裡只顯示簡短的 label（例如「標線長度」），
    等使用者在旁邊的輸入框填了數字後，才用 apply_value 把數字接回完整的模板文字。

    回傳 dict：
      - display：下拉選單裡顯示的文字（needs_value 的話是簡短 label，否則是代換好的完整文字）
      - raw：原始 caption
      - needs_value：bool
      - value_label：輸入框旁的簡短說明文字
      - template_filled：{material}/{type} 已代換、但 {value} 仍保留佔位字的完整模板文字，
        給 apply_value 用來組出最終存檔的說明文字
    如果這個 caption 因為 only_type 不符合目前選擇而不該出現，回傳 None。
    """
    if isinstance(caption, str):
        return {
            "display": caption,
            "raw": caption,
            "needs_value": False,
            "value_label": None,
            "template_filled": caption,
        }

    only_type = caption.get("only_type")
    if only_type and selections.get("type") != only_type:
        return None

    text = caption["template"]
    if caption.get("material"):
        text = text.replace("{material}", selections.get("material", ""))
    if caption.get("type"):
        text = text.replace("{type}", selections.get("type", ""))

    needs_value = "{value}" in text
    label = caption.get("label")
    return {
        "display": label if (needs_value and label) else text,
        "raw": caption,
        "needs_value": needs_value,
        "value_label": label,
        "template_filled": text,
    }


def apply_value(rendered: dict, value: str) -> str:
    """把使用者填入的數字代進 rendered['template_filled'] 裡的 {value} 佔位字，回傳最終存檔用的說明文字。"""
    return rendered["template_filled"].replace("{value}", value)


def caption_slot_index(caption_text: str, category: dict):
    """找出 caption_text（manifest.csv 裡存的最終說明文字）對應到 category['captions'] 清單裡第幾個項目（0-based）。

    用途：報告產生時，同一分類底下的照片要依照 config.json 設定的說明順序排列，
    而不是依照使用者標記的先後順序，所以需要反查每張照片的說明文字原本是清單裡的哪一項。
    找不到（例如使用者自行輸入的自訂說明）就回傳 None，排序時會被放到最後面。
    """
    material_options = category.get("material_options") or [None]
    type_options = category.get("type_options") or [None]

    for idx, c in enumerate(category.get("captions", [])):
        if isinstance(c, str):
            if c == caption_text:
                return idx
            continue

        for material in material_options:
            for type_ in type_options:
                selections = {}
                if material is not None:
                    selections["material"] = material
                if type_ is not None:
                    selections["type"] = type_
                rendered = render_caption(c, selections)
                if rendered is None:
                    continue
                if rendered["needs_value"]:
                    prefix, _, suffix = rendered["template_filled"].partition("{value}")
                    if caption_text.startswith(prefix) and caption_text.endswith(suffix):
                        return idx
                elif rendered["display"] == caption_text:
                    return idx
    return None


def match_caption_selection(caption_text: str, category: dict):
    """反查 caption_text 是從 category 底下哪一個 caption 模板、用什麼材料別/標線種類/數值產生的。

    用途：修改一張已經標記過的照片時，要讓「照片說明」的下拉選單/材料別/數值輸入框
    還原成當初選的樣子，而不是每次都跳回清單第一項。
    找不到就回傳 None（例如使用者自行輸入的自訂說明），這種情況畫面上要退回自由輸入模式。
    """
    material_options = category.get("material_options") or [None]
    type_options = category.get("type_options") or [None]

    for c in category.get("captions", []):
        if isinstance(c, str):
            if c == caption_text:
                return {"caption": c, "material": None, "type": None, "value": None}
            continue

        for material in material_options:
            for type_ in type_options:
                selections = {}
                if material is not None:
                    selections["material"] = material
                if type_ is not None:
                    selections["type"] = type_
                rendered = render_caption(c, selections)
                if rendered is None:
                    continue
                if rendered["needs_value"]:
                    prefix, _, suffix = rendered["template_filled"].partition("{value}")
                    if caption_text.startswith(prefix) and caption_text.endswith(suffix):
                        value = caption_text[len(prefix): len(caption_text) - len(suffix)]
                        return {"caption": c, "material": material, "type": type_, "value": value}
                elif rendered["display"] == caption_text:
                    return {"caption": c, "material": material, "type": type_, "value": None}
    return None


# ---------- 日期浮水印 ----------

# 依序嘗試這些字型檔案，找到第一個存在的就用；都找不到的話就用 Pillow 內建的預設字型。
_STAMP_FONT_CANDIDATES = [
    "C:/Windows/Fonts/consola.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/msjhbd.ttc",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _get_stamp_font(size: int):
    for path in _STAMP_FONT_CANDIDATES:
        try:
            if Path(path).exists():
                return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)  # 較新版本的 Pillow 才支援 size 參數
    except TypeError:
        return ImageFont.load_default()


def apply_date_stamp(img: Image.Image, date_str: str) -> Image.Image:
    """在照片右下角燒錄一個日期浮水印（模擬傳統相機的日期戳記）。

    date_str 格式為 "YYYY-MM-DD"，例如 "2026-07-02"。
    這裡蓋上去的是「拍照日期」，不是「施工日期」，兩者可能不一樣。
    """
    img = ImageOps.exif_transpose(img)  # 先依照 EXIF 方向校正，避免照片被誤轉向
    img = img.convert("RGB")

    # 如果裁切範圍選得很小，照片本身的像素就很少，字級（照片高度的固定比例）算出來
    # 也會跟著小到只剩幾個像素，蓋出來的文字會糊掉。這裡先把過小的照片放大到至少一個
    # 底線解析度（報告照片格用 300 DPI 換算），確保無論裁切多小，文字都還有足夠的像素
    # 可以畫得清楚；照片內容本身解析度不夠的話還是會模糊，這是放大不可避免的副作用。
    w, h = img.size
    min_h = round(PHOTO_SLOT_HEIGHT_CM / 2.54 * 300)
    if h < min_h:
        scale = min_h / h
        img = img.resize((round(w * scale), min_h), Image.LANCZOS)

    display_text = date_str.replace("-", "/")

    w, h = img.size
    # 字級固定用照片高度的比例算，不設下限，這樣不管原始照片解析度多少，
    # 裁切比例都鎖定跟報告照片格一樣，蓋進報告後每張照片的浮水印字級才會一樣大。
    # （如果設下限，解析度低的照片反而會被拉到比例外，蓋出來的字看起來比別張大。）
    font_size = max(1, round(h * 0.035))
    font = _get_stamp_font(font_size)

    measure_draw = ImageDraw.Draw(img)
    bbox = measure_draw.textbbox((0, 0), display_text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    margin = int(h * 0.02)
    x = w - text_w - margin
    y = h - text_h - margin

    final_draw = ImageDraw.Draw(img)
    final_draw.text((x - bbox[0], y - bbox[1]), display_text, font=font, fill=(255, 255, 255))
    return img


def save_stamped_image(img: Image.Image, dest_path: Path, date_str: str):
    """把已經在記憶體裡的照片（例如裁切過的）蓋上 date_str 的日期浮水印，存到 dest_path。"""
    stamped = apply_date_stamp(img, date_str)
    save_kwargs = {}
    if dest_path.suffix.lower() in (".jpg", ".jpeg"):
        save_kwargs["quality"] = 92
    stamped.save(dest_path, **save_kwargs)


def save_stamped_photo(src_path: Path, dest_path: Path, date_str: str):
    """讀取 src_path 的照片，蓋上 date_str 的日期浮水印，存到 dest_path。"""
    with Image.open(src_path) as img:
        save_stamped_image(img, dest_path, date_str)
