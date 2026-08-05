# mobile_app.py
# 這是「現場拍照」專用的手機版網頁，跟 app.py（辦公室用的整理/產生報告工具）完全分開，
# 不會互相影響。執行方式：
#     streamlit run mobile_app.py --server.port 8502
#
# 用途：在工地用手機打開這個網頁，按「拍照」會直接開啟手機原生相機（不是網頁模擬鏡頭，
# 拍出來畫質跟平常用相機 App 拍的一樣），拍完選分類/說明/日期，按「儲存」，
# 立刻回到拍照畫面繼續拍下一張。
#
# 存檔位置（staging 資料夾／session_pending.csv／config.json）跟 app.py 完全共用，
# 所以回到辦公室打開 app.py 時，這裡拍的照片會直接出現在「本次工作階段」清單裡，
# 可以照常修改分類/說明/日期，套用裁切與日期浮水印，再產生報告。

import base64
import io
from datetime import date, datetime

import streamlit as st
from PIL import Image, ImageOps

import utils

CROP_ASPECT_RATIO = (utils.PHOTO_SLOT_WIDTH_CM, utils.PHOTO_SLOT_HEIGHT_CM)
NEW_CATEGORY_OPTION = "➕ 新增分類..."
NEW_CAPTION_OPTION = "➕ 自行輸入新的說明..."

_PAGE_TITLE = f"📷 現場拍照－{utils.SITE_NAME}" if utils.SITE_NAME else "📷 現場拍照"

st.set_page_config(page_title=_PAGE_TITLE, layout="centered")

# ---------- 拍照元件：用 <input capture> 直接呼叫手機原生相機 ----------
# 刻意不用 st.camera_input（那個是網頁模擬鏡頭 getUserMedia，畫質較差、較慢），
# 而是用一個小型自訂元件（st.components.v2，Streamlit 1.59+ 內建，不需要另外安裝套件），
# 包一個 capture="environment" 的原生檔案輸入框，手機上點下去會直接開啟相機 App。
_CAMERA_HTML = """
<input type="file" id="camera-input" accept="image/*" capture="environment" style="display:none">
<label for="camera-input" class="camera-btn">📷 拍照</label>
"""
_CAMERA_CSS = """
.camera-btn {
  display: block;
  width: 100%;
  box-sizing: border-box;
  padding: 36px 0;
  font-size: 28px;
  font-weight: bold;
  text-align: center;
  background: #FF4B4B;
  color: white;
  border-radius: 14px;
  cursor: pointer;
  user-select: none;
}
"""
_CAMERA_JS = """
export default function(component) {
  const root = component.parentElement;
  const input = root.querySelector('#camera-input');
  input.addEventListener('change', () => {
    const file = input.files && input.files[0];
    if (!file) return;

    // 先把照片送進標記畫面，這是最重要、不能被打斷的一步。
    const reader = new FileReader();
    reader.onload = () => {
      component.setTriggerValue('photo', reader.result);
      input.value = "";
    };
    reader.readAsDataURL(file);

    // 本機備份下載放在後面、且獨立包起來：這只是「順便」的動作，跟上面「送進標記畫面」
    // 完全無關。之前把這段放在 reader 前面，結果在 iPhone Safari 上，跳出的「是否下載」
    // 確認視窗會讓後面送進標記畫面的程式碼整個沒執行到，畫面卡在拍照鈕、進不去下一步。
    // 實測過：Android Chrome 會靜默存進「下載」資料夾；iPhone Safari 需要手動點一下
    // 跳出視窗裡的「下載」才會真的存檔（Safari 的限制，沒辦法做到完全不用點）。
    try {
      const downloadUrl = URL.createObjectURL(file);
      const ext = file.name && file.name.includes('.') ? file.name.slice(file.name.lastIndexOf('.')) : '.jpg';
      const a = document.createElement('a');
      a.href = downloadUrl;
      a.download = 'inspection_' + Date.now() + ext;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(downloadUrl), 30000);
    } catch (e) {
      // 備份下載失敗就算了，不能影響到上面照片已經送進標記流程這件事
    }
  });
}
"""

_camera_capture = st.components.v2.component(
    "mobile_camera_capture",
    html=_CAMERA_HTML,
    css=_CAMERA_CSS,
    js=_CAMERA_JS,
)

