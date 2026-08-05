

# Construction Photo Tagging & Report Generator

Instructions written for someone who has never coded before. Just follow the steps in order.

---

## What this tool does

1. Photos get in two ways: drop them into the computer's `incoming` (waiting area) folder, or take them directly on a phone in the field
2. You open a browser screen, and for each photo you crop it, pick a category and a caption, then click save
3. Once you're happy with everything, click "Finish this session" — the app stamps the date onto each photo, moves it into the `sorted` folder, and logs it in `manifest.csv`
4. In the same browser screen, click "Generate report" to produce a Word report into the `output` folder, laid out the same way as your original sample file

---

## First-time setup (only needed once)

### 1. Install Python

Go to https://www.python.org/downloads/ and download/install the latest version of Python.

**Important (Windows users)**: near the bottom of the installer screen there's a checkbox that says **"Add python.exe to PATH"** — make sure it's checked before clicking Install.

Once installed, open VS Code, press `Ctrl + ~` (or menu Terminal → New Terminal) to open the terminal, and type:

```
python --version
```

If it shows a version number (e.g. `Python 3.12.1`), you're good.

### 2. Open this folder in VS Code

VS Code menu: File → Open Folder, then select this `inspection-photo-app` folder.

### 3. Install the required packages

In the VS Code terminal, type:

```
pip install -r requirements.txt
```

Wait for it to finish (may take a minute or two the first time). This installs the small tools this program needs, including:

- `streamlit`: lets the program run as a browser screen
- `streamlit-cropper`: lets the computer version's drag-to-crop tool work
- `python-docx`: lets the program create Word files
- `pillow`: lets the program read and crop photos
- `pillow-heif`: lets the program open `.heic` photos (the format iPhones shoot in by default)

Every package in `requirements.txt` is pinned to an exact version on purpose — read the note at the top of that file before changing any of them.

---

## Daily workflow

### Step 1: Get today's photos ready

Two ways to do this:

- **Import on the computer**: copy today's photos from your phone/cloud drive and paste them into the `incoming` folder — or point your Google Drive / OneDrive desktop sync folder path directly at this `incoming` folder, so once a photo uploads to the cloud from your phone, it shows up automatically on your computer with no manual copying
- **Take photos directly on a phone** (good for logging things on-site in real time): use a separate browser screen to shoot and upload straight from the job site — see "Step 1b: Mobile version" below

Either way, everything ends up in the same "current session" list, and you can review it all together back at the office.

**Supported file types**: `.jpg`, `.jpeg`, `.png`, and `.heic` — the format iPhones shoot in by default. You don't need to convert anything first: HEIC photos are read directly, and when you finalize a session they're saved into `sorted` as `.jpg` so Word and Windows Photo Viewer can both open them. (HEIC files are a bit slower to decode, so the "整理 incoming" thumbnail screen may take a moment the first time through a large batch.)

### Step 1b (optional): Mobile version — shooting on site

The mobile version (`mobile_app.py`) is a separate browser screen that shares the same `config.json` settings and staging data as the computer version. It's meant for taking photos directly on site without waiting until you're back at the office.

In a separate VS Code terminal tab (you can run this alongside the computer version), type:

```
streamlit run mobile_app.py --server.port 8502 --server.address 0.0.0.0
```

Open the address it prints on your phone's browser (if the phone and computer are on the same wifi, it's usually `http://<computer's-local-IP>:8502`; if you need the phone to reach the office computer over cellular data too, use the packaged installer instead — its control panel has built-in Tailscale setup, see `說明.txt` in the install package).

How it works on the phone:

