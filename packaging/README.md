# Construction Photo Tagging & Report Generator

Instructions written for someone who has never coded before. Just follow the steps in order.

(This document covers the full feature set in detail. If you just want a quick-start version, see the shorter `說明.txt` in the same folder.)

---

## What this tool does

1. Photos get in two ways: drop them into the computer's `incoming` (waiting area) folder, or take them directly on a phone in the field
2. Open the control panel, launch the browser tool, and for each photo crop it, pick a category and a caption, then click save
3. Once you're happy with everything, click "Finish this session" — the app stamps the date onto each photo, moves it into the `sorted` folder, and logs it in `manifest.csv`
4. Click "Generate report" (in the control panel or the browser tool) to produce a Word report, laid out the same way as the original sample file

---

## First-time setup (only needed once)

1. If you received a zip file, extract it first
2. Double-click "安裝.bat" (Install)
3. If it says "偵測不到 Python" (Python not detected), follow the on-screen instructions to install from https://www.python.org/downloads/
   (make sure **"Add python.exe to PATH"** is checked near the bottom of the installer screen), then double-click "安裝.bat" again
4. Press Enter to use the default install location, or type in a folder path of your choice
5. Wait for it to finish (may take a minute or two the first time installing packages) — you're done once you see "安裝完成！" (Installation complete)

After installing, open the folder it installed into — that's where you'll work every day from now on. To update to a newer version later, just double-click "安裝.bat" again and install into the same folder — your photos, `manifest.csv`, and other data won't be overwritten or deleted.

---

## Daily workflow

### Step 1: Open the control panel

Double-click "工地照片系統.bat" (Site Photo System) in the installed folder. It opens a control panel window — everything from here on happens inside that one window, no need to remember any other files or commands. Top to bottom, the panel has five boxes:

- **工地（手機拍照連結）(Sites — phone camera links)**: one row per site, showing its name, current status, and the address phones connect to. Select a row first, then use the buttons below it: "啟動" (Start) / "停止" (Stop) for that site's mobile server, "複製網址" (Copy URL), "改名" (Rename), "＋ 新增工地" (Add site), "移除工地" (Remove site)
- **辦公室版（標記、產生報告）(Office version)**: one row per site as well. Select a site and click "開啟" (Open) — the browser opens that site's tagging screen; "停止" (Stop) shuts it down
- **工程設定 (Project settings)**: project name / contractor / report title — click "儲存設定" (Save settings). These belong to **whichever site is selected above**, so each site can differ
- **產生報告 (Generate report)**: pick a site and a construction date, click "📄 產生報告" (click "重新整理" / Refresh if a date is missing)
- **訊息記錄 (Log)**: shows what's happening and any error messages

With only one site set up, each list simply has a single row (called "主要工地" by default) — select it and use the buttons the same way.

Closing this control panel window does **not** stop any server you've already started — to stop one later, reopen "工地照片系統.bat" and click "停止" (Stop).

### Step 2 (optional): Taking photos on site with a phone

1. In the control panel's top "工地" (Sites) list, select the site you're using and click "啟動" (Start)
2. The first time you do this, you'll need to sign into Tailscale (free, sign in with a Google or Microsoft account):
   - If it's not installed, the control panel opens the download page for you automatically — install it, then click "啟動" again
   - A browser window pops up asking you to sign in — once signed in, come back to the control panel and it continues automatically
3. Once an address appears in that row's "手機網址" (Mobile URL) column (something like `https://<computer-name>.xxxxx.ts.net`), click "複製網址" (Copy URL) below and send it to the phone (LINE, text message, whatever's convenient)
4. Open that address in the phone's browser to start shooting

How it works on the phone:

- Tap the big "📷 拍照" (Take Photo) button — it opens the phone's actual camera app, not a simulated browser camera, so photo quality is normal
- A connection status badge (🟢 connected / 🔴 disconnected) sits at the top — worth watching if signal is spotty on site; a dropped connection won't lose a photo you've already taken but not yet saved
- After shooting, it auto-crops to the report's aspect ratio, centered (no manual drag-adjust on the phone — you can still fine-tune it later on the office version); tap "🔄 旋轉90度" (Rotate 90°) if the photo came out sideways
- Pick a category and material/line type; tap "▶ 📋 分類清單" (category checklist) to see which of today's common captions for this category are already photographed (✅) vs. still missing (⬜)
- Pick a "照片說明" (caption) from the list, or "➕ 自行輸入新的說明..." (enter your own) to type one
- Tap "✅ 儲存，拍下一張" (Save, take next)