# ---------- 連線狀態小標籤 ----------
# 實測發現：連線中斷時（例如工地訊號不穩），Streamlit 完全不會顯示任何提示，畫面看起來
# 跟平常一模一樣，使用者會搞不清楚剛剛的操作到底有沒有生效。但也實測確認：連線中斷後
# 就算長達 3 分鐘，只要恢復連線，Streamlit 會自動重新整理並接續原本的畫面，不會遺失
# 已經拍好、還沒儲存的照片——所以問題不是「會不見」，而是「不會告訴你發生什麼事」。
# 這裡加一個小標籤，定期呼叫 Streamlit 內建的健康檢查網址（/_stcore/health）確認連得到
# 伺服器，連不到就變紅色提醒，讓使用者知道要等一下、不要一直重複點擊。
_CONN_HTML = """
<div id="conn-badge" class="conn-badge">🟢 已連線</div>
"""
_CONN_CSS = """
.conn-badge {
  display: inline-block;
  padding: 6px 14px;
  border-radius: 999px;
  font-size: 14px;
  font-weight: bold;
  color: white;
  background: #1a7f37;
  margin-bottom: 10px;
}
"""
# 這段 JS 用「原始字串」（r"""）包起來：裡面的正規表示式有 \/ 這種反斜線寫法，
# 一般字串會被 Python 當成跳脫字元而發出警告，未來的版本還會直接變成錯誤。
_CONN_JS = r"""
export default function(component) {
  const root = component.parentElement;
  const badge = root.querySelector('#conn-badge');

  // 健康檢查的網址要把「目前網址的路徑」也接上去，不能只用 window.location.origin。
  // 一台電腦同時服務好幾個工地時，每個工地掛在不同路徑下（例如 /siteb），只用 origin
  // 會固定去問掛在根目錄那個工地的伺服器：變成這個工地的伺服器已經掛掉，手機卻因為
  // 另一個工地還活著而顯示綠燈「已連線」——那比沒有這個標籤更危險。
  const basePath = window.location.pathname.replace(/\/+$/, '');

  function setStatus(ok) {
    if (ok) {
      badge.textContent = '🟢 已連線';
      badge.style.background = '#1a7f37';
    } else {
      badge.textContent = '🔴 連線中斷，正在重新連線…（請勿關閉頁面，資料不會遺失）';
      badge.style.background = '#d1242f';
    }
  }

  async function ping() {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 3000);
      const res = await fetch(window.location.origin + basePath + '/_stcore/health', {
        method: 'GET', cache: 'no-store', signal: controller.signal,
      });
      clearTimeout(timer);
      setStatus(res.ok);
    } catch (e) {
      setStatus(false);
    }
  }

  window.addEventListener('online', ping);
  window.addEventListener('offline', () => setStatus(false));
  ping();
  setInterval(ping, 5000);
}
"""

_connection_status = st.components.v2.component(
    "mobile_connection_status",
    html=_CONN_HTML,
    css=_CONN_CSS,
    js=_CONN_JS,
)

_EXT_BY_MIME = {"image/jpeg": ".jpg", "image/png": ".png", "image/heic": ".heic"}


def _decode_data_url(data_url):
    """把拍照元件回傳的 data URL（例如 data:image/jpeg;base64,...）拆成 (原始 bytes, 副檔名)。"""
    header, b64data = data_url.split(",", 1)
    mime = header.split(";")[0].replace("data:", "")
    ext = _EXT_BY_MIME.get(mime, ".jpg")
    return base64.b64decode(b64data), ext


def _centered_crop_coords(width, height):
    """算出置中、比例鎖定為報告照片格的預設裁切框，讓使用者大多時候只要按確認，不用自己拖曳調整。"""
    target_ratio = CROP_ASPECT_RATIO[0] / CROP_ASPECT_RATIO[1]
    if width / height > target_ratio:
        box_h = height
        box_w = height * target_ratio
    else:
        box_w = width
        box_h = width / target_ratio
    left = round((width - box_w) / 2)
    top = round((height - box_h) / 2)
    return (left, left + round(box_w), top, top + round(box_h))


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


def _render_caption_checklist(matching_entries, selections, all_rows, date_str):
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
    # 不用 st.expander：它內建的展開箭頭圖示要另外載入字型，工地訊號不穩時常常字型
    # 載入失敗，會直接顯示圖示的英文原始碼名稱（一堆看不懂的英文字母）而不是箭頭圖案。
    # 改用純文字按鈕手動切換顯示/隱藏，箭頭符號直接用純文字符號（▼／▶），不用另外載入字型。
    toggle_key = "show_caption_checklist"
    if toggle_key not in st.session_state:
        st.session_state[toggle_key] = False
    arrow = "▼" if st.session_state[toggle_key] else "▶"
    if st.button(f"{arrow} 📋 分類清單", key=f"toggle_{toggle_key}", use_container_width=True):
        st.session_state[toggle_key] = not st.session_state[toggle_key]
    if st.session_state[toggle_key]:
        st.markdown("\n".join(lines))