- Tap the big "📷 拍照" (Take Photo) button — it opens the phone's actual camera app, not a simulated browser camera, so photo quality is normal
- A connection status badge (🟢 connected / 🔴 disconnected) sits at the top — worth watching if signal is spotty on site; a dropped connection won't lose a photo you've already taken but not yet saved
- After shooting, it auto-crops to the report's aspect ratio, centered (no manual drag-adjust on the phone — you can still fine-tune it later on the computer version); tap "🔄 旋轉90度" (Rotate 90°) if the photo came out sideways
- Pick category, material/type, and caption the same way as the computer version — including the checklist feature described below
- Tap "✅ 儲存，拍下一張" (Save, take next)

Photos taken on the phone land in the same shared staging area, so opening the computer version back at the office shows them right in the "📦 本次工作階段" (current session) list, alongside anything imported on the computer.

### Step 2: Open the tagging tool (computer version)

In the VS Code terminal, type:

```
streamlit run app.py
```

A browser window should open automatically. (If it doesn't, the terminal will print a web address like `http://localhost:8501` — copy and paste that into your browser.)

### Step 3: Tag photos one at a time

The screen shows photos from `incoming` one at a time, sorted by when they were taken (so photos from the same day appear together, making it easy to tag a whole day in a row).

If `incoming` has a bunch of photos you don't actually need to tag (e.g. unrelated photos that synced in by accident), use the "🗂️ 整理 incoming" (Organize incoming) section in the sidebar first — "挑出要忽略的照片" (pick photos to ignore) lets you check off photos to move into the `ignored` folder, so they stop showing up in the tagging screen (nothing gets deleted — you can move files back into `incoming` yourself later if you want them).

Each photo has **two separate date fields**:

- **📅 拍照日期 (Photo-taken date)**: the actual day this photo was taken. This date gets **burned directly onto the bottom-right corner of the photo** (like an old-school camera timestamp) once you finalize it with "完成本次作業" — and it's permanent from that point on.
- **🏗️ 施工日期 (Construction date)**: which day this photo should be filed under in the report — it drives the folder and report grouping. It defaults to match the photo-taken date (or whatever you picked for the previous photo), but you can change it.

This split exists for cases like: work happened on 7/1, but some inspection photos are taken that same day and others aren't taken until 7/2. Set "施工日期" to 7/1 (so the report groups it under 7/1) and let "拍照日期" reflect the real day each photo was taken. If the two dates differ, you'll see a blue notice on screen; the actual photo-taken date is still recorded in `manifest.csv` for later reference, but it's not printed into the Word report itself.

Tagging steps:

1. **✂️ Crop the photo**: the photo appears on the left, locked to the report's photo-slot aspect ratio — drag to adjust the framing
2. Confirm/adjust "拍照日期" — **automatically read from the photo's shooting info**. If it detected the wrong date (e.g. the camera's clock was off), just click the date field and correct it
3. Confirm/adjust "施工日期" — defaults to the photo-taken date; change it if this is a photo taken the day after construction
4. Choose which "分類" (category) this photo belongs to (e.g. 刨除施工照片 / milling photos), and pick a material type (DGAC/OGAC/PAC) or line type if that category has one
5. Click "▶ 📋 分類清單" (category checklist) to expand a list of today's common captions for this category — checked (✅) ones are already photographed, unchecked (⬜) ones aren't, so you can spot anything you're missing
6. Choose a "照片說明" (caption) — pick a common one from the list, or select "➕自行輸入新的說明..." at the bottom to type your own. If the list has a typo or an entry you no longer need, click the "✕" next to the dropdown to remove it
7. Click "儲存並下一張" (Save & Next)

**Note: clicking "儲存並下一張" doesn't actually stamp the photo or move it into `sorted` yet** — it just records the photo into the "📦 本次工作階段" (current session) list in the sidebar, with the crop and dates remembered but not yet final. This means that up until you finalize everything, you can pick any photo (whether imported on the computer or shot on the phone) from "回去修改已標記的照片" (go back and edit a photo from this session) in the sidebar and adjust its category, caption, crop, or dates — click "💾 更新這張" (update this one) when done.

