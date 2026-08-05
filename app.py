# app.py
# 這是「照片標記工具」。執行方式（在 VS Code 的終端機輸入）：
#     streamlit run app.py
# 它會自動在瀏覽器打開一個網頁畫面。
#
# 使用方式：
# 1. 把今天拍的照片放進 incoming 資料夾（例如你的雲端同步資料夾可以直接設成這個路徑，
#    或是你手動把照片複製過來）。
# 2. 打開這個網頁，畫面會一次顯示一張還沒分類的照片。
# 3. 確認/修改「拍照日期」（會蓋在照片右下角當浮水印）跟「施工日期」
#    （用來決定報告分類，如果是隔天才補拍的檢查照片，兩者可以不一樣）。
# 4. 選分類、選（或輸入）說明文字，按「儲存並下一張」。
# 5. 這時候還不會蓋日期浮水印，照片只是先記錄起來（側邊欄「本次工作階段」可以看到），
#    按下去之前都能回頭修改分類、說明、裁切範圍或日期。全部確認沒問題後，按側邊欄的
#    「完成本次作業」，才會一次把裁切和日期浮水印套用到全部照片、搬進 sorted 資料夾。
# 6. 全部標記完後，執行 generate_report.py 產生 Word 報告。

import base64
import io
import shutil
from collections import Counter
from datetime import datetime

import streamlit as st
from PIL import Image, ImageOps
from streamlit_cropper import st_cropper

import generate_report
import utils

# 裁切工具鎖定的比例，跟報告裡照片格子的寬高比一致（見 utils.PHOTO_SLOT_WIDTH_CM/HEIGHT_CM），
# 這樣裁切好存檔的照片，貼進報告時會剛好填滿格子，不會有留白或被硬擠壓變形。
CROP_ASPECT_RATIO = (utils.PHOTO_SLOT_WIDTH_CM, utils.PHOTO_SLOT_HEIGHT_CM)

# 裁切工具在畫面上顯示的最大尺寸（像素）。st_cropper 內建的縮圖尺寸固定是 700×700，而且它畫出來
# 的畫布是固定像素、不會跟著欄位寬度縮放：手機拍的直式照片會被畫成 525×700，比左邊這一欄還寬、
# 也比瀏覽器視窗還高，於是照片右邊被切掉、整張看不完（看起來就像被放大成一條直的）。
# 所以這裡改成自己先把照片縮到「確定塞得下」的尺寸再交給它，座標再自己換算回原圖像素。
# 螢幕更大想把裁切工具放大的話，這兩個數字可以往上調，但寬度一定要比左邊那一欄窄，
# 不然照片又會被切掉（欄寬約是「視窗寬度－側邊欄」的 5/9）。
CROP_DISPLAY_MAX_W = 480
CROP_DISPLAY_MAX_H = 420

NEW_CATEGORY_OPTION = "➕ 新增分類..."
NEW_CAPTION_OPTION = " ➕自行輸入新的說明..."

BULK_PICKER_PAGE_SIZE = 24

# 施工總覽裡「重複照片」一列固定放幾張（張數比較少時右邊留空，不要把圖磚放大）。
DUPLICATE_PHOTO_COLS = 3


def _render_crop_tool(img: Image.Image, key: str, default_coords: tuple | None = None) -> dict:
    """顯示裁切工具，回傳裁切框 {left, top, width, height}。
    回傳值和 default_coords（(左, 右, 上, 下)）用的都是「原圖像素」座標，
    不是畫面上那張縮圖的座標。"""
    scale = min(CROP_DISPLAY_MAX_W / img.width, CROP_DISPLAY_MAX_H / img.height, 1.0)
    display_img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))))

    display_coords = None
    if default_coords is not None:
        xl, xr, yt, yb = (round(c * scale) for c in default_coords)
        display_coords = (
            min(max(xl, 0), display_img.width),
            min(max(xr, 0), display_img.width),
            min(max(yt, 0), display_img.height),
            min(max(yb, 0), display_img.height),
        )

    rect = st_cropper(
        display_img,
        aspect_ratio=CROP_ASPECT_RATIO,
        box_color="#FF4B4B",
        return_type="box",
        default_coords=display_coords,
        # 上面已經自己縮好了，不要讓它再縮一次（它自己縮的話尺寸就固定是 700×700，改不掉）。
        should_resize_image=False,
        key=key,
    )

    # 換算回原圖像素。裁切框的紅色邊框本身有粗細，回傳的框會比實際看到的框大一點點，也可能
    # 稍微超出照片邊界，所以一律夾在照片範圍內；最後再依鎖定的比例把高度重算一次，確保存進
    # session_pending.csv 的裁切範圍跟報告照片格的比例完全一致，貼進報告不會被擠壓變形。
    left = min(max(round(rect["left"] / scale), 0), img.width - 1)
    top = min(max(round(rect["top"] / scale), 0), img.height - 1)
    width = min(round(rect["width"] / scale), img.width - left)
    height = min(round(width * CROP_ASPECT_RATIO[1] / CROP_ASPECT_RATIO[0]), img.height - top)
    width = min(round(height * CROP_ASPECT_RATIO[0] / CROP_ASPECT_RATIO[1]), img.width - left)
    return {"left": left, "top": top, "width": width, "height": height}


# 預覽圖一律做成同樣大小的正方形圖磚。照片本身有直式有橫式、長寬比也不一樣，如果照原樣
# 縮圖再交給 st.image(use_container_width=True)，每一張會被拉成不同的高度，整排看起來高高低低
# 又胖瘦不一。這裡改成把照片「完整縮進」一個正方形畫布、四周補上淺灰底，不是把邊緣裁掉：
# 挑要忽略的照片、比對是不是拍重複時，都要看得到整張才判斷得準，不能為了畫面整齊藏掉內容。
THUMBNAIL_TILE_PX = 200
# 實際編碼出來的縮圖比顯示框大一點，高解析度螢幕上才不會糊掉。
THUMBNAIL_ENCODE_PX = 400


