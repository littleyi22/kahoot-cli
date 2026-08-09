#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kahoot CLI —— 讓 AI 助理控制 Kahoot! 進行自動化出題。
專屬助手: 基於 wordwall-cli 簡化改編，專注於 Kahoot! 的 Playwright 自動化。
"""

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

# ---- 路徑與常數設定 ----
CONFIG_DIR = Path.home() / ".kahoot"
STATE_FILE = CONFIG_DIR / "state.json"                # 登入後的 cookies 儲存檔案
CHROME_LOGIN_FILE = CONFIG_DIR / "chrome-login.json"  # 記錄啟動的專用 Chrome 連線資訊
CHROME_LOGIN_PROFILE = CONFIG_DIR / "chrome-login-profile"
DEFAULT_CDP_PORT = 9334
DEBUG_DIR = Path(__file__).resolve().parent / "debug"
BASE_URL = "https://create.kahoot.it"

def die(msg: str, code: int = 1):
    """列印錯誤訊息並結束程式。"""
    print(f"[錯誤] {msg}", file=sys.stderr)
    sys.exit(code)

def _need_playwright():
    """延遲載入 Playwright，並在缺少時給予友善提示。"""
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        die("尚未安裝 Playwright。請執行:\n"
            "    python -m pip install -r requirements.txt\n"
            "    python -m playwright install chromium\n"
            "或執行一鍵安裝腳本: .\\setup.ps1")

def _find_chrome(chrome_path: str | None = None) -> Path:
    """尋找系統中的 Google Chrome 執行檔路徑。"""
    if chrome_path:
        candidate = Path(chrome_path).expanduser().resolve()
        if candidate.is_file():
            return candidate
        die(f"找不到指定的 Chrome: {candidate}", code=4)
    
    # 預設名稱
    for name in ("chrome.exe", "chrome", "google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            return Path(found).resolve()
            
    # Windows/macOS/Linux 的常見安裝路徑
    candidates = []
    if sys.platform == "win32":
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            root = os.environ.get(variable)
            if root:
                candidates.append(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe")
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    else:
        candidates.extend((Path("/usr/bin/google-chrome"), Path("/usr/bin/google-chrome-stable")))
        
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
            
    die("找不到 Google Chrome。請安裝 Chrome，或用 --chrome-path 指定執行檔路徑。", code=4)

def _port_is_available(port: int) -> bool:
    """確認本機除錯埠尚未被其他工具占用。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False

def _resolve_grab_session_cdp_url(explicit_url: str | None) -> str:
    """決定 CDP 連線網址，優先使用上次 Chrome 登入紀錄。"""
    if explicit_url:
        return explicit_url.rstrip("/")
    if not CHROME_LOGIN_FILE.is_file():
        die("找不到本工具啟動的 Chrome 紀錄。請先執行:\n"
            "    python kahoot.py chrome-login\n"
            "本人登入完成後，再執行 python kahoot.py grab-session。", code=4)
    try:
        metadata = json.loads(CHROME_LOGIN_FILE.read_text(encoding="utf-8"))
        port = int(metadata["port"])
    except Exception:
        die(f"Chrome 登入紀錄已損壞: {CHROME_LOGIN_FILE}\n請重新執行 python kahoot.py chrome-login。", code=4)
        
    return f"http://127.0.0.1:{port}"

def _get_browser_context(p, headless: bool, profile_dir: Path):
    """
    獲取 Playwright 瀏覽器 Context。
    優先嘗試連接現有的 CDP 偵錯埠。
    如果連不上，則啟動帶有真實 Chrome Profile 的 Persistent Context。
    """
    # 1. 嘗試連接現有的 CDP
    try:
        import urllib.request
        port = 9334
        if CHROME_LOGIN_FILE.is_file():
            try:
                metadata = json.loads(CHROME_LOGIN_FILE.read_text(encoding="utf-8"))
                port = int(metadata.get("port", 9334))
            except Exception:
                pass
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as response:
            if response.status == 200:
                print(f"[資訊] 偵測到已開啟的專用 Chrome (Port {port})，將直接接管視窗進行出題...")
                browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                if browser.contexts:
                    return browser, browser.contexts[0], True
    except Exception:
        pass
        
    # 2. 如果連不上，啟動 Persistent Context
    print(f"[資訊] 啟動專屬真實 Chrome Profile 進行出題... (Headless: {headless})")
    pdir = profile_dir.expanduser().resolve()
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(pdir),
        headless=headless,
        channel="chrome",
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    return None, context, False