Once everything looks right, click "✅ 完成本次作業（N 張）" (Finish this session — N photos) in the sidebar. That's the point where the crop and date stamp actually get applied, and the photos are properly filed into `sorted` and logged in `manifest.csv`.

This automatic date detection is especially useful when uploading hundreds of photos at once after a project wraps up — you don't need to keep switching the date by hand; the app reads it from each photo, and you just confirm it, then pick the category and caption.

**About screenshots and photos downloaded from LINE**: these usually don't carry shooting-time information. When that happens, you'll see a yellow warning (⚠️) telling you the app couldn't detect a real photo-taken date, and the date shown is just a guess based on the file's save time. In that case, please manually enter the correct photo-taken date — once you finalize the session, this is the date that gets stamped onto the image and it can't be changed afterward.

When you're done tagging, you can just close the browser tab, then go back to the VS Code terminal and press `Ctrl + C` to stop the program.

### Step 4: Generate the Word report

The easiest way: in the sidebar under "📄 產生報告" (Generate report), pick the construction date, click "📄 產生報告", then click "⬇️ 下載報告" (Download report) to download it directly — no terminal needed.

If you'd rather use the terminal, you can also run it as a command (replace the date with the one you want):

```
python generate_report.py 2026-04-22
```

Once finished, it will show you the path to the report, e.g.:

```
完成！報告已產生：output/查驗照片_2026-04-22.docx
```

Open the `output` folder to find the Word file (both methods produce the exact same report — use whichever is more convenient).

### Step 3b (recommended): check the day overview before generating

In the sidebar under "🔍 施工總覽" (Day overview), pick the construction date and click "🔍 檢查本日照片". You get every category for that day at once: what was shot, what's still missing, and what got shot twice. The button shows the count directly, e.g. 「🔍 檢查本日照片（1 項重複）」.

A duplicate means *same construction date, same category, identical caption text, 2 or more photos*. The comparison is deliberately on the full caption text, so:

- `AC刨除厚度5cm` and `AC刨除厚度7cm` are two different measurement points and are **not** flagged. Neither are different materials (DGAC vs PAC).
- Categories with `min_required` (交維照片) are **never** checked — shooting the same item many times is the whole point there.
- If nearly every item in a category comes in pairs, it's treated as "two road sections in one night": one note under the category heading instead of a dozen identical warnings, which would just train everyone to ignore them.

When something is flagged, the panel shows those photos side by side — same-size previews so shape and orientation don't distract from the comparison — so you can look and decide which to keep. "🗑️ 移出報告" moves the extra one out — it is **never deleted**, just moved to `ignored/`, so a wrong call is recoverable.

It's a warning only; it never blocks report generation.

---

## Two construction sites on the same day

One PC can serve several sites at once, each with its own phone link, its own photos, and its own report.

In the control panel's 「工地」 section, click 「＋ 新增工地」 and enter a name (e.g. 光復路段). It creates the site and produces a dedicated phone URL — hand a different link to each site's crew.

- Each site's photos, `manifest.csv` and reports live separately under `sites\<slug>\`.
- **The 工程設定 block (工程名稱 / 承攬廠商 / 報告標題) is per site**, stored as `site_config.json` in that site's folder — so sites belonging to different contracts or different 工務段 get the right report header. A site that hasn't set its own falls back to the values in `config.json`.
- **The category and caption list in `config.json` stays shared** across all sites: a caption added at one site appears on the other site's phones immediately. That's a company-wide rule about how inspection photos are taken, and it shouldn't fragment per site.
- The office app opens one site at a time: select it in the list, then 啟動. The panel shows which site is currently open. To switch, stop it and start again.
- The 工地 dropdown in 產生報告 is the **same selection** as the list above — they move together, so you can never be looking at site A while generating site B.
- Report filenames include the site name (`查驗照片_2026-07-23_光復路段.docx`).

**Why they must be separate:** reports are keyed on construction date. Photos from two sites in one dataset get merged into a single report for that day, and the `min_required` check sums both sites — 3 + 3 passes as 6, and nothing about the report looks wrong.