def _render_tag_form(config, manifest_rows, session_pending_rows, date_str):
    """簡化版分類/說明表單（手機用，大按鈕、單欄排列），底層規則沿用 utils.py 跟 app.py 共用的樣板邏輯。"""
    category_display_names = []
    seen = set()
    for c in config["categories"]:
        dn = utils.display_name(c)
        if dn not in seen:
            seen.add(dn)
            category_display_names.append(dn)

    st.markdown("**分類**")
    category_choice = st.selectbox(
        "分類", category_display_names + [NEW_CATEGORY_OPTION], label_visibility="collapsed",
    )

    if category_choice == NEW_CATEGORY_OPTION:
        chosen_category = st.text_input("輸入新分類名稱", value="").strip()
        matching_entries = []
    else:
        chosen_category = category_choice
        matching_entries = [c for c in config["categories"] if utils.display_name(c) == chosen_category]

    material_options = next((e["material_options"] for e in matching_entries if e.get("material_options")), None)
    type_options = next((e["type_options"] for e in matching_entries if e.get("type_options")), None)

    selections = {}
    if material_options:
        st.markdown("**材料別**")
        selections["material"] = st.selectbox("材料別", options=material_options, label_visibility="collapsed")
    elif type_options:
        st.markdown("**標線種類**")
        selections["type"] = st.selectbox("標線種類", options=type_options, label_visibility="collapsed")

    _render_caption_checklist(
        matching_entries, selections, manifest_rows + session_pending_rows, date_str
    )

    rendered_captions = []
    for entry in matching_entries:
        for c in entry["captions"]:
            rendered = utils.render_caption(c, selections)
            if rendered is not None:
                rendered["owner_name"] = entry["name"]
                rendered_captions.append(rendered)

    st.markdown("**照片說明**")
    caption_options = [r["display"] for r in rendered_captions] + [NEW_CAPTION_OPTION]
    caption_choice = st.selectbox("照片說明", options=caption_options, label_visibility="collapsed")
    chosen_rendered = next((r for r in rendered_captions if r["display"] == caption_choice), None)

    if category_choice == NEW_CATEGORY_OPTION:
        real_category = chosen_category
    elif chosen_rendered is not None:
        real_category = chosen_rendered["owner_name"]
    elif matching_entries:
        real_category = matching_entries[0]["name"]
    else:
        real_category = chosen_category

    is_new_freeform_caption = caption_choice == NEW_CAPTION_OPTION
    if is_new_freeform_caption:
        final_caption = st.text_input("輸入照片說明", value="").strip()
    elif chosen_rendered["needs_value"]:
        value_text = st.text_input(
            f"{chosen_rendered['value_label']}（cm）", value="",
            placeholder=f"{chosen_rendered['value_label']}（cm）",
        ).strip()
        final_caption = utils.apply_value(chosen_rendered, value_text) if value_text else ""
    else:
        final_caption = caption_choice

    return {
        "real_category": real_category,
        "final_caption": final_caption,
        "is_new_freeform_caption": is_new_freeform_caption,
    }