def _dump_debug(page, name: str):
    """當出錯時，自動保存螢幕截圖與 HTML 供日後排除錯誤。"""
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        screenshot_path = DEBUG_DIR / f"{name}_{timestamp}.png"
        html_path = DEBUG_DIR / f"{name}_{timestamp}.html"
        
        page.screenshot(path=str(screenshot_path))
        html_path.write_text(page.content(), encoding="utf-8")
        print(f"[偵錯] 已儲存錯誤畫面至:\n  截圖: {screenshot_path}\n  HTML: {html_path}", file=sys.stderr)
    except Exception as e:
        print(f"[偵錯] 無法儲存偵錯資訊: {e}", file=sys.stderr)

# ---- 指令實作 ----

def cmd_chrome_login(args):
    """啟動專用 Chrome 供使用者手動登入。"""
    chrome_path = _find_chrome(args.chrome_path)
    port = args.port
    
    if not _port_is_available(port):
        die(f"除錯埠 {port} 已被占用，請嘗試其他埠（例如 --port 9335）或關閉占用它的程式。")
        
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    profile_dir = CHROME_LOGIN_PROFILE.expanduser().resolve()
    
    # 紀錄此次啟動資訊
    metadata = {
        "port": port,
        "profile_dir": str(profile_dir),
        "timestamp": time.time()
    }
    CHROME_LOGIN_FILE.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    
    # 組裝 Chrome 啟動參數
    cmd = [
        str(chrome_path),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "https://create.kahoot.it/auth/login"
    ]
    
    print(f"[資訊] 正在啟動專用 Chrome (Port: {port})...")
    print("[提示] 請在開啟的 Chrome 中登入您的 Kahoot! 帳號。")
    print("[提示] 登入成功並看到 Dashboard 後，請回到此視窗執行:")
    print("       python kahoot.py grab-session")
    
    # 以獨立進程啟動 Chrome，不阻塞 CLI
    if sys.platform == "win32":
        subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def cmd_grab_session(args):
    """從偵錯 Chrome 抓取 cookie 與 localStorage/sessionStorage 並保存。"""
    cdp_url = _resolve_grab_session_cdp_url(args.cdp_url)
    sync_playwright = _need_playwright()
    
    print(f"[資訊] 正在連線至 Chrome ({cdp_url})...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(cdp_url)
            # 取得主要 Context
            contexts = browser.contexts
            if not contexts:
                die("在 Chrome 中找不到任何活動中的視窗。請確認專用 Chrome 仍開著。")
            
            context = contexts[0]
            cookies = context.cookies()
            
            # 取得活躍頁面的 localStorage 與 sessionStorage (通常是 create.kahoot.it 相關的頁面)
            local_storage = {}
            session_storage = {}
            target_page = None
            for page in context.pages:
                if "kahoot.it" in page.url or "kahoot.com" in page.url:
                    target_page = page
                    break
            if not target_page and context.pages:
                target_page = context.pages[0]
                
            if target_page:
                try:
                    local_storage_json = target_page.evaluate("() => JSON.stringify(localStorage)")
                    local_storage = json.loads(local_storage_json)
                except Exception as e:
                    print(f"[警告] 無法讀取 localStorage: {e}")
                try:
                    session_storage_json = target_page.evaluate("() => JSON.stringify(sessionStorage)")
                    session_storage = json.loads(session_storage_json)
                except Exception as e:
                    print(f"[警告] 無法讀取 sessionStorage: {e}")
            
            # 儲存登入憑證
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            state_data = {
                "cookies": cookies,
                "local_storage": local_storage,
                "session_storage": session_storage,
                "grabbed_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            STATE_FILE.write_text(json.dumps(state_data, indent=2), encoding="utf-8")
            print(f"[成功] 登入狀態已成功儲存至: {STATE_FILE}")
            
    except Exception as e:
        die(f"連線或抓取 Session 失敗: {e}\n請確認您已執行 chrome-login 且 Chrome 視窗仍在運行。")

def _inject_storage(page, local_storage, session_storage):
    """注入 localStorage 與 sessionStorage 到頁面中。"""
    ls_script = ""
    for k, v in local_storage.items():
        k_json = json.dumps(k)
        v_json = json.dumps(v)
        ls_script += f"localStorage.setItem({k_json}, {v_json});\n"
        
    ss_script = ""
    for k, v in session_storage.items():
        k_json = json.dumps(k)
        v_json = json.dumps(v)
        ss_script += f"sessionStorage.setItem({k_json}, {v_json});\n"
        
    init_script = f"""
    try {{
        {ls_script}
        {ss_script}
    }} catch(e) {{
        console.error('Failed to inject storage:', e);
    }}
    """
    page.add_init_script(init_script)

def cmd_check(args):
    """驗證本地 Session 是否仍有效。"""
    if not STATE_FILE.is_file():
        die("尚未登入。請先執行 chrome-login 及 grab-session。", code=2)
        
    sync_playwright = _need_playwright()
    
    with sync_playwright() as p:
        # 專屬助手: 預設使用傳入的 headless 設定，並套用真實 User-Agent 避開機器人檢測
        headless = getattr(args, "headless", True)
        browser = p.chromium.launch(headless=headless, channel="chrome")
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            context.add_cookies(state.get("cookies", []))
        except Exception as e:
            die(f"讀取登入檔案失敗: {e}，請重新登入。")
            
        page = context.new_page()
        _inject_storage(page, state.get("local_storage", {}), state.get("session_storage", {}))
        print("[資訊] 正在驗證登入狀態...")
        
        try:
            # 訪問 Library 頁面，看是否會被重新導向到 login
            page.goto("https://create.kahoot.it/my-library/kahoots")
            page.wait_for_timeout(3000) # 給予緩衝時間載入
            
            current_url = page.url
            if "auth/login" in current_url or "login" in current_url:
                print(f"[失效] 登入 Session 已過期。當前網址: {current_url}")
                _dump_debug(page, "check_failed")
                sys.exit(2)
            else:
                print("[OK] 登入有效。可以正常操作！")
        except Exception as e:
            print(f"[錯誤] 驗證過程發生異常: {e}")
            _dump_debug(page, "check_error")
            sys.exit(2)

def cmd_doctor(args):
    """環境診斷。"""
    print("===== kahoot-cli 環境診斷 =====")
    
    # 1. 檢查 Python 版本
    py_ver = sys.version_info
    print(f"Python 版本: {py_ver.major}.{py_ver.minor}.{py_ver.micro} -> [OK]")
    
    # 2. 檢查 Playwright
    try:
        import playwright
        print("Playwright 套件: 已安裝 -> [OK]")
    except ImportError:
        print("Playwright 套件: 未安裝 -> [FAIL] (請執行 pip install playwright)")
        
    # 3. 檢查 Chromium
    sync_playwright = None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
        print("Chromium 瀏覽器: 可正常啟動 -> [OK]")
    except Exception as e:
        print(f"Chromium 瀏覽器: 啟動失敗 -> [FAIL] ({e})")
        print("  請執行: python -m playwright install chromium")
        
    # 4. 檢查 Session
    if STATE_FILE.is_file():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            cookies_count = len(state.get("cookies", []))
            print(f"本地登入狀態: 已儲存 ({cookies_count} 個 cookies，擷取於 {state.get('grabbed_at', '未知')}) -> [OK]")
        except Exception:
            print("本地登入狀態: 檔案損壞 -> [FAIL]")
    else:
        print("本地登入狀態: 尚未登入 -> [WARNING] (請執行 python kahoot.py chrome-login)")
        
    print("===============================")

def _handle_popups(page):
    """關閉編輯器中可能跳出的各種引導或通知對話框。"""
    page.wait_for_timeout(1000)
    # 按 Escape 關閉大部分彈窗
    page.keyboard.press("Escape")
    
    # 嘗試點擊可能存在的 Got it / Close 鈕
    popup_selectors = [
        "button:has-text('Got it')",
        "button:has-text('Maybe later')",
        "button:has-text('Skip')",
        "button[aria-label='Close']",
        "[data-testid='onboarding-close-button']",
        ".welcome-popup__close-btn"
    ]
    for sel in popup_selectors:
        try:
            if page.locator(sel).is_visible():
                page.locator(sel).click(timeout=1000)
        except Exception:
            pass

def _find_and_select_image(page, query: str):
    """在 Kahoot! 媒體庫搜尋圖片並選擇第一張。"""
    try:
        # 關閉任何可能因為剛才填答而殘留的 Rich-text 工具列或對話框
        page.keyboard.press("Escape")
        _handle_popups(page)
        
        # 專屬助手: 1. 點擊 Add media 鈕，只使用最精準的功能定位器，避免點錯到左側的「+ 新增」題目按鈕
        media_button = page.locator("[data-functional-selector='media-library-info-view__add-media-button']")
        if media_button.count() > 0:
            media_button.first.click(force=True)
            page.wait_for_timeout(2000) # 給予媒體庫彈出視窗加載時間
        else:
            print(f"    [警告] 找不到 Add media 按鈕，跳過圖片搜尋: {query}")
            return
            
        # 2. 在搜尋框中填入關鍵字
        search_input = page.locator("[data-functional-selector='media-library-dialog__search__input'], input[placeholder='Search...'], input[placeholder='搜尋...'], input[type='search']")
        try:
            search_input.first.wait_for(state="visible", timeout=5000)
            # 專屬助手: 優先使用 click & press_sequentially 模擬真實鍵盤輸入以觸發 React 狀態更新，並先 Control+A & Backspace 清除舊內容
            search_input.first.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            search_input.first.press_sequentially(query, delay=100)
            page.wait_for_timeout(500)
            page.keyboard.press("Enter")
            # 專屬助手: 搜尋後強制等待 3 秒以讓 Getty 網格更新，防範點到搜尋前的舊預設熱門圖片
            page.wait_for_timeout(3000)
        except Exception as e:
            print(f"    [警告] 搜尋輸入框操作失敗 ({e})，跳過圖片搜尋: {query}")
            _dump_debug(page, f"image_search_failed_{query.replace(' ', '_')}")
            page.keyboard.press("Escape")
            return
            
        # 3. 點擊搜尋結果的第一張圖片
        image_items = page.locator("[data-functional-selector='media-library-dialog__image-grid__image'], [data-testid*='search-result-item'], .image-library-item, .search-result button")
        try:
            image_items.first.wait_for(state="visible", timeout=5000)
            image_items.first.click()
            page.wait_for_timeout(2000) # 等待圖片載入完成
            print(f"    [成功] 已選擇圖片搜尋結果的第一張圖: {query}")
        except Exception as e:
            print(f"    [提示] 選擇圖片結果失敗 ({e})，關鍵字 '{query}' 未搜尋到合適的圖片，跳過。")
            _dump_debug(page, f"image_select_failed_{query.replace(' ', '_')}")
            page.keyboard.press("Escape")
            
    except Exception as e:
        print(f"    [錯誤] 圖片搜尋操作失敗 ({query}): {e}")
        page.keyboard.press("Escape")

def _upload_local_image(page, image_path: Path):
    """上傳本機圖片。"""
    try:
        # 點擊 "Add media" 或上傳區域
        # 尋找 file input
        file_input = page.locator("input[type='file']")
        if file_input.count() > 0:
            file_input.first.set_files(str(image_path))
            page.wait_for_timeout(3000) # 等待上傳
            print(f"    [成功] 已上傳本機圖片: {image_path.name}")
        else:
            # 如果沒有直接的 file input，點擊 Add media 開啟視窗再找
            media_button = page.locator("[data-testid='media-add-button'], button:has-text('Add media')")
            if media_button.count() > 0:
                media_button.first.click()
                page.wait_for_timeout(1000)
                
            file_input = page.locator("input[type='file']")
            if file_input.count() > 0:
                file_input.first.set_files(str(image_path))
                page.wait_for_timeout(3000)
                print(f"    [成功] 已上傳本機圖片: {image_path.name}")
            else:
                print(f"    [警告] 找不到檔案上傳元件，無法上傳: {image_path}")
    except Exception as e:
        print(f"    [錯誤] 本機圖片上傳失敗: {e}")

def cmd_create(args):
    """讀取 JSON 並自動建立 Kahoot! 遊戲。"""
    json_path = Path(args.content).resolve()
    if not json_path.is_file():
        die(f"找不到題目 JSON 檔案: {json_path}")
        
    # 讀取並檢驗 JSON 格式
    try:
        content = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as e:
        die(f"題目 JSON 格式錯誤: {e}")
        
    title = content.get("title", "未命名 Kahoot")
    description = content.get("description", "")
    questions = content.get("questions", [])
    
    if not questions:
        die("JSON 檔案中沒有題目。")
        
    # 互動式付費帳號詢問
    is_premium = args.premium
    has_premium_questions = any(q.get("type") in ("type_answer", "puzzle", "jumble", "word_cloud", "poll", "survey") for q in questions)
    if has_premium_questions and not is_premium:
        try:
            if sys.stdin.isatty():
                ans = input("[提示] 偵測到您的題目中包含進階/付費題型。請問您的 Kahoot! 帳號是付費/進階帳號嗎？(y/N): ")
                if ans.strip().lower() in ('y', 'yes'):
                    is_premium = True
                else:
                    die("免費版帳號不支援建立進階題型。請先移除付費題型，或升級您的 Kahoot! 帳號。")
            else:
                die("偵測到進階/付費題型，非互動終端請加上 --premium 參數以宣告您擁有付費帳號。")
        except Exception:
            die("偵測到進階/付費題型，請在指令加上 --premium 參數以宣告您擁有付費帳號。")

    # 預檢：驗證每個題目的必要欄位
    for idx, q in enumerate(questions):
        q_text = q.get("question")
        q_type = q.get("type", "quiz")
        answers = q.get("answers", [])
        correct = q.get("correct")
        
        if not q_text:
            die(f"第 {idx+1} 題缺少 question (題幹)")
            
        # 根據不同題型定義驗證規則
        if q_type == "type_answer":
            min_answers = 1
        elif q_type == "word_cloud":
            min_answers = 0
        elif q_type in ("puzzle", "jumble"):
            min_answers = 4 # 排列解謎必須 4 個選項
        else:
            min_answers = 2
            
        if min_answers > 0:
            if not isinstance(answers, list) or len(answers) < min_answers:
                die(f"第 {idx+1} 題 ({q_type}) 答案選項數量必須大於等於 {min_answers} 個 (answers)")
                
        # 只有測驗題與簡答題需要驗證 correct 欄位
        if q_type in ("quiz", "type_answer"):
            if correct is None:
                correct = 0
            if not (0 <= correct < len(answers)):
                die(f"第 {idx+1} 題正確答案索引 (correct) 無效，應在 0 到 {len(answers)-1} 之間。")

    if args.dry_run:
        print("[Dry Run] 題目預檢通過！")
        print(f"  活動標題: {title}")
        print(f"  題目數量: {len(questions)} 題")
        sys.exit(0)
        
    # 開始 Playwright 自動化
    # 專屬助手: 優先使用 launch_persistent_context 以共用 Profile 狀態，若無 state.json 則檢查
    if not STATE_FILE.is_file() and not CHROME_LOGIN_PROFILE.is_dir():
        die("尚未登入。請先執行 chrome-login。")
        
    sync_playwright = _need_playwright()
    
    with sync_playwright() as p:
        browser, context, is_cdp = _get_browser_context(p, args.headless, CHROME_LOGIN_PROFILE)
        
        # 決定 page
        if is_cdp:
            page = None
            for p_page in context.pages:
                if "kahoot.it" in p_page.url or "kahoot.com" in p_page.url:
                    page = p_page
                    break
            if not page:
                page = context.new_page()
        else:
            page = context.new_page()
            
        # 備用注入 Session (以防 Persistent Context 的 cookie 過期)
        if STATE_FILE.is_file():
            try:
                state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                context.add_cookies(state.get("cookies", []))
                _inject_storage(page, state.get("local_storage", {}), state.get("session_storage", {}))
            except Exception as e:
                print(f"[警告] 嘗試備份載入 Session 失敗 (通常無礙): {e}")
        
        try:
            # 1. 進入 Kahoot Creator 頁面
            print("[步驟 1/5] 正在載入 Kahoot! Creator...")
            page.goto(f"{BASE_URL}/creator")
            page.wait_for_load_state("networkidle")
            
            # 檢查是否被登出
            if "auth/login" in page.url or "login" in page.url:
                die("登入狀態已失效，請重新執行 chrome-login 及 grab-session。")
                
            _handle_popups(page)
            
            # 2. 設定 Kahoot 標題與描述
            print("[步驟 2/5] 設定活動標題與描述...")
            # 點擊左上角 Settings/設定 鈕
            settings_btn = page.locator("[data-functional-selector='top-bar__kahoot-summary-button'], [data-testid='settings-button'], button:has-text('Settings'), button:has-text('設定')")
            if settings_btn.count() > 0:
                settings_btn.first.click()
                page.wait_for_timeout(1000)
                
                # 填寫標題
                title_input = page.locator("[data-functional-selector='dialog-information-kahoot__kahoot_title_input'], #title, [data-testid='settings-title']")
                title_input.first.fill(title)
                
                # 填寫描述
                desc_input = page.locator("[data-functional-selector='dialog-information-kahoot__kahoot_description_textarea'], #description, [data-testid='settings-description']")
                if desc_input.count() > 0 and description:
                    desc_input.first.fill(description)
                    
                # 點擊 Done 儲存設定
                done_btn = page.locator("[data-functional-selector='dialog-information-kahoot__done-button'], button:has-text('Done'), button:has-text('完成'), [data-testid='settings-done-button']")
                done_btn.first.click()
                page.wait_for_timeout(1000)
            else:
                print("  [警告] 找不到 Settings 按鈕，跳過標題設定。")
                
            # 3. 逐題填寫
            print(f"[步驟 3/5] 開始填寫題目 (共 {len(questions)} 題)...")
            
            # 專屬助手: 檢查第一題是不是非預設 Quiz 題。如果是，我們在出完所有題後，將第 1 張臨時投影片刪除。
            has_first_dummy_slide = (questions[0].get("type", "quiz") != "quiz")
            actual_questions = questions.copy()
            if has_first_dummy_slide:
                actual_questions.insert(0, {
                    "question": "臨時題目（即將自動刪除）",
                    "answers": ["1", "2", "3", "4"],
                    "correct": 0,
                    "type": "quiz"
                })
                
            for idx, q in enumerate(actual_questions):
                q_text = q.get("question")
                q_type = q.get("type", "quiz")
                answers = q.get("answers", [])
                correct = q.get("correct")
                time_limit = q.get("time_limit", 20)
                
                print(f"  -> 正在填寫第 {idx+1} 題 ({q_type}): {q_text[:20]}...")
                
                # 如果不是第一題，需要點擊 "Add question" 新增題目
                if idx > 0:
                    add_q_btn = page.locator("[data-functional-selector='add-question-button'], [data-testid='add-question-button'], button:has-text('Add question'), button:has-text('新增')")
                    add_q_btn.first.click()
                    page.wait_for_timeout(1000)
                    
                    if q_type == "type_answer":
                        # 選擇簡答題 (Type Answer) 題型
                        type_answer_btn = page.locator("[data-functional-selector='create-button__open-ended'], [data-testid='add-question-short_answer'], [data-testid='add-question-type-answer'], button:has-text('Type answer'), button:has-text('簡答題')")
                        type_answer_btn.first.click()
                    elif q_type in ("puzzle", "jumble"):
                        # 選擇排列解謎 (Puzzle) 題型
                        puzzle_btn = page.locator("[data-functional-selector='create-button__jumble'], button:has-text('Puzzle'), button:has-text('排列解謎')")
                        puzzle_btn.first.click()
                    elif q_type == "word_cloud":
                        # 選擇文字雲 (Word Cloud) 題型
                        word_cloud_btn = page.locator("[data-functional-selector='create-button__word-cloud'], button:has-text('Word cloud'), button:has-text('文字雲')")
                        word_cloud_btn.first.click()
                    elif q_type in ("poll", "survey"):
                        # 選擇票選活動 (Poll) 題型
                        poll_btn = page.locator("[data-functional-selector='create-button__survey'], button:has-text('Poll'), button:has-text('票選活動')")
                        poll_btn.first.click()
                    else:
                        # 選擇 "Quiz" (測驗) 題型
                        quiz_type_btn = page.locator("[data-testid='add-question-quiz'], button:has-text('Quiz'), button:has-text('測驗')")
                        quiz_type_btn.first.click()
                    page.wait_for_timeout(1000)
                
                _handle_popups(page)
                
                # A. 填寫題幹
                question_editor = page.locator("[data-functional-selector='question-title__input'], [data-testid='question-text-editor'], [placeholder='Start typing your question'], [data-placeholder='開始輸入你的題目']")
                question_editor.first.click()
                question_editor.first.fill(q_text)
                
                # B. 填寫答案與勾選
                if q_type == "type_answer":
                    # 簡答題：填寫正確答案輸入框
                    open_ended_input = page.locator("input[data-functional-selector='question-answer__input'], [data-testid='open-ended-answer-input-0']")
                    open_ended_input.first.click()
                    ans_text = answers[correct] if (correct is not None and correct < len(answers)) else (answers[0] if answers else "")
                    open_ended_input.first.fill(ans_text)
                elif q_type == "word_cloud":
                    # 文字雲：不填寫答案項目
                    pass
                elif q_type in ("puzzle", "jumble", "poll", "survey"):
                    # 排列解謎 & 票選活動：依序填寫 4 個/多個答案，無須 correctness 勾選
                    for a_idx, ans in enumerate(answers):
                        if a_idx >= 4:
                            break
                        ans_input = page.locator("[data-functional-selector='dnd-choice__input'], [data-functional-selector='question-answer__input']").nth(a_idx)
                        ans_input.click()
                        ans_input.fill(ans)
                else:
                    # 測驗題：填寫 4 個選項並勾選
                    for a_idx, ans in enumerate(answers):
                        if a_idx >= 4:
                            break
                        ans_input = page.locator("[data-functional-selector='question-answer__input']").nth(a_idx)
                        ans_input.click()
                        ans_input.fill(ans)
                        
                        if a_idx == correct:
                            correct_chk = page.locator("[data-functional-selector='question-answer__toggle-button']").nth(a_idx)
                            correct_chk.click()
                        
                # C. 處理圖片 (優先上傳本機 -> 其次搜尋)
                if q.get("image"):
                    img_path = json_path.parent / q.get("image")
                    if img_path.is_file():
                        print(f"    上傳本機圖片: {img_path.name}")
                        _upload_local_image(page, img_path)
                    else:
                        print(f"    [警告] 找不到本機圖片檔案: {img_path}")
                        
                elif q.get("image_search"):
                    query = q.get("image_search")
                    print(f"    搜尋線上圖片: {query}")
                    _find_and_select_image(page, query)
                    
                # D. 設定時間限制 (可選)
                # 專屬助手: 免費版帳號預設為 20 秒，暫不實作複雜下拉選單以維持穩定，如有特殊需求請手動調整。
                
            # 刪除臨時的第一題
            if has_first_dummy_slide:
                print("  -> 正在自動移除臨時的第一題以確保題型序列正確...")
                first_slide = page.locator("[data-functional-selector='sidebar-block__kahoot-block-0'], [data-functional-selector='creator-side-bar'] [data-functional-selector='sidebar-block']").first
                first_slide.hover()
                remove_btn = first_slide.locator("[data-functional-selector='sidebar__remove'], button[class*='remove']")
                if remove_btn.count() > 0:
                    remove_btn.first.click()
                    page.wait_for_timeout(1000)
                    confirm_btn = page.locator("[data-functional-selector='dialog-confirm-delete-question__accept-button']")
                    if confirm_btn.count() > 0:
                        confirm_btn.first.click()
                        page.wait_for_timeout(1000)
                else:
                    print("  [警告] 找不到臨時第一題的移除按鈕，請手動移除該題。")
                
            # 4. 儲存 Kahoot
            print("[步驟 4/5] 正在儲存活動...")
            save_btn = page.locator("[data-functional-selector='top-bar__save-button'], [data-testid='save-button'], button:has-text('Save'), button:has-text('儲存')")
            save_btn.first.click()
            page.wait_for_timeout(3000)
            
            # 5. 處理發布或草稿
            print("[步驟 5/5] 處理發布狀態...")
            # 優先檢查是否彈出「準備就緒」對話框
            finish_btn = page.locator("[data-functional-selector='dialog-complete-kahoot__finish-button']")
            if finish_btn.count() > 0:
                finish_btn.first.click()
                page.wait_for_timeout(3000)
                print("[成功] Kahoot 已經成功建立並完成發布！")
            else:
                if args.publish:
                    # 點擊 Publish / Done 進行發布
                    publish_btn = page.locator("[data-functional-selector='dialog-information-kahoot__done-button'], button:has-text('Publish'), button:has-text('Done'), button:has-text('發布'), button:has-text('完成'), [data-testid='publish-kahoot-button']")
                    if publish_btn.count() > 0:
                        publish_btn.first.click()
                        page.wait_for_timeout(3000)
                    print("[成功] Kahoot 已經成功建立並發布！")
                else:
                    # 點擊 'Keep as draft' 或 'Close' / 'Done'
                    draft_btn = page.locator("button:has-text('Keep as draft'), button:has-text('Back to edit'), button:has-text('Close'), button:has-text('保留為草稿'), button:has-text('離開'), button:has-text('取消')")
                    if draft_btn.count() > 0:
                        draft_btn.first.click()
                        page.wait_for_timeout(2000)
                    print("[成功] Kahoot 已經成功建立並儲存為草稿。")
                
            # 獲取當前網址 (若能取得)
            print(f"[成功] 建立完成。請至您的 Kahoot 創作者後台確認: {BASE_URL}/my-library/kahoots")
            
        except Exception as e:
            print(f"[失敗] 建立過程發生錯誤: {e}", file=sys.stderr)
            _dump_debug(page, "create_failed")
            sys.exit(3)

# ---- 主程式與參數解析 ----

def build_parser():
    parser = argparse.ArgumentParser(
        description="Kahoot! CLI 自動化出題工具",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="cmd", required=True, title="可用的指令")
    
    # doctor 指令
    subparsers.add_parser("doctor", help="診斷本機 Playwright、Chromium 及登入 Session 狀態")
    
    # chrome-login 指令
    parser_login = subparsers.add_parser("chrome-login", help="開啟專屬 Profile 的真實 Chrome 供您手動登入 Kahoot")
    parser_login.add_argument("--port", type=int, default=DEFAULT_CDP_PORT, help=f"除錯埠 (預設 {DEFAULT_CDP_PORT})")
    parser_login.add_argument("--chrome-path", type=str, default=None, help="手動指定 Google Chrome 執行檔路徑")
    
    # grab-session 指令
    parser_grab = subparsers.add_parser("grab-session", help="連線到偵錯 Chrome，複製 cookies 保存登入 Session")
    parser_grab.add_argument("--cdp-url", type=str, default=None, help="手動指定 CDP 連線網址")
    
    # check 指令
    parser_check = subparsers.add_parser("check", help="驗證本地登入 Session 是否仍有效")
    parser_check.add_argument("--no-headless", dest="headless", action="store_false", help="以有頭瀏覽器模式執行（可看見操作畫面）")
    parser_check.set_defaults(headless=True)
    
    # create 指令
    parser_create = subparsers.add_parser("create", help="讀取題目 JSON 並自動在 Kahoot 建立遊戲")
    parser_create.add_argument("--content", required=True, help="題目 JSON 設定檔路徑")
    parser_create.add_argument("--dry-run", action="store_true", help="只驗證 JSON 與設定，不執行 Playwright 自動化")
    parser_create.add_argument("--publish", action="store_true", help="建立完畢後直接發布 (Publish) 遊戲，而非只存為草稿")
    parser_create.add_argument("--no-headless", dest="headless", action="store_false", help="以有頭瀏覽器模式執行（可看見操作畫面）")
    parser_create.add_argument("--premium", action="store_true", help="宣告您使用的是付費帳號，解鎖高級題型出題 (Puzzle, Word Cloud, Poll)")
    parser_create.set_defaults(headless=True)
    
    return parser

def main():
    parser = build_parser()
    args = parser.parse_args()
    
    # 對應指令執行
    if args.cmd == "doctor":
        cmd_doctor(args)
    elif args.cmd == "chrome-login":
        cmd_chrome_login(args)
    elif args.cmd == "grab-session":
        cmd_grab_session(args)
    elif args.cmd == "check":
        cmd_check(args)
    elif args.cmd == "create":
        cmd_create(args)

if __name__ == "__main__":
    main()