Photos taken on the phone land in a shared staging area — starting "辦公室版" (Office version) back at the office shows them right in the "📦 本次工作階段" (current session) list, alongside anything imported on the computer.

Once it's running, just click "啟動" (Start) each day from then on — no more sign-in prompts. Click "停止" (Stop) when the phone doesn't need to connect anymore.

### Step 3: Tag / review photos on the computer (office version)

In the control panel's "辦公室版" (Office version) box, select the site you want and click "開啟" (Open) — the browser opens that site's screen automatically. The default site runs at `http://localhost:8501`; sites added later get their own port starting at 8511, shown in the list's "網址" (URL) column.

The top line of the sidebar is the day at a glance — "待標記 N ・ 待確認 N ・ 已完成 N" (waiting / pending review / finalized) — followed by four sections: "🗂️ 整理 incoming", "📦 本次工作階段", "🔍 施工總覽", "📄 產生報告".

If photos are being imported on the computer rather than taken on the phone, put today's photos into the `incoming` folder first — either copy them in manually, or point your Google Drive / OneDrive desktop sync folder path directly at this `incoming` folder so they show up automatically once uploaded from the phone.

**Supported file types**: `.jpg`, `.jpeg`, `.png`, and `.heic` — the format iPhones shoot in by default. You don't need to convert anything first: HEIC photos are read directly, and when you click "完成本次作業" they're saved into `sorted` as `.jpg`, so Word and Windows Photo Viewer can both open them. (HEIC is a bit slower to decode, so the "整理 incoming" thumbnail screen may take a moment the first time through a large batch — that's normal, not a hang.)

If `incoming` has a bunch of photos you don't actually need to tag (e.g. unrelated photos that synced in by accident), use "🗂️ 整理 incoming" (Organize incoming) in the sidebar first — "挑出要忽略的照片" (pick photos to ignore) lets you check off photos to move into the `ignored` folder (nothing gets deleted — you can move them back into `incoming` yourself later).

Each photo has **two separate date fields**:

- **📅 拍照日期 (Photo-taken date)**: the actual day this photo was taken. This date gets **burned directly onto the bottom-right corner of the photo** once you finalize it with "完成本次作業" — permanent from that point on.
- **🏗️ 施工日期 (Construction date)**: which day this photo should be filed under in the report. Defaults to the photo-taken date, but you can change it (e.g. work happened 7/1 but a photo wasn't taken until 7/2 — set construction date to 7/1, photo-taken date to the real day).

Tagging steps:

1. **✂️ Crop the photo**: it appears on the left, locked to the report's photo-slot aspect ratio — drag to adjust the framing
2. Confirm/adjust "拍照日期" — automatically read from the photo's shooting info; correct it if it detected the wrong date
3. Confirm/adjust "施工日期" — defaults to the photo-taken date
4. Choose a "分類" (category), and a material type (DGAC/OGAC/PAC) or line type if that category has one
5. Click "▶ 📋 分類清單" to check which of today's common captions for this category are still missing
6. Choose a "照片說明" (caption), or "➕自行輸入新的說明..." to type your own; click "✕" next to an entry to delete a typo or one you no longer need
7. Click "儲存並下一張" (Save & Next)

**Note: clicking "儲存並下一張" doesn't stamp the photo or move it into `sorted` yet** — it just records it into the "📦 本次工作階段" (current session) list in the sidebar. Before you finalize, you can pick any photo from "回去修改已標記的照片" (go back and edit a photo from this session) — whether it came from the computer or the phone — and adjust category, caption, crop, or dates, then click "💾 更新這張" (update this one).

Once everything looks right, click "✅ 完成本次作業（N 張）" (Finish this session — N photos) in the sidebar — that's when the crop and date stamp actually get applied, and photos are properly filed into `sorted` and logged in `manifest.csv`.

**About screenshots and photos downloaded from LINE**: these usually don't carry shooting-time information. You'll see a yellow warning (⚠️), and the date shown is just a guess based on the file's save time — manually enter the correct photo-taken date in that case.

When done tagging, close the browser tab and click "停止" (Stop) in the "辦公室版" box of the control panel.

### Step 3b (recommended): Check the day's overview before generating

In the sidebar under "🔍 施工總覽" (Day overview), pick a construction date and click "🔍 檢查本日照片" (Check today's photos). It lists, per category, what was shot, what's still missing, and what looks duplicated. When there are duplicates the button turns red and says how many, e.g. "🔍 檢查本日照片（1 項重複）".

"Duplicate" means: same construction date, same category, byte-identical caption text, 2 or more photos.

- `AC刨除厚度5cm` and `AC刨除厚度7cm` are two different measurement points and are **not** flagged; neither are different materials (DGAC vs PAC)
- Categories that are supposed to have many shots of the same item (交維照片) are **never** checked
- If nearly every item in a category comes in pairs, it's treated as "two road sections in one night" — a single note under the category instead of a dozen identical warnings

Flagged photos are shown side by side (equal-sized previews, so portrait/landscape doesn't skew the comparison). Click "🗑️ 移出報告" under the one you don't want — it is **never deleted**, just moved to `ignored`, so a wrong call is recoverable.

It's a warning only; it never blocks report generation.

### Step 4: Generate the Word report

Either way works:

- **Control panel**: under "產生報告" (Generate report), pick a site and a date, click "📄 產生報告" — it'll offer to open the folder the report was saved into
- **Office version browser screen**: in the sidebar, pick a date under "📄 產生報告", click the button, then "⬇️ 下載報告" (Download report) to download directly

Both produce the exact same report, saved into the `output` folder.

---

## Two sites under construction on the same day

One computer can serve several sites at once — each with its own phone URL, its own photos, and its own reports.

In the control panel's top "工地" (Sites) box, click "＋ 新增工地" (Add site) and type a name (e.g. 光復路段). It gets created with its own phone URL; hand out the right URL to the right crew.

- Each site's photos, `manifest.csv`, and reports live separately under `sites\<slug>\`
- **Project name / contractor / report title are per-site** — select the site, then edit "工程設定". Sites without their own settings fall back to `config.json`
- **Categories and captions stay shared** across all sites: a caption added at site A shows up on site B's phone immediately. That's a company-wide rule about how inspection photos are shot, not a per-site thing
- Report filenames carry the site name (e.g. `查驗照片_2026-07-23_光復路段.docx`)

**Why they must stay separate**: reports are indexed by construction date. Mixed together, two sites' photos on the same day collapse into one report — and the `min_required` check for 交維照片 would add both sides together, so 3 + 3 passes as 6 with nothing on the report looking wrong.

### Site names and the phone's title

The phone screen shows the site name in its title (e.g. "📷 現場拍照－光復路段") so nobody shoots with the wrong link open. A fresh install calls the default site "主要工地", which is a placeholder and is **not** shown on the phone; rename it to the real road section and it appears.

"改名" (Rename) changes the displayed name only — **the phone URL stays the same**, so bookmarks keep working. Stop and start the server afterwards for the phone title to update.

### Removing a site

"移除工地" (Remove site) stops the server, releases the phone URL, removes the row, and **deletes that site's folder** (photos and reports included). It goes to the Windows Recycle Bin rather than being erased, so a mistake is recoverable, and the confirmation tells you exactly how many photos and reports are about to go.

"主要工地" can't be removed — its folder is the program's own folder. Rename it instead.

---

## Want to change the project name/contractor, or add/edit categories and captions?

- **Project name, contractor, report title**: edit directly in the control panel's "工程設定" (Project settings) fields and click "儲存設定" (Save settings)
- **Categories and common captions**: open `config.json` (just open it in Notepad — it's plain text) and edit:
  - `"categories"`: each category's name, along with the list of common captions under it

  Save, then restart the office version to pick up the change — no code editing needed. The "✕" button next to a category or caption in the tagging screen deletes it directly too, with the same effect.

The `captions` list can also hold advanced entries instead of plain text (this is how "鋪築施工照片" and "標線標記照片" are set up already):

- Category-level `"material_options": ["DGAC", "OGAC", "PAC"]` → shows a "材料別" dropdown when that category is selected. Any caption containing `{material}` gets it substituted, and the material code is shown in red both in the app preview and in the generated Word report.
- Category-level `"type_options": [...]` → same idea, for a two-way choice like "熱聚酯標線/臨時標線" — but not shown in red.
- A caption written as `{"template": "AC刨除厚度{value}cm", "fill_in": true, "label": "AC刨除厚度"}` → shows a blank input box when picked, and fills the number into the caption on save.
- A caption written as `{"template": "熱聚酯標線溫度", "only_type": "熱聚酯標線"}` → only appears in the list when the type dropdown matches that value.
- Category-level `"min_required": 6` → shows a live "tagged X of 6" counter in the app, and a red warning under that category's heading in the Word report if the day falls short.

You don't need to fully understand these to use them — copy the pattern from an existing category and change the text.

---

## FAQ

**Q: "安裝.bat" says "偵測不到 Python" (Python not detected)?**
Install it from https://www.python.org/downloads/, making sure to check "Add python.exe to PATH", then double-click "安裝.bat" again.

**Q: The phone shows "can't connect to this site" when opening the address?**
Go back to the control panel and check that site's "狀態" (Status) column in the "工地" list — if it shows "未啟動" (Not started) instead of "執行中" (Running), select the row and click "啟動" (Start) again.

**Q: Can I shut down this computer?**
Not if you want the site phone to keep connecting — the control panel window itself can be closed, but that site's mobile server needs to stay running. If you're only tagging/generating reports at the office, click "停止" (Stop) in the "辦公室版" box first, then it's fine to shut down.

**Q: Can I remove or change the date stamp burned onto a photo?**
No — the stamp only gets drawn onto the image once you click "完成本次作業", and it can't be removed or edited after that. Always double-check every photo's "拍照日期" via "回去修改已標記的照片" in the sidebar before finalizing.

**Q: I picked the wrong category or caption, and only noticed after saving — how do I fix it?**
If you haven't clicked "完成本次作業" yet: pick that photo from the "📦 本次工作階段" dropdown in the sidebar, fix it in the edit screen, then click "💾 更新這張".
If you already clicked "完成本次作業": edit the `caption` column for that row in `manifest.csv` (open in Excel and save). If the category was wrong too, also move the photo file inside `sorted` into the correct category's folder.

**Q: I want to remove a photo from the report entirely?**
Delete the corresponding photo file from `sorted`, delete its row in `manifest.csv`, save, then regenerate the report.

**Q: I want to tag photos from several different days at once?**
That's fine — `incoming` can contain photos from multiple days mixed together. Just set "施工日期" to whichever day each photo should be filed under, then generate a report separately per date.

---

## Folder structure

```
工地照片系統/ (the folder created after installing)
├── incoming/              ← New photos imported on the computer, waiting to be tagged
├── staging/               ← Photos in the current session not yet finalized (managed automatically)
├── ignored/               ← Photos moved here via "整理 incoming" (nothing is deleted)
├── sorted/                ← Finalized, tagged photos, auto-organized by date/category
├── output/                ← Generated Word reports
├── sites/                 ← One folder per additional site (its photos, manifest, reports)
├── venv/                  ← The program's own Python environment (don't touch)
├── manifest.csv           ← Log of every finalized, tagged photo (automatic)
├── session_pending.csv    ← Log of photos in the current session not yet finalized (automatic)
├── config.json             ← Category and caption settings (shared by every site)
├── site_config.json        ← This site's project name / contractor / report title (maintained by "儲存設定")
├── sites.json              ← The site list (maintained by "＋ 新增工地")
├── 工地照片系統.bat         ← Double-click to open the control panel (start here every day)
├── 說明.txt                ← Short quick-start instructions
├── control_panel.py       ← The control panel program itself
├── app.py                  ← The office tagging tool
├── mobile_app.py           ← The phone camera tool
├── generate_report.py      ← The report generator
└── utils.py                 ← Shared helper code (no need to touch this)
```

---

*繁體中文版說明請見同資料夾裡的 `README_zh.md`。*