def main():
    utils.ensure_dirs()
    config = utils.load_config()
    manifest_rows = utils.load_manifest()
    session_pending_rows = utils.load_session_pending()

    st.title(_PAGE_TITLE)
    _connection_status()
    st.caption(f"這台裝置待確認（尚未套用裁切/浮水印）：{len(session_pending_rows)} 張")

    if "captured_photo_bytes" not in st.session_state:
        st.session_state["captured_photo_bytes"] = None
    if "_last_camera_payload" not in st.session_state:
        st.session_state["_last_camera_payload"] = None

    if st.session_state["captured_photo_bytes"] is None:
        result = _camera_capture(on_photo_change=lambda: None)
        st.caption("拍完照片後請耐心等待畫面自動跳轉，不要重複點擊；若畫面卡住，先看上方連線狀態。")
        if result.photo and result.photo != st.session_state["_last_camera_payload"]:
            st.session_state["_last_camera_payload"] = result.photo
            photo_bytes, ext = _decode_data_url(result.photo)
            st.session_state["captured_photo_bytes"] = photo_bytes
            st.session_state["captured_ext"] = ext
            st.session_state["captured_at"] = datetime.now()
            st.rerun()
        return

    # ---------- 拍完：自動裁切預覽 + 分類/說明/日期表單 ----------
    # 不提供手動裁切工具（現場沒空慢慢框選），直接照報告版面比例自動置中裁切；
    # 這裡只是預覽用，真正的裁切座標會存進 session_pending.csv，等回辦公室按「完成本次
    # 作業」時才會真正套用（跟 app.py 的裁切工具邏輯一致，那邊需要時仍可重新調整）。
    photo_bytes = st.session_state["captured_photo_bytes"]
    original_img = ImageOps.exif_transpose(Image.open(io.BytesIO(photo_bytes)))

    left, right, top, bottom = _centered_crop_coords(*original_img.size)
    crop_rect = {"left": left, "top": top, "width": right - left, "height": bottom - top}

    st.caption("✂️ 已自動裁切成報告版面比例，以下是預覽（回辦公室後仍可重新調整）：")
    st.image(original_img.crop((left, top, right, bottom)), use_container_width=True)

    # 有些手機橫向拍照時，相片檔案本身沒有正確的方向資訊，畫面會變成側躺，這裡給一個
    # 手動旋轉的按鈕修正，不試著自動判斷方向（猜錯的機率不低，不如讓使用者自己按一下）。
    # 按下去後直接把目前這張照片的實際像素轉正、覆蓋掉暫存的照片內容，不是只轉預覽畫面，
    # 所以下面的自動裁切框跟最後存檔的照片都會是轉正後的版本。
    if st.button("🔄 旋轉90度", use_container_width=True):
        rotated_img = original_img.rotate(-90, expand=True)
        buf = io.BytesIO()
        rotated_img.convert("RGB").save(buf, format="JPEG", quality=95)
        st.session_state["captured_photo_bytes"] = buf.getvalue()
        st.session_state["captured_ext"] = ".jpg"
        st.rerun()

    today = date.today()
    photo_date = st.date_input("📅 拍照日期", value=today)

    # 施工日期記住上一張存檔時手動選的值（不是每次都跳回今天），因為夜間施工常常跨過午夜，
    # 拍照當下已經是隔天，但施工日期應該維持不變，不然每張照片都要重改一次很煩。
    # 拍照日期則不套用這個記憶，因為那個本來就該是每張照片實際拍攝的當下時間。
    remembered_construction_date = st.session_state.get("last_construction_date", today)
    construction_date = st.date_input("🏗️ 施工日期", value=remembered_construction_date)
    date_str = construction_date.strftime("%Y-%m-%d")
    photo_date_str = photo_date.strftime("%Y-%m-%d")

    tag_result = _render_tag_form(config, manifest_rows, session_pending_rows, date_str)

    save_col, retake_col = st.columns(2)
    with save_col:
        save_clicked = st.button("✅ 儲存，拍下一張", type="primary", use_container_width=True)
    with retake_col:
        retake_clicked = st.button("🔄 捨棄，重新拍攝", use_container_width=True)

    if retake_clicked:
        st.session_state["captured_photo_bytes"] = None
        st.rerun()

    if save_clicked:
        if not tag_result["real_category"]:
            st.error("請輸入新分類名稱後再儲存。")
        elif not tag_result["final_caption"].strip():
            st.error("請輸入或選擇照片說明後再儲存（若該說明需要填入 cm 數值，請確認已輸入數字）。")
        else:
            # 用 update_config 而不是「改本地 config 再整個存回去」：現場常常同時有好幾支手機
            # 在用，如果剛好在同一秒各自新增一個新分類/新說明，用鎖保護、重新讀最新資料再改，
            # 才不會其中一支手機的新增被另一支蓋掉。
            def _apply_new_category_caption(fresh_config):
                changed = False
                category_entry = next(
                    (c for c in fresh_config["categories"] if c["name"] == tag_result["real_category"]), None
                )
                if category_entry is None:
                    category_entry = {"name": tag_result["real_category"], "captions": []}
                    fresh_config["categories"].append(category_entry)
                    changed = True
                if (
                    tag_result["is_new_freeform_caption"]
                    and tag_result["final_caption"] not in category_entry["captions"]
                ):
                    category_entry["captions"].append(tag_result["final_caption"])
                    changed = True
                return changed

            utils.update_config(_apply_new_category_caption)

            ext = st.session_state["captured_ext"]
            original_name = f"camera_{st.session_state['captured_at'].strftime('%Y%m%d_%H%M%S')}{ext}"
            staged_path = utils.unique_path(utils.STAGING_DIR, original_name)
            staged_path.write_bytes(photo_bytes)

            utils.append_session_pending({
                "staged_filename": staged_path.name,
                "original_filename": original_name,
                "category": tag_result["real_category"],
                "caption": tag_result["final_caption"],
                "date": date_str,
                "photo_date": photo_date_str,
                "crop_left": crop_rect["left"],
                "crop_top": crop_rect["top"],
                "crop_width": crop_rect["width"],
                "crop_height": crop_rect["height"],
                "tagged_at": datetime.now().isoformat(timespec="seconds"),
            })

            st.session_state["captured_photo_bytes"] = None
            st.session_state["_last_camera_payload"] = None
            st.session_state["last_construction_date"] = construction_date
            st.success("已儲存！")
            st.rerun()


main()