### Site names and the phone title

The phone title shows the site name (「📷 現場拍照－光復路段」) so nobody shoots into the wrong report.

A fresh install names the default site 主要工地. That's a placeholder, and it is **not** shown on the phone. Rename it to a real road section with 改名 and it appears — whether you have one site or five.

改名 changes the display name only. **The URL never changes**, so bookmarks already on a worker's phone keep working. After renaming, press 停止 then 啟動 and refresh the phone — the title is fixed when the server starts.

### Removing a site

移除工地 stops the server, takes back the phone URL, drops the entry, and **deletes that site's folder** — photos and reports included.

The delete goes to the **Windows Recycle Bin**, not a permanent erase, so a mis-click is recoverable. If the site holds anything, the confirmation states how many photos and reports are about to go rather than just asking "are you sure".

主要工地 cannot be removed: its folder *is* the installation folder, so deleting it would take the whole program with it, `venv` and `config.json` included. Use 改名 if you just want a different name.

Old data is deleted by hand: photos live in `sites\<site>\sorted\<date>\`, reports in `output\`.

---

## Want to add or change categories / captions?

Open the `config.json` file (just open it in VS Code — it's plain text, not code) and edit directly:

- `"project_name"`: the project name shown at the top of the report
- `"contractor"`: the contractor name
- `"categories"`: each category's name, along with the list of common captions under it

Save your changes, then re-run `streamlit run app.py` to pick up the new settings — no code editing needed. The "✕" button next to a category or caption in the tagging screen deletes it directly too, with the same effect as editing this file by hand.

The `captions` list can also hold advanced entries instead of plain text (this is how "鋪築施工照片" and "標線標記照片" are set up already):

- Category-level `"material_options": ["DGAC", "OGAC", "PAC"]` → shows a "材料別" dropdown when that category is selected. Any caption containing `{material}` gets it substituted, and the material code is shown in red both in the app preview and in the generated Word report.
- Category-level `"type_options": [...]` → same idea, for a two-way choice like "熱聚酯標線/臨時標線" — but not shown in red.
- A caption written as `{"template": "AC刨除厚度{value}cm", "fill_in": true, "label": "AC刨除厚度"}` → shows a blank input box when picked, and fills the number into the caption on save.
- A caption written as `{"template": "熱聚酯標線溫度", "only_type": "熱聚酯標線"}` → only appears in the list when the type dropdown matches that value.
- Category-level `"min_required": 6` → shows a live "tagged X of 6" counter in the app, and a red warning under that category's heading in the Word report if the day falls short.

You don't need to fully understand these to use them — copy the pattern from an existing category and change the text. Plain-string captions (no `{}`) work exactly as before.

---

## FAQ

**Q: The terminal shows "streamlit: command not found" or a similar error?**
The packages didn't install properly. Go back to "Install the required packages" and re-run `pip install -r requirements.txt`.

**Q: I want to tag photos from several different days at once?**
That's fine — the `incoming` folder can contain photos from multiple days mixed together. Just set "施工日期" to whichever day each photo should be filed under in the report (and let "拍照日期" reflect the real day it was taken). Then generate a report separately for each date you need one for.

**Q: Can I remove or change the date stamp burned onto a photo?**
No — the stamp only gets drawn onto the image once you click "完成本次作業", and it can't be removed or edited after that. Always double-check every photo's "拍照日期" field via "回去修改已標記的照片" in the sidebar before finalizing.

**Q: I picked the wrong category or caption, and only noticed after saving — how do I fix it?**
If you haven't clicked "完成本次作業" yet: pick that photo from the "📦 本次工作階段" dropdown in the sidebar — it opens an edit screen where you can fix the category, caption, crop, or dates, then click "💾 更新這張".
If you already clicked "完成本次作業": edit the `caption` column for that row in `manifest.csv` (open it in Excel and save) — a typo in the filename itself doesn't matter and doesn't need fixing. If the category itself was wrong, you'll also need to move the photo file inside `sorted` into the correct category's folder to match the corrected `manifest.csv` row.

**Q: I want to remove a photo from the report entirely?**
Delete the corresponding photo file from the `sorted` folder, and delete its row in `manifest.csv` (open it in Excel, delete the row, save). Then regenerate the report.

---

## Developer & operations tools

These live only in this development folder and are deliberately **not** included in the package sent to colleagues.

### `打包.bat` — build the package to hand out

Double-click it. It rebuilds the `distribute` folder from the current source files plus everything in `packaging`, using `packaging\config.範本.json` (a clean template) in place of your real `config.json`, so none of your actual site data goes out. Then zip up `distribute` and send it — the recipient extracts it and double-clicks `安裝.bat`.

The shipped instructions are the copies inside `packaging` (`README.md`, `README_zh.md`, `說明.txt`) — edit those. The copies in `distribute` get wiped and rewritten on every build.

### `reset.bat` — wipe test data

Double-click it to put this folder back to a clean "nothing tagged yet" state: it clears `incoming`, `staging`, `sorted`, `ignored`, `output` and deletes `manifest.csv` / `session_pending.csv`. It asks for confirmation first, refuses to run while either server is still up, and never touches source files, `config.json`, or `format.docx`. From a terminal, `python reset_dev_data.py --yes` skips the prompt.

`config.json` is intentionally left alone, so categories you added while testing stay. To clear those too, overwrite `config.json` by hand with `packaging\config.範本.json` and re-enter the project name and contractor.

### If you edit any `.bat` file here

Keep it pure ASCII, filename included. Under `chcp 65001`, `cmd.exe` seeks by *byte* offset while counting *characters*, so a `.bat` with much Chinese in it eventually reads from the wrong position and starts executing its own text as commands — this already happened once and overwrote the live `config.json`. Put any Chinese text and any real logic in a `.py` file and keep the `.bat` a thin launcher, the way `reset.bat` and `reset_dev_data.py` are split.

---

## Folder structure

```
inspection-photo-app/
├── incoming/              ← New photos imported on the computer, waiting to be tagged
├── staging/               ← Photos in the current session not yet finalized (managed automatically)
├── ignored/               ← Photos moved here via "整理 incoming" (nothing is deleted)
├── sorted/                ← Finalized, tagged photos, auto-organized by date/category
├── output/                ← Generated Word reports
├── packaging/             ← Files that only go into the handout package (installer, control panel, shipped READMEs)
├── distribute/            ← Build output of 打包.bat — zip this and send it (rebuilt from scratch each time)
├── sites/                 ← One folder per additional site (its own photos, manifest and reports)
├── manifest.csv           ← Log of every finalized, tagged photo (created & maintained automatically)
├── session_pending.csv    ← Log of photos in the current session not yet finalized (automatic)
├── config.json             ← Category and caption settings (edit freely, shared by all sites)
├── site_config.json        ← This site's own 工程名稱/承攬廠商/報告標題 (written by 儲存設定; absent until changed)
├── sites.json              ← The site list (maintained by 「＋ 新增工地」; absent when there's only one site)
├── format.docx             ← The original sample report the layout is copied from
├── app.py                 ← The computer tagging tool (run: streamlit run app.py)
├── mobile_app.py          ← The phone camera tool (run: streamlit run mobile_app.py --server.port 8502)
├── generate_report.py     ← The report generator (use the in-app button, or: python generate_report.py <date>)
├── utils.py               ← Shared helper code (no need to touch this)
├── 打包.bat                ← Build the handout package into distribute/
├── reset.bat              ← Wipe test data back to a clean state (dev only)
└── reset_dev_data.py      ← The actual reset logic
```

---

*A Chinese version of this file (`README_zh.md`) is also included in this folder.*