@st.cache_data(show_spinner=False)
def _load_thumbnail(photo_path_str: str, mtime: float) -> bytes:
    """產生預覽圖（給整理 incoming 和比對重複照片的畫面用），用檔案路徑+修改時間當快取 key，
    這樣同一批照片重複整理時不用每次都重新解碼一次（HEIC 解碼比較慢）。"""
    with Image.open(photo_path_str) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((THUMBNAIL_ENCODE_PX, THUMBNAIL_ENCODE_PX), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return buf.getvalue()


def _render_thumbnail(photo_path):
    """把一張照片畫成固定大小的預覽方框：每一格的寬高都是 THUMBNAIL_TILE_PX，照片維持原本的
    長寬比、完整置中放進框裡（不裁切），所以直式橫式、大張小張佔的位置都一樣，
    下面的檔名和按鈕也會排在同一條線上。
    框裡多出來的空白直接露出網頁本來的背景色（沒有自己填色），淺色和深色佈景主題都不會突兀。"""
    thumb_b64 = base64.b64encode(
        _load_thumbnail(str(photo_path), photo_path.stat().st_mtime)
    ).decode("ascii")
    st.markdown(
        f"<div style='width:{THUMBNAIL_TILE_PX}px;height:{THUMBNAIL_TILE_PX}px;"
        f"display:flex;align-items:center;justify-content:center'>"
        f"<img src='data:image/jpeg;base64,{thumb_b64}' "
        f"style='max-width:100%;max-height:100%;object-fit:contain'></div>",
        unsafe_allow_html=True,
    )


def _material_preview_html(text: str, material_options: list) -> str | None:
    """如果 text 裡含有材料代號（DGAC/OGAC/PAC），回傳把代號標紅的 HTML；沒有的話回傳 None。"""
    if not material_options or not any(token in text for token in material_options):
        return None
    preview = text
    for token in material_options:
        preview = preview.replace(token, f"<span style='color:red;font-weight:bold'>{token}</span>")
    return preview


def _used_caption_indices(entry, rows, date_str):
    """算出這個分類（entry）在這個施工日期，常用說明清單（entry['captions']）裡哪些項目
    已經至少用過一次（不論材料別/標線種類/填入的數值是哪個組合），回傳對應的 index 集合，
    用來在checklist畫勾勾。自訂/自由輸入的說明不算在清單裡，找不到對應項目就略過。"""
    used = set()
    captions_list = entry.get("captions", [])
    for r in rows:
        if r["category"] != entry["name"] or r["date"] != date_str:
            continue
        match = utils.match_caption_selection(r["caption"], entry)
        if match is None:
            continue
        try:
            used.add(captions_list.index(match["caption"]))
        except ValueError:
            continue
    return used


def _render_caption_checklist(matching_entries, selections, all_rows, date_str, key_prefix=""):
    """顯示這個分類在這個施工日期，常用說明清單裡哪些已經拍過、哪些還沒——只顯示目前
    材料別/標線種類選擇下會出現的項目，跟照片說明下拉選單看到的清單一致。"""
    if not matching_entries or not date_str:
        return
    lines = []
    for entry in matching_entries:
        used_indices = _used_caption_indices(entry, all_rows, date_str)
        for i, c in enumerate(entry.get("captions", [])):
            rendered_c = utils.render_caption(c, selections)
            if rendered_c is None:
                continue
            label = rendered_c["value_label"] if rendered_c["needs_value"] else rendered_c["display"]
            mark = "✅" if i in used_indices else "⬜"
            lines.append(f"- {mark} {label}")
    if not lines:
        return
    # 不用 st.expander：它內建的展開箭頭圖示要另外載入字型，訊號不穩時常常字型載入失敗，
    # 會直接顯示圖示的英文原始碼名稱而不是箭頭圖案。改用純文字按鈕手動切換顯示/隱藏，
    # 箭頭符號直接用純文字符號（▼／▶），不用另外載入字型。
    toggle_key = f"show_caption_checklist_{key_prefix}"
    if toggle_key not in st.session_state:
        st.session_state[toggle_key] = False
    arrow = "▼" if st.session_state[toggle_key] else "▶"
    if st.button(f"{arrow} 📋 分類清單", key=f"toggle_{toggle_key}", use_container_width=True):
        st.session_state[toggle_key] = not st.session_state[toggle_key]
    if st.session_state[toggle_key]:
        st.markdown("\n".join(lines))


# ---------- 施工總覽：產生報告前，一次看完當天所有分類拍了什麼、漏了什麼、有沒有拍重複 ----------

def _photo_path_for(row, source):
    """這一筆紀錄對應到的照片檔案在哪裡。"""
    if source == "pending":
        return utils.STAGING_DIR / row["staged_filename"]
    return utils.DATA_DIR / row["sorted_path"]


def _day_selections(entries, group_rows):
    """猜這個分類當天用的材料別／標線種類，用來把「還沒拍」的項目顯示成看得懂的完整文字。

    清單裡有些說明是模板（例如「瀝青混凝土({material})鋪設」），沒有材料別就組不出完整
    句子。這裡直接看當天已經拍的照片實際用的是哪一種，取最常出現的那個；當天還完全沒拍
    的話才退回用清單裡的第一個選項。
    """
    materials, types = Counter(), Counter()
    for row, _source in group_rows:
        entry = next((e for e in entries if e["name"] == row.get("category")), None)
        if entry is None:
            continue
        match = utils.match_caption_selection(row.get("caption", ""), entry)
        if not match:
            continue
        if match.get("material"):
            materials[match["material"]] += 1
        if match.get("type"):
            types[match["type"]] += 1

    selections = {}
    material_options = next((e["material_options"] for e in entries if e.get("material_options")), None)
    type_options = next((e["type_options"] for e in entries if e.get("type_options")), None)
    if material_options:
        selections["material"] = materials.most_common(1)[0][0] if materials else material_options[0]
    if type_options:
        selections["type"] = types.most_common(1)[0][0] if types else type_options[0]
    return selections


def _analyze_day(config, manifest_rows, session_pending_rows, date_str):
    """把某個施工日期的照片整理成「一個分類一組」的結構，順便算出重複與還沒拍的項目。

    側邊欄的提醒數字和總覽面板都用這同一份結果，兩邊的數字才不會對不起來。

    manifest 和 session_pending 兩邊都要算進來：還沒按「完成本次作業」的照片也是今天拍的，
    只看 manifest 的話，標記到一半時整個畫面會像什麼都還沒拍。但兩邊要分辨得出來，因為
    要移掉一張時的處理方式不一樣——待確認的還在 staging，已套用的還要一起改 manifest。
    """
    rows_for_date = [(r, "manifest") for r in manifest_rows if r.get("date") == date_str]
    rows_for_date += [(r, "pending") for r in session_pending_rows if r.get("date") == date_str]

    groups = []
    seen_display_names = set()
    for cat in config["categories"]:
        display = utils.display_name(cat)
        if display in seen_display_names:
            continue
        seen_display_names.add(display)

        entries = [c for c in config["categories"] if utils.display_name(c) == display]
        entry_names = {e["name"] for e in entries}
        group_rows = [(r, s) for r, s in rows_for_date if r.get("category") in entry_names]
        if not group_rows and not entries:
            continue

        counts = Counter(r.get("caption") for r, _s in group_rows)
        photos_by_caption = {}
        for row, source in group_rows:
            photos_by_caption.setdefault(row.get("caption"), []).append((row, source))

        min_required = next((e["min_required"] for e in entries if e.get("min_required")), None)

        # 每一段說明文字原本是清單裡的第幾項：用來照 config.json 的順序排，跟報告一致。
        slot_of = {}
        used_slots = set()
        for caption in counts:
            slot = None
            for entry in entries:
                slot = utils.caption_slot_index(caption, entry)
                if slot is not None:
                    used_slots.add((entry["name"], slot))
                    break
            slot_of[caption] = slot

        shot = sorted(
            ({"caption": c, "count": counts[c], "slot": slot_of[c],
              "photos": photos_by_caption.get(c, [])} for c in counts if slot_of[c] is not None),
            key=lambda item: (item["slot"], item["caption"]),
        )
        # 現場自己打的說明對不到清單，單獨放一區。目前的分類清單完全看不到這種，
        # 打錯字打出來的近似重複（「掃車清潔」對「掃車清潔作業」）也是藏在這裡。
        extras = sorted(
            ({"caption": c, "count": counts[c], "slot": None,
              "photos": photos_by_caption.get(c, [])} for c in counts if slot_of[c] is None),
            key=lambda item: item["caption"],
        )

        selections = _day_selections(entries, group_rows)
        missing = []
        for entry in entries:
            for idx, raw_caption in enumerate(entry.get("captions", [])):
                if (entry["name"], idx) in used_slots:
                    continue
                rendered = utils.render_caption(raw_caption, selections)
                if rendered is None:
                    continue
                missing.append(
                    rendered["value_label"] if rendered["needs_value"] else rendered["display"]
                )

        # 同一天做了兩個路段時，這個分類幾乎每一項都會剛好兩張。那不是拍錯，是做了兩趟，
        # 逐項標紅只會變成十幾條一模一樣的警告，現場很快就會學會整片忽略。這種情況改成
        # 在分類標題下面講一句就好。判斷條件刻意抓寬鬆一點：寧可少提醒，也不要狼來了。
        paired = [item for item in shot if item["count"] >= 2]
        repeat_pattern = len(shot) >= 4 and len(paired) >= len(shot) * 0.6

        # 有設定最低張數的分類（例如交維照片）本來就要同一項拍很多張，完全不檢查重複。
        if min_required or repeat_pattern:
            duplicates = []
        else:
            duplicates = [item["caption"] for item in shot + extras if item["count"] >= 2]

        groups.append({
            "display_name": display,
            "entries": entries,
            "rows": group_rows,
            "shot": shot,
            "extras": extras,
            "missing": missing,
            "duplicates": duplicates,
            "min_required": min_required,
            "repeat_pattern": repeat_pattern,
        })

    total_photos = len(rows_for_date)
    pending_photos = sum(1 for _r, s in rows_for_date if s == "pending")
    total_duplicates = sum(len(g["duplicates"]) for g in groups)
    total_missing = sum(len(g["missing"]) for g in groups if g["rows"] or not g["min_required"])
    total_extras = sum(len(g["extras"]) for g in groups)

    return {
        "groups": groups,
        "total_photos": total_photos,
        "pending_photos": pending_photos,
        "total_duplicates": total_duplicates,
        "total_missing": total_missing,
        "total_extras": total_extras,
    }


def _set_aside_photo(row, source):
    """把一張重複的照片移出報告，搬到 ignored 資料夾——刻意不是刪除，判斷錯了還救得回來。

    已套用的照片一定要「先把 manifest.csv 那一列拿掉，再搬檔案」。順序反過來的話，萬一
    檔案搬走了、改 manifest 卻失敗，manifest 就留下一列指向不存在的檔案，之後產生報告時
    那一格會變成「找不到照片」，而且完全看不出原因。照這個順序，最差的情況也只是 sorted
    資料夾裡多留一張沒人參照的照片，不影響任何報告。
    """
    utils.IGNORED_DIR.mkdir(parents=True, exist_ok=True)
    if source == "pending":
        utils.remove_session_pending_rows([row["staged_filename"]])
        src = utils.STAGING_DIR / row["staged_filename"]
    else:
        remaining = [
            r for r in utils.load_manifest() if r.get("sorted_path") != row.get("sorted_path")
        ]
        utils.rewrite_manifest(remaining)
        src = utils.DATA_DIR / row["sorted_path"]
    if src.exists():
        shutil.move(str(src), str(utils.unique_path(utils.IGNORED_DIR, src.name)))


def _render_duplicate_photos(item, key_prefix):
    """把重複的那幾張並排顯示出來，讓人直接看圖決定要留哪一張。"""
    # 欄數固定 3 欄（就算只有 2 張、右邊那欄空著也一樣），這樣每一組重複照片的圖磚
    # 寬度都一致；欄數跟著張數變的話，2 張的那組會被拉得比 3 張的那組大一號。
    columns = st.columns(DUPLICATE_PHOTO_COLS)
    for i, (row, source) in enumerate(item["photos"]):
        with columns[i % len(columns)]:
            path = _photo_path_for(row, source)
            if path.exists():
                try:
                    _render_thumbnail(path)
                except Exception as e:
                    st.caption(f"（無法顯示預覽：{e}）")
            else:
                st.caption("（找不到照片檔案）")
            label = "已套用" if source == "manifest" else "待確認"
            st.caption(f"{label}｜{row.get('original_filename', path.name)}")
            # 按鈕寬度跟預覽圖的框一樣寬，這樣按鈕跟照片會對齊成一排；
            # 用 use_container_width 的話按鈕會撐滿整欄，比照片寬一大截，看起來歪掉。
            if st.button(
                "🗑️ 移出報告",
                key=f"{key_prefix}_setaside_{i}",
                help="搬到 ignored 資料夾，不會刪除，判斷錯了還能拿回來",
                width=THUMBNAIL_TILE_PX,
            ):
                try:
                    _set_aside_photo(row, source)
                    st.success("已移出，照片保留在 ignored 資料夾。")
                except Exception as e:
                    st.error(f"移出失敗：{e}")
                st.rerun()


def _render_day_overview(analysis, date_str):
    """總覽面板本體。刻意只在這裡做「看」跟「移出重複」，不做修改分類/說明——
    那是側邊欄「回去修改這次已標記的照片」的事，兩邊各做一件事比較不會誤按。"""
    site_label = f"　—　{utils.SITE_NAME}" if utils.SITE_NAME else ""
    st.subheader(f"📅 {date_str} 施工總覽{site_label}")

    if analysis["total_photos"] == 0:
        st.info("這個施工日期還沒有任何照片。")
        return

    st.caption(
        f"共 {analysis['total_photos']} 張"
        f"（已套用 {analysis['total_photos'] - analysis['pending_photos']} 張、"
        f"待確認 {analysis['pending_photos']} 張）"
    )

    metric_cols = st.columns(3)
    metric_cols[0].metric("尚未拍攝", f"{analysis['total_missing']} 項")
    metric_cols[1].metric("需確認是否重複", f"{analysis['total_duplicates']} 項")
    metric_cols[2].metric("自行輸入的說明", f"{analysis['total_extras']} 項")

    if analysis["total_duplicates"] == 0:
        st.success("沒有發現重複的項目。")

    if analysis["pending_photos"]:
        st.info(
            f"這一天還有 {analysis['pending_photos']} 張照片在「本次工作階段」尚未套用。"
        )

    st.divider()

    for group in analysis["groups"]:
        if not group["rows"] and not group["missing"]:
            continue

        photo_count = len(group["rows"])
        if group["min_required"]:
            headline = f"{photo_count} / {group['min_required']} 張"
        else:
            done = len(group["shot"])
            headline = f"{done} / {done + len(group['missing'])} 項　·　{photo_count} 張"
        st.markdown(f"**{group['display_name']}**　　`{headline}`")

        if group["min_required"]:
            if photo_count < group["min_required"]:
                st.warning(
                    f"未達最低 {group['min_required']} 張要求，報告會被標註。"
                    "這個分類同一個項目本來就會拍很多張，不檢查重複。"
                )
            else:
                st.caption("這個分類有最低張數要求，同一個項目本來就會拍很多張，不檢查重複。")
        elif group["repeat_pattern"]:
            st.info(
                "這個分類大部分項目都成對出現，可能是同一天做了兩個路段，以下不逐項標記重複。"
                "如果不是的話，請逐項確認是不是真的拍重複了。"
            )

        lines = []
        for item in group["shot"]:
            if item["caption"] in group["duplicates"]:
                continue
            suffix = "" if item["count"] == 1 else f"　×{item['count']} 張"
            lines.append(f"- ✅ {item['caption']}{suffix}")
        for item in group["extras"]:
            if item["caption"] in group["duplicates"]:
                continue
            suffix = "" if item["count"] == 1 else f" ×{item['count']}"
            lines.append(f"- 📝 {item['caption']}{suffix}　（自行輸入）")
        for label in group["missing"]:
            lines.append(f"- ⬜ {label}")
        if lines:
            st.markdown("\n".join(lines))

        for item in group["shot"] + group["extras"]:
            if item["caption"] not in group["duplicates"]:
                continue
            st.warning(f"⚠️ {item['caption']}　—　{item['count']} 張，請確認是不是拍重複了")
            _render_duplicate_photos(item, key_prefix=f"{group['display_name']}_{item['caption']}")

        st.divider()


def render_category_caption_form(
    config, manifest_rows, session_pending_rows, date_str, key_prefix,
    seed_category_name=None, seed_caption_text=None,
):
    """畫出「分類」「材料別/標線種類」「照片說明」「數值輸入」表單，回傳這次選擇的結果。

    key_prefix 讓同一份表單可以用在不同情境（標記新照片、回頭修改某張已標記的照片）而不互相干擾。
    seed_category_name / seed_caption_text：回頭修改已標記照片時，用這張照片「目前實際」的
    分類/說明，讓選單第一次出現時就還原成原本選的樣子，而不是套用「上一張存檔時選的」這個
    全域記憶（那是給標記新照片用的預設值，跟修改舊照片是兩回事）。
    """
    cat_key = f"category_select_{key_prefix}"

    # 有些分類在 config.json 裡其實是拆成好幾個底層項目（例如「鋪築施工照片」實際上是
    # 「鋪築施工照片01」+「02」兩個項目，各自帶不同的說明清單，這樣報告產生時才會各自分頁），
    # 但畫面上只用共同的 display_name 顯示一次，選的時候完全看不出底層有拆開。
    category_display_names = []
    seen_display_names = set()
    for c in config["categories"]:
        dn = utils.display_name(c)
        if dn not in seen_display_names:
            seen_display_names.add(dn)
            category_display_names.append(dn)

    seed_owner_entry = None
    if seed_category_name is not None:
        seed_owner_entry = next((c for c in config["categories"] if c["name"] == seed_category_name), None)

    # 每張新照片預設帶入「上一張存檔時選的分類」，因為連續拍的照片通常都是同一個分類，
    # 不然每張都要重新選一次分類很煩。cat_key 是這個情境專屬的 key，第一次出現時
    # （也就是還沒被使用者動過）才帶入預設值：回頭修改的話帶入這張原本的分類，否則帶入上一次的。
    if cat_key not in st.session_state:
        if seed_owner_entry is not None:
            seed_display = utils.display_name(seed_owner_entry)
            if seed_display in category_display_names:
                st.session_state[cat_key] = seed_display
        else:
            remembered_category = st.session_state.get("last_category_choice")
            if remembered_category in category_display_names:
                st.session_state[cat_key] = remembered_category

    # 只有分類本身有 material_options/type_options 時才需要多留一欄給材料別/標線種類，
    # 沒有的話「分類」就撐滿整排，不要因為多留了一欄空白而變窄。
    # Streamlit 在使用者切換這個 selectbox 時，rerun 一開始 session_state[cat_key] 就已經是
    # 「剛選好的新值」，所以這裡讀到的永遠是最新選擇，不會有延遲一輪的問題。
    pending_category = st.session_state.get(cat_key, category_display_names[0] if category_display_names else None)
    pending_entries = [c for c in config["categories"] if utils.display_name(c) == pending_category]
    category_needs_extra_col = any(
        e.get("material_options") or e.get("type_options") for e in pending_entries
    )

    if category_needs_extra_col:
        cat_col, extra_col, cat_x_col = st.columns([5, 3, 1])
    else:
        cat_col, cat_x_col = st.columns([8, 1])
        extra_col = None

    with cat_col:
        st.caption("分類")
        category_choice = st.selectbox(
            "分類", category_display_names + [NEW_CATEGORY_OPTION], label_visibility="collapsed", key=cat_key
        )

    if category_choice == NEW_CATEGORY_OPTION:
        chosen_category = st.text_input(
            "輸入新分類名稱", value="", key=f"new_category_name_{key_prefix}"
        ).strip()
        matching_entries = []
    else:
        chosen_category = category_choice  # 這是顯示名稱；實際存檔用的分類名稱要等說明選好才知道
        matching_entries = [c for c in config["categories"] if utils.display_name(c) == chosen_category]

    material_options_combined = next(
        (e["material_options"] for e in matching_entries if e.get("material_options")), None
    )
    type_options_combined = next(
        (e["type_options"] for e in matching_entries if e.get("type_options")), None
    )

    # 反查這張照片原本的說明文字是用哪個材料別/標線種類/數值產生的，只有在使用者還沒換過
    # 分類（目前的 matching_entries 仍然包含原本那個底層分類）時才有意義。
    seed_match = None
    if seed_owner_entry is not None and seed_caption_text is not None and seed_owner_entry in matching_entries:
        seed_match = utils.match_caption_selection(seed_caption_text, seed_owner_entry)

    # 材料別（鋪築施工照片）/ 標線種類（標線標記照片）下拉選單：只有設定裡有對應欄位的分類才會出現
    selections = {}
    if extra_col is not None:
        with extra_col:
            if material_options_combined:
                material_key = f"material_{key_prefix}"
                if material_key not in st.session_state:
                    seed_material = seed_match["material"] if seed_match else None
                    if seed_material in material_options_combined:
                        st.session_state[material_key] = seed_material
                    else:
                        remembered_material = st.session_state.get("last_material")
                        if remembered_material in material_options_combined:
                            st.session_state[material_key] = remembered_material
                st.caption("材料別")
                selections["material"] = st.selectbox(
                    "材料別",
                    options=material_options_combined,
                    key=material_key,
                    label_visibility="collapsed",
                )
            elif type_options_combined:
                type_key = f"type_{key_prefix}"
                if type_key not in st.session_state:
                    seed_type = seed_match["type"] if seed_match else None
                    if seed_type in type_options_combined:
                        st.session_state[type_key] = seed_type
                    else:
                        remembered_type = st.session_state.get("last_type")
                        if remembered_type in type_options_combined:
                            st.session_state[type_key] = remembered_type
                st.caption("標線種類")
                selections["type"] = st.selectbox(
                    "標線種類",
                    options=type_options_combined,
                    key=type_key,
                    label_visibility="collapsed",
                )

    with cat_x_col:
        # 撐出跟「分類」/「材料別」標題文字一樣的高度，讓 ✕ 按鈕跟下拉選單的上緣對齊
        # （st.caption 如果內容是純空白字元，瀏覽器會把它塌縮成 0 高度，所以改用固定高度的 div）
        st.markdown("<div style='height:38px'></div>", unsafe_allow_html=True)
        if category_choice != NEW_CATEGORY_OPTION and st.button(
            "✕", key=f"delete_category_{key_prefix}_{category_choice}", use_container_width=True
        ):
            def _remove_category(fresh_config):
                before = len(fresh_config["categories"])
                fresh_config["categories"] = [
                    c for c in fresh_config["categories"] if utils.display_name(c) != category_choice
                ]
                return len(fresh_config["categories"]) != before

            utils.update_config(_remove_category)
            st.rerun()

    _render_caption_checklist(
        matching_entries, selections, manifest_rows + session_pending_rows, date_str, key_prefix=key_prefix
    )

    # 找出這個分類底下的常用說明清單（新分類的話清單是空的），套用材料別/標線種類代換。
    # 一個顯示名稱可能對應好幾個底層項目，說明清單要全部合併，並記住每一條說明實際屬於哪個底層項目
    # （owner_name），這樣選定說明之後才知道這張照片真正要歸進哪一個分類、存進哪個資料夾。
    rendered_captions = []
    for entry in matching_entries:
        for c in entry["captions"]:
            rendered = utils.render_caption(c, selections)
            if rendered is not None:
                rendered["owner_name"] = entry["name"]
                rendered_captions.append(rendered)

    cap_key = f"caption_select_{key_prefix}"

    st.markdown("照片說明")
    # 跟「分類」那排一樣：只有選到的說明需要填入 cm 數值時，才多留一欄放輸入框，
    # 不需要的話「照片說明」就撐滿整排。原理同上，讀 session_state 就能拿到這一輪剛選好的值。
    caption_options = [r["display"] for r in rendered_captions] + [NEW_CAPTION_OPTION]

    value_key = f"value_{key_prefix}"

    # 同樣道理：這個情境第一次出現時，預設帶入「這張照片原本的說明」（回頭修改時）或
    # 「上一張存檔時選的說明」（標記新照片時）。
    if cap_key not in st.session_state:
        seed_display = None
        if seed_match is not None:
            seed_rendered = utils.render_caption(seed_match["caption"], selections)
            if seed_rendered is not None and seed_rendered["display"] in caption_options:
                seed_display = seed_rendered["display"]
        if seed_display is not None:
            st.session_state[cap_key] = seed_display
            if seed_match["value"] is not None and value_key not in st.session_state:
                st.session_state[value_key] = seed_match["value"]
        elif seed_owner_entry is not None:
            # seed 是自訂/自由輸入的說明（找不到對應模板），退回自行輸入模式
            st.session_state[cap_key] = NEW_CAPTION_OPTION
        else:
            remembered_caption = st.session_state.get("last_caption_choice")
            if remembered_caption in caption_options:
                st.session_state[cap_key] = remembered_caption

    pending_caption = st.session_state.get(cap_key)
    pending_rendered = next((r for r in rendered_captions if r["display"] == pending_caption), None)
    caption_needs_value_col = bool(pending_rendered and pending_rendered["needs_value"])

    if caption_needs_value_col:
        cap_select_col, cap_value_col, cap_x_col = st.columns([5, 3, 1])
    else:
        cap_select_col, cap_x_col = st.columns([8, 1])
        cap_value_col = None

    with cap_select_col:
        caption_choice = st.selectbox(
            "照片說明", options=caption_options, label_visibility="collapsed", key=cap_key
        )

    chosen_rendered = next((r for r in rendered_captions if r["display"] == caption_choice), None)

    # 真正要存進 manifest/資料夾的分類名稱：如果這個顯示名稱底下有好幾個底層項目
    # （例如鋪築施工照片01/02），要等說明選好才知道這張照片屬於哪一個；找不到對應說明
    # （自訂新分類，或自行輸入的自訂說明）就分別退回輸入的新名稱，或底下第一個項目。
    if category_choice == NEW_CATEGORY_OPTION:
        real_category = chosen_category
    elif chosen_rendered is not None:
        real_category = chosen_rendered["owner_name"]
    elif matching_entries:
        real_category = matching_entries[0]["name"]
    else:
        real_category = chosen_category

    value_text = ""
    if cap_value_col is not None:
        with cap_value_col:
            if chosen_rendered and chosen_rendered["needs_value"]:
                # 不顯示獨立的標籤文字（改用 placeholder），這樣輸入框的上緣才會跟左邊的照片說明下拉選單對齊
                value_text = st.text_input(
                    f"{chosen_rendered['value_label']}（cm）",
                    value="",
                    key=value_key,
                    label_visibility="collapsed",
                    placeholder=f"{chosen_rendered['value_label']}（cm）",
                ).strip()

    # 只有使用者自己打過的純文字說明才能用 ✕ 刪除；模板算出來的結構化項目維持在清單裡，不給刪
    with cap_x_col:
        can_delete_caption = chosen_rendered is not None and isinstance(chosen_rendered["raw"], str)
        if caption_choice != NEW_CAPTION_OPTION and can_delete_caption and st.button(
            "✕", key=f"delete_caption_{key_prefix}_{chosen_category}_{caption_choice}", use_container_width=True
        ):
            owner_name = chosen_rendered["owner_name"]
            raw_caption = chosen_rendered["raw"]

            def _remove_caption(fresh_config):
                owner_entry = next((c for c in fresh_config["categories"] if c["name"] == owner_name), None)
                if owner_entry and raw_caption in owner_entry["captions"]:
                    owner_entry["captions"].remove(raw_caption)
                    return True
                return False

            _, removed = utils.update_config(_remove_caption)
            if removed:
                st.rerun()

    material_options = material_options_combined
    is_new_freeform_caption = caption_choice == NEW_CAPTION_OPTION

    freeform_default = ""
    if is_new_freeform_caption and seed_owner_entry is not None and seed_match is None and seed_caption_text:
        freeform_default = seed_caption_text

    if is_new_freeform_caption:
        final_caption = st.text_input(
            "輸入照片說明", value=freeform_default, key=f"freeform_caption_{key_prefix}"
        ).strip()
    elif chosen_rendered["needs_value"]:
        final_caption = utils.apply_value(chosen_rendered, value_text) if value_text else ""
        if value_text:
            preview_html = _material_preview_html(final_caption, material_options)
            if preview_html:
                st.markdown(f"照片說明預覽：{preview_html}", unsafe_allow_html=True)
    else:
        final_caption = caption_choice
        preview_html = _material_preview_html(final_caption, material_options)
        if preview_html:
            st.markdown(f"照片說明預覽：{preview_html}", unsafe_allow_html=True)

    # 有設定 min_required 的分類（例如交維照片）：顯示本日已標記張數提示
    real_category_entry = next((c for c in config["categories"] if c["name"] == real_category), None)
    if real_category_entry and real_category_entry.get("min_required"):
        min_required = real_category_entry["min_required"]
        # 已經完成套用的張數 + 這次還沒按「完成本次作業」的張數，兩邊都要算，
        # 不然標記到一半（都還沒套用裁切/浮水印）時，這裡會一直顯示 0 張。
        tagged_count = sum(
            1 for r in manifest_rows
            if r["category"] == real_category and r["date"] == date_str
        ) + sum(
            1 for r in session_pending_rows
            if r["category"] == real_category and r["date"] == date_str
        )
        count_msg = f"📋 本日「{chosen_category}」已標記 {tagged_count} / {min_required} 張"
        if tagged_count < min_required:
            st.warning(count_msg + "，尚未達到最低張數要求。")
        else:
            st.success(count_msg + "，已達到最低張數要求。")

    return {
        "real_category": real_category,
        "final_caption": final_caption,
        "category_choice": category_choice,
        "caption_choice": caption_choice,
        "is_new_freeform_caption": is_new_freeform_caption,
        "selections": selections,
    }


# 工地名稱要出現在標題和瀏覽器分頁上：好幾個工地的辦公室版可以同時開著（各自一個埠、
# 各自一個分頁），畫面長得一模一樣，不寫清楚就完全分不出現在標記的照片會存到哪個工地去。
# set_page_config 必須是第一個 streamlit 指令，而且整支程式只能呼叫一次。
_APP_TITLE = f"📸 施工照片標記工具　—　{utils.SITE_NAME}" if utils.SITE_NAME else "📸 施工照片標記工具"
st.set_page_config(
    page_title=f"施工照片標記工具 - {utils.SITE_NAME}" if utils.SITE_NAME else "施工照片標記工具",
    layout="wide",
)
utils.ensure_dirs()
config = utils.load_config()

# 側邊欄的間距。Streamlit 每個元件之間預設留很大的空隙，側邊欄那幾個區塊加起來會長到要捲動，
# 一眼看不完。這裡只調間距（元件本身完全沒動），把區塊之間的空白縮小、標題大小統一。
# 注意：這是靠 Streamlit 內部的 data-testid 選到元素的，requirements.txt 已經把 streamlit 鎖在
# 1.59.1，所以選擇器是穩定的；哪天升級版本後如果選不到，也只是回到預設間距，功能不受影響。
# 這裡只改 gap 和字級，不要去清掉標題的 padding：Streamlit 的標題外框只有 7px 高、靠標題自己的
# padding 撐開，再用 -16px 的負 margin 把下一個元件拉上來；把 padding 清成 0，標題會直接壓在
# 下一個元件上面（試過，整個側邊欄的字會疊在一起）。
st.markdown(
    """
    <style>
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.55rem; }
    [data-testid="stSidebar"] hr { margin: 0.5rem 0; }
    [data-testid="stSidebar"] h3 { font-size: 1.05rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title(_APP_TITLE)

manifest_rows = utils.load_manifest()
all_incoming_photos = utils.list_incoming_photos()
incoming_photos = all_incoming_photos
incoming_count_total = len(incoming_photos)  # 給「待標記張數」這個指標用，不受下面的略過篩選影響

# 這次工作階段裡「已經選好分類/說明，但還沒套用裁切和日期浮水印」的照片，
# 存在 session_pending.csv／staging 資料夾裡，按「完成本次作業」之前都可以回頭修改。
session_pending_rows = utils.load_session_pending()

# 記住這次瀏覽器連線中，使用者按過「略過」的照片，讓它們排到後面而不是一直卡住
if "skipped_names" not in st.session_state:
    st.session_state.skipped_names = set()

not_skipped = [p for p in incoming_photos if p.name not in st.session_state.skipped_names]
if not_skipped:
    incoming_photos = not_skipped
else:
    # 全部都被略過了，就重新從頭開始顯示
    st.session_state.skipped_names = set()

# ---------- 側邊欄：最上面一行就把今天的狀況講完 ----------
# 三個數字以前是側邊欄最下面三個 st.metric，佔掉很長一段，還要捲到底才看得到；
# 而且「incoming 有幾張」「已經選好幾張」這兩句說明講的就是同樣的數字，重複了。
# 這裡併成一行，工地名稱也從 st.info 的大方塊改成一行粗體字。
if utils.SITE_NAME:
    st.sidebar.markdown(f"🏗️ **{utils.SITE_NAME}**")
st.sidebar.caption(
    f"待標記 {incoming_count_total}　·　待確認 {len(session_pending_rows)}　·　已完成 {len(manifest_rows)}"
)
st.sidebar.divider()

# ---------- 側邊欄：整理 incoming（incoming 照片很多時，先挑出不用標記的） ----------
st.sidebar.subheader("🗂️ 整理 incoming")
if st.sidebar.button("挑出要忽略的照片", use_container_width=True):
    st.session_state["show_bulk_picker"] = True
    st.rerun()

# ---------- 側邊欄：本次工作階段：確認完再套用裁切/浮水印 ----------
st.sidebar.subheader("📦 本次工作階段")

PENDING_EDIT_PLACEHOLDER = "（不修改，繼續標記新照片）"
editing_pending_row = None

# Streamlit 規定 widget 的 session_state 只能在該 widget「這一輪還沒被建立之前」修改，
# 所以「更新這張」/「返回標記新照片」按鈕不能直接改 edit_pending_choice（選單早就建立過了），
# 只能先設一個旗標，等下一輪重新執行、選單「還沒建立」的這個時間點才套用。
if st.session_state.pop("_reset_edit_choice", False):
    st.session_state["edit_pending_choice"] = PENDING_EDIT_PLACEHOLDER

if session_pending_rows:
    pending_labels = [PENDING_EDIT_PLACEHOLDER] + [
        f"{r['original_filename']}－{r['caption']}" for r in session_pending_rows
    ]
    edit_choice = st.sidebar.selectbox(
        "回去修改已標記的照片", pending_labels, key="edit_pending_choice"
    )
    if edit_choice != PENDING_EDIT_PLACEHOLDER:
        editing_pending_row = session_pending_rows[pending_labels.index(edit_choice) - 1]

    if st.sidebar.button(
        f"✅ 完成本次作業（{len(session_pending_rows)} 張）",
        type="primary",
        help="把這 %d 張的裁切與日期浮水印一次套用上去，搬進 sorted 資料夾" % len(session_pending_rows),
        use_container_width=True,
    ):
        finalize_errors = []
        finalized_staged_filenames = []
        for row in session_pending_rows:
            target_path = None
            manifest_written = False
            try:
                staged_path = utils.STAGING_DIR / row["staged_filename"]
                with Image.open(staged_path) as staged_img:
                    original_img_for_finalize = ImageOps.exif_transpose(staged_img)
                    left = int(row["crop_left"])
                    top = int(row["crop_top"])
                    crop_w = int(row["crop_width"])
                    crop_h = int(row["crop_height"])
                    cropped_for_finalize = original_img_for_finalize.crop(
                        (left, top, left + crop_w, top + crop_h)
                    )

                category_real = row["category"]
                row_date_str = row["date"]
                row_photo_date_str = row["photo_date"]
                caption_text = row["caption"]

                target_dir = utils.sorted_dir_for(row_date_str, category_real)
                target_dir.mkdir(parents=True, exist_ok=True)
                safe_caption = utils.safe_filename(caption_text)
                src_suffix = staged_path.suffix.lower()
                output_suffix = ".jpg" if src_suffix == ".heic" else src_suffix
                target_path = utils.unique_path(target_dir, f"{safe_caption}{output_suffix}")

                # 蓋日期浮水印如果失敗，「不要」退而求其次存一張沒有日期的照片：查驗報告的照片
                # 一定要有拍照日期，默默存一張沒日期的進去，等於安靜地產生一份不合格的報告，
                # 而且畫面上完全不會有任何提示，等到報告被退件時現場早就鋪完了、補拍不回來。
                # 這裡讓錯誤往外丟給下面的 except 收集起來顯示，這張照片會原封不動留在 staging，
                # session_pending.csv 裡的紀錄也會保留，使用者處理完問題後可以直接再按一次。
                utils.save_stamped_image(cropped_for_finalize, target_path, row_photo_date_str)

                utils.append_manifest({
                    "date": row_date_str,
                    "category": category_real,
                    "caption": caption_text,
                    # 存成「相對於這個工地資料夾」的路徑，不是相對於程式所在的資料夾：
                    # 一台電腦服務好幾個工地時，每個工地有自己的 manifest.csv，裡面的路徑
                    # 只要對自己的資料夾有意義就好，這樣整個工地資料夾搬走也不會失效。
                    # 預設工地的資料夾就是程式所在的資料夾，所以舊的 manifest.csv 不受影響。
                    "sorted_path": str(target_path.relative_to(utils.DATA_DIR)),
                    "original_filename": row["original_filename"],
                    "tagged_at": datetime.now().isoformat(timespec="seconds"),
                    "photo_date": row_photo_date_str,
                })
                manifest_written = True
                finalized_staged_filenames.append(row["staged_filename"])
                # 寫進 manifest 就算這張完成了。刪掉 staging 的原始檔只是順手清理，
                # 就算刪不掉（例如檔案剛好被防毒軟體鎖住）也不影響結果，絕對不能因此把這張
                # 當成失敗——那會讓它留在待確認清單裡，下次再按一次「完成本次作業」就會被
                # 重複處理一遍，報告裡出現兩張一模一樣的照片。
                try:
                    staged_path.unlink(missing_ok=True)
                except OSError:
                    pass
            except Exception as e:
                # 這張沒有成功處理完：如果輸出檔已經建到一半（但還沒寫進 manifest），把它清掉，
                # 免得 sorted 資料夾裡留下一張沒人認得、也不會出現在報告裡的殘缺照片。
                # staging 的原始照片和 session_pending.csv 的紀錄都刻意保留，等使用者重試。
                if target_path is not None and not manifest_written:
                    target_path.unlink(missing_ok=True)
                finalize_errors.append(f"{row['original_filename']}：{e}")

        # 用 remove_session_pending_rows 而不是「整個清空」：處理這一批的過程中，如果剛好有
        # 手機存了一張新照片進 session_pending.csv，整個清空會連那張新的都一起洗掉；
        # 這裡改成「只移除這次真的處理過的這幾筆」，重新讀最新清單再移除，兩者不會互相影響。
        # 只移除「成功套用完成」的那幾筆：失敗的必須留著，不然照片會卡在 staging 裡變成孤兒，
        # 分類/說明/日期/裁切範圍全部消失，只能整張重來。
        utils.remove_session_pending_rows(finalized_staged_filenames)
        if finalize_errors:
            st.sidebar.error(
                f"有 {len(finalize_errors)} 張照片套用失敗（這幾張仍保留在待確認清單裡，"
                "可以修正後再按一次「完成本次作業」）：\n" + "\n".join(finalize_errors)
            )
        if finalized_staged_filenames:
            st.sidebar.success(
                f"已完成，套用了 {len(finalized_staged_filenames)} 張照片的裁切與浮水印！"
            )
        st.rerun()
else:
    st.sidebar.caption("目前沒有待確認的照片。")

# ---------- 側邊欄：施工總覽（產生報告前先看一次當天拍了什麼、漏了什麼、有沒有重複） ----------
st.sidebar.divider()
st.sidebar.subheader("🔍 施工總覽")

# 這裡的日期刻意把「還沒完成本次作業」的照片也算進去，跟下面產生報告的日期清單不一樣：
# 總覽最有用的時機正好是還沒套用之前——那時候發現拍重複、漏拍，處理起來最單純，
# 照片都還在 staging，移掉一張不用動 sorted 也不用改 manifest。
overview_dates = sorted(
    {r["date"] for r in manifest_rows} | {r["date"] for r in session_pending_rows},
    reverse=True,
)
if not overview_dates:
    st.sidebar.caption("還沒有任何已標記的照片。")
else:
    overview_date = st.sidebar.selectbox(
        "選擇施工日期", overview_dates, key="overview_date_choice",
        label_visibility="collapsed",
    )
    overview_analysis = _analyze_day(config, manifest_rows, session_pending_rows, overview_date)
    overview_dupes = overview_analysis["total_duplicates"]
    # 重複的張數直接寫在按鈕上就夠了。以前按鈕下面還有一個黃色警告方塊講同一件事，
    # 佔掉三行又沒有多給任何資訊，拿掉。
    if st.sidebar.button(
        f"🔍 檢查本日照片（{overview_dupes} 項重複）" if overview_dupes else "🔍 檢查本日照片",
        type="primary" if overview_dupes else "secondary",
        use_container_width=True,
    ):
        st.session_state["show_day_overview"] = overview_date
        st.rerun()

# ---------- 側邊欄：產生報告 ----------
st.sidebar.divider()
st.sidebar.subheader("📄 產生報告")

available_report_dates = sorted({r["date"] for r in manifest_rows}, reverse=True)
if not available_report_dates:
    st.sidebar.caption("還沒有可以產生報告的照片。")
else:
    report_date = st.sidebar.selectbox(
        "選擇施工日期", available_report_dates, key="report_date_choice",
        label_visibility="collapsed",
    )

    # 這個提醒留著：這天還有照片沒套用就產生報告，產出的報告會少照片，而且不會有任何地方
    # 提示，等發現時通常已經送出去了。只是把三行縮成一行。
    pending_for_report_date = sum(1 for r in session_pending_rows if r["date"] == report_date)
    if pending_for_report_date:
        st.sidebar.warning(f"⚠️ 這天還有 {pending_for_report_date} 張未套用，不會進報告")

    if st.sidebar.button("📄 產生報告", use_container_width=True):
        day_rows = [r for r in manifest_rows if r["date"] == report_date]
        try:
            out_path = generate_report.build_report(report_date, config, day_rows)
            st.session_state["generated_report_path"] = out_path
            st.sidebar.success(f"已產生：{out_path.name}")
        except Exception as e:
            st.sidebar.error(f"產生報告失敗：{e}")

    generated_report_path = st.session_state.get("generated_report_path")
    if generated_report_path and generated_report_path.exists():
        with open(generated_report_path, "rb") as f:
            st.sidebar.download_button(
                "⬇️ 下載報告",
                data=f.read(),
                file_name=generated_report_path.name,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )

# 整體進度的三個數字改放在側邊欄最上面那一行（見上面的 st.sidebar.caption），
# 不再用三個 st.metric 佔掉側邊欄最下面一大段。

# ---------- 主畫面：修改某一張還沒定案的照片（分類/說明/裁切/日期） ----------
if editing_pending_row is not None:
    row = editing_pending_row
    staged_path = utils.STAGING_DIR / row["staged_filename"]
    edit_key_prefix = f"edit_{row['staged_filename']}"

    st.subheader(f"✏️ 修改：{row['original_filename']}－{row['caption']}")

    edit_photo_col, edit_form_col = st.columns([5, 4])

    with edit_photo_col:
        st.caption("✂️ 重新調整裁切範圍（比例已鎖定為報告版面的照片格）")
        edit_original_img = ImageOps.exif_transpose(Image.open(staged_path))
        default_coords = (
            int(row["crop_left"]),
            int(row["crop_left"]) + int(row["crop_width"]),
            int(row["crop_top"]),
            int(row["crop_top"]) + int(row["crop_height"]),
        )
        edit_crop_rect = _render_crop_tool(
            edit_original_img,
            key=f"edit_cropper_{row['staged_filename']}",
            default_coords=default_coords,
        )
        st.caption(f"裁切後尺寸：{edit_crop_rect['width']} × {edit_crop_rect['height']}px")

    with edit_form_col:
        edit_photo_date = st.date_input(
            "拍照日期",
            value=datetime.strptime(row["photo_date"], "%Y-%m-%d").date(),
            key=f"edit_photo_date_{row['staged_filename']}",
        )
        edit_construction_date = st.date_input(
            "施工日期",
            value=datetime.strptime(row["date"], "%Y-%m-%d").date(),
            key=f"edit_construction_date_{row['staged_filename']}",
        )
        edit_date_str = edit_construction_date.strftime("%Y-%m-%d")

        edit_result = render_category_caption_form(
            config, manifest_rows, session_pending_rows, edit_date_str, edit_key_prefix,
            seed_category_name=row["category"], seed_caption_text=row["caption"],
        )

        edit_save_col, edit_cancel_col = st.columns(2)
        with edit_save_col:
            update_clicked = st.button("💾 更新這張", type="primary", use_container_width=True)
        with edit_cancel_col:
            if st.button("↩ 返回標記新照片", use_container_width=True):
                st.session_state["_reset_edit_choice"] = True
                st.rerun()

        if update_clicked:
            if not edit_result["real_category"]:
                st.error("請輸入新分類名稱後再更新。")
            elif not edit_result["final_caption"].strip():
                st.error("請輸入或選擇照片說明後再更新（若該說明需要填入 cm 數值，請確認已輸入數字）。")
            else:
                def _apply_edit_category_caption(fresh_config):
                    changed = False
                    category_entry = next(
                        (c for c in fresh_config["categories"] if c["name"] == edit_result["real_category"]), None
                    )
                    if category_entry is None:
                        category_entry = {"name": edit_result["real_category"], "captions": []}
                        fresh_config["categories"].append(category_entry)
                        changed = True
                    if (
                        edit_result["is_new_freeform_caption"]
                        and edit_result["final_caption"] not in category_entry["captions"]
                    ):
                        category_entry["captions"].append(edit_result["final_caption"])
                        changed = True
                    return changed

                utils.update_config(_apply_edit_category_caption)

                # 用 update_session_pending_row 而不是「改本地 row 再整個存回去」：修改這一筆
                # 的同時，如果剛好有手機存了一張新照片進 session_pending.csv，整個存回去會把
                # 那張新的蓋掉；這裡改成「只更新這一筆指定的欄位」，重新讀最新清單再更新。
                utils.update_session_pending_row(row["staged_filename"], {
                    "category": edit_result["real_category"],
                    "caption": edit_result["final_caption"],
                    "crop_left": edit_crop_rect["left"],
                    "crop_top": edit_crop_rect["top"],
                    "crop_width": edit_crop_rect["width"],
                    "crop_height": edit_crop_rect["height"],
                    "photo_date": edit_photo_date.strftime("%Y-%m-%d"),
                    "date": edit_date_str,
                })
                st.session_state["_reset_edit_choice"] = True
                st.success("已更新！")
                st.rerun()

# ---------- 主畫面：施工總覽（產生報告前的檢查） ----------
elif st.session_state.get("show_day_overview"):
    overview_target_date = st.session_state["show_day_overview"]
    if st.button("← 返回標記畫面"):
        st.session_state.pop("show_day_overview", None)
        st.rerun()
    _render_day_overview(
        _analyze_day(config, manifest_rows, session_pending_rows, overview_target_date),
        overview_target_date,
    )

# ---------- 主畫面：整理 incoming（勾選要忽略的照片，搬到 ignored 資料夾） ----------
elif st.session_state.get("show_bulk_picker"):
    st.subheader("🗂️ 整理 incoming 資料夾")
    st.caption(
        "勾選不需要標記的照片，按下面的按鈕搬到 ignored 資料夾（不會刪除，"
        "之後想拿回來標記可以自己把檔案搬回 incoming）。"
    )

    if not all_incoming_photos:
        st.info("incoming 資料夾目前沒有照片。")
    else:
        # 勾選狀態的唯一真實來源是這個 set（存檔名），不是勾選框各自的 widget 狀態：
        # 換頁的時候，不在畫面上的勾選框不會被 Streamlit 建立，widget 狀態不保證留著，
        # 所以每次畫面上出現一個勾選框，都要立刻把它的結果同步回這個 set，換頁後才不會
        # 忘記其他頁勾過的照片。
        if "ignore_selected" not in st.session_state:
            st.session_state["ignore_selected"] = set()
        if "bulk_select_generation" not in st.session_state:
            st.session_state["bulk_select_generation"] = 0

        # 「全選」/「全部取消」要讓所有勾選框（包括不在這一頁的）都套用新值，但勾選框一旦
        # 建立過，widget 的 session_state 就會蓋過 value= 參數。做法是把 widget key 加上一個
        # 每次全選/全部取消就 +1 的版本號，逼 Streamlit 把它們當成全新的勾選框重新套用預設值。
        bulk_action = st.session_state.pop("_bulk_select_action", None)
        if bulk_action == "all":
            st.session_state["ignore_selected"] = {p.name for p in all_incoming_photos}
            st.session_state["bulk_select_generation"] += 1
        elif bulk_action == "none":
            st.session_state["ignore_selected"] = set()
            st.session_state["bulk_select_generation"] += 1

        action_col1, action_col2, action_col3, action_col4 = st.columns(4)
        with action_col1:
            if st.button("全選", use_container_width=True):
                st.session_state["_bulk_select_action"] = "all"
                st.rerun()
        with action_col2:
            if st.button("全部取消", use_container_width=True):
                st.session_state["_bulk_select_action"] = "none"
                st.rerun()
        with action_col4:
            if st.button("↩ 返回標記照片", use_container_width=True):
                st.session_state["show_bulk_picker"] = False
                st.rerun()

        total_pages = (len(all_incoming_photos) - 1) // BULK_PICKER_PAGE_SIZE + 1
        if "bulk_picker_page" not in st.session_state:
            st.session_state["bulk_picker_page"] = 1
        st.session_state["bulk_picker_page"] = min(
            max(1, st.session_state["bulk_picker_page"]), total_pages
        )

        page_col1, page_col2, page_col3 = st.columns([1, 2, 1])
        with page_col1:
            if st.button("⬅ 上一頁", disabled=st.session_state["bulk_picker_page"] <= 1):
                st.session_state["bulk_picker_page"] -= 1
                st.rerun()
        with page_col2:
            st.markdown(
                f"<div style='text-align:center'>第 {st.session_state['bulk_picker_page']} / {total_pages} 頁"
                f"（共 {len(all_incoming_photos)} 張）</div>",
                unsafe_allow_html=True,
            )
        with page_col3:
            if st.button("下一頁 ➡", disabled=st.session_state["bulk_picker_page"] >= total_pages):
                st.session_state["bulk_picker_page"] += 1
                st.rerun()

        page_start = (st.session_state["bulk_picker_page"] - 1) * BULK_PICKER_PAGE_SIZE
        page_photos = all_incoming_photos[page_start:page_start + BULK_PICKER_PAGE_SIZE]

        generation = st.session_state["bulk_select_generation"]
        ignore_selected = st.session_state["ignore_selected"]

        THUMB_COLS = 4
        for row_start in range(0, len(page_photos), THUMB_COLS):
            row_photos = page_photos[row_start:row_start + THUMB_COLS]
            cols = st.columns(THUMB_COLS)
            for col, p in zip(cols, row_photos):
                with col:
                    try:
                        _render_thumbnail(p)
                    except Exception as e:
                        st.warning(f"無法預覽：{e}")
                    st.caption(p.name)
                    checked = st.checkbox(
                        "忽略這張", value=(p.name in ignore_selected),
                        key=f"ignore_chk_{generation}_{p.name}",
                    )
                    if checked:
                        ignore_selected.add(p.name)
                    else:
                        ignore_selected.discard(p.name)

        st.divider()
        selected_count = len(ignore_selected)
        if st.button(
            f"🗑️ 忽略已勾選的照片（共 {selected_count} 張，搬到 ignored 資料夾）",
            type="primary",
            disabled=selected_count == 0,
        ):
            moved = 0
            move_errors = []
            for p in all_incoming_photos:
                if p.name in ignore_selected:
                    try:
                        dest = utils.unique_path(utils.IGNORED_DIR, p.name)
                        shutil.move(str(p), str(dest))
                        moved += 1
                    except Exception as e:
                        move_errors.append(f"{p.name}：{e}")
            st.session_state["ignore_selected"] = set()
            st.session_state["bulk_select_generation"] += 1
            if move_errors:
                st.error("部分照片搬移失敗：\n" + "\n".join(move_errors))
            if moved:
                st.success(f"已把 {moved} 張照片搬到 ignored 資料夾。")
            st.rerun()

# ---------- 主畫面：顯示下一張待標記的照片 ----------
elif not incoming_photos:
    st.success("🎉 incoming 資料夾裡目前沒有照片需要標記。")
    st.info("把新照片放進 incoming 資料夾，然後重新整理這個頁面。")
else:
    photo_path = incoming_photos[0]

    photo_col, form_col = st.columns([5, 4])

    with photo_col:
        # 裁切是必要步驟，不能跳過：比例鎖死跟報告照片格一樣（CROP_ASPECT_RATIO），
        # 存檔時一律用這裡裁切出來的版本，不會存到原始未裁切的照片。
        st.caption(f"✂️ 請裁切照片（比例已鎖定為報告版面的照片格：{photo_path.name}）")
        original_img = ImageOps.exif_transpose(Image.open(photo_path))
        crop_rect = _render_crop_tool(original_img, key=f"cropper_{photo_path.name}")
        st.caption(f"裁切後尺寸：{crop_rect['width']} × {crop_rect['height']}px")

    with form_col:
        guessed_date, is_confident = utils.get_best_guess_date(photo_path)

        st.markdown("**📅 拍照日期**　－　日期會蓋在照片右下角")

        if is_confident:
            photo_date = st.date_input(
                "拍照日期（自動讀取自照片的拍攝資訊，如果相機時間設定錯誤可自行修改）",
                value=guessed_date,
                key=f"photo_date_{photo_path.name}",
            )
        else:
            st.warning(
                "⚠️ 這張照片沒有拍攝時間資訊（常見於截圖、LINE 下載的圖片），偵測不到真正的拍照日期。"
                "下面預設用的是檔案的下載/儲存時間，請務必手動確認、改成實際拍照的日期！"
            )
            photo_date = st.date_input(
                "請手動輸入實際拍照日期",
                value=guessed_date,
                key=f"photo_date_{photo_path.name}",
            )

        st.markdown("**🏗️ 施工日期**　－　用來決定報告分類與資料夾")
        # 記住上一張存檔時的施工日期，不是每次都跳回照片自己的猜測日期：夜間施工常常跨過
        # 午夜，拍照當下已經是隔天，但施工日期應該維持不變。如果是一次上傳橫跨很多天的
        # 舊照片，這代表除了第一張，後面每張都要記得手動改回正確日期（而不是像以前一樣
        # 自動猜對），這是刻意接受的取捨。
        remembered_construction_date = st.session_state.get("last_construction_date", guessed_date)
        construction_date = st.date_input(
            "施工日期",
            value=remembered_construction_date,
            key=f"construction_date_{photo_path.name}",
        )

        if photo_date != construction_date:
            st.info(f"ℹ️ 拍照日期（{photo_date}）跟施工日期（{construction_date}）不一樣。")

        date_str = construction_date.strftime("%Y-%m-%d")
        photo_date_str = photo_date.strftime("%Y-%m-%d")

        result = render_category_caption_form(
            config, manifest_rows, session_pending_rows, date_str, photo_path.name,
        )
        real_category = result["real_category"]
        final_caption = result["final_caption"]
        category_choice = result["category_choice"]
        caption_choice = result["caption_choice"]
        selections = result["selections"]

        btn_col1, btn_col2 = st.columns(2)

        with btn_col1:
            save_clicked = st.button(" 儲存並下一張", type="primary", use_container_width=True)
        with btn_col2:
            skip_clicked = st.button("⏭ 略過這張", use_container_width=True)

    if save_clicked:
        if not real_category:
            st.error("請輸入新分類名稱後再儲存。")
        elif not final_caption.strip():
            st.error("請輸入或選擇照片說明後再儲存（若該說明需要填入 cm 數值，請確認已輸入數字）。")
        else:
            # 如果是新分類，或使用者自己打的新常用說明，存回 config.json，之後可以直接從清單選取。
            # 模板算出來的一次性文字（例如帶 cm 數值、材料別的說明）不會塞進常用清單，避免清單被塞爆。
            # 這裡一律用 real_category（實際底層分類名稱），不是畫面上看到的顯示名稱。
            # 用 update_config 而不是「改本地 config 再整個存回去」：手機那邊也可能同時在新增
            # 分類/說明，用鎖保護、重新讀最新資料再改，才不會兩邊的新增互相蓋掉。
            def _apply_new_category_caption(fresh_config):
                changed = False
                category_entry = next((c for c in fresh_config["categories"] if c["name"] == real_category), None)
                if category_entry is None:
                    category_entry = {"name": real_category, "captions": []}
                    fresh_config["categories"].append(category_entry)
                    changed = True
                if result["is_new_freeform_caption"] and final_caption not in category_entry["captions"]:
                    category_entry["captions"].append(final_caption)
                    changed = True
                return changed

            utils.update_config(_apply_new_category_caption)

            # 這裡不馬上裁切/蓋浮水印/搬進 sorted，而是把「原始、完全沒動過」的照片搬進
            # staging 資料夾，裁切範圍和日期先記在 session_pending.csv 裡。真正套用裁切跟
            # 浮水印，要等按下側邊欄的「完成本次作業」才會一次處理，這樣按完「儲存並下一張」
            # 之後，還是能回頭修改任何一張的分類、說明、拍照日期或裁切範圍。
            original_name = photo_path.name
            staged_path = utils.unique_path(utils.STAGING_DIR, original_name)
            shutil.move(str(photo_path), str(staged_path))

            utils.append_session_pending({
                "staged_filename": staged_path.name,
                "original_filename": original_name,
                "category": real_category,
                "caption": final_caption,
                "date": date_str,
                "photo_date": photo_date_str,
                "crop_left": crop_rect["left"],
                "crop_top": crop_rect["top"],
                "crop_width": crop_rect["width"],
                "crop_height": crop_rect["height"],
                "tagged_at": datetime.now().isoformat(timespec="seconds"),
            })

            # 記住這次選的分類/材料別/標線種類/說明/施工日期，下一張照片會直接預設帶入，
            # 不用每張都重新選一次（但「新增分類」「自行輸入新的說明」這種一次性選項不記）。
            if category_choice != NEW_CATEGORY_OPTION:
                st.session_state["last_category_choice"] = category_choice
            st.session_state["last_material"] = selections.get("material")
            st.session_state["last_type"] = selections.get("type")
            if caption_choice != NEW_CAPTION_OPTION:
                st.session_state["last_caption_choice"] = caption_choice
            st.session_state["last_construction_date"] = construction_date

            st.rerun()

    if skip_clicked:
        st.session_state.skipped_names.add(photo_path.name)
        st.rerun()

st.divider()
st.caption("標記完今天所有照片後，用左側邊欄的「📄 產生報告」就可以直接產生並下載 Word 報告。")
