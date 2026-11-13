#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import random
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

try:
    from patchright.sync_api import TimeoutError as PlaywrightTimeoutError
    from patchright.sync_api import sync_playwright
    USING_PATCHRIGHT = True
except ImportError:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
    USING_PATCHRIGHT = False


SERVER_URL = os.getenv("SERVER_URL", "").strip()
HOSTSHIP_LOGIN = os.getenv("HOSTSHIP_LOGIN", "").strip()
HOSTSHIP_PASSWORD = os.getenv("HOSTSHIP_PASSWORD", "").strip()

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "").strip()

IS_PROXY = os.getenv("IS_PROXY", "false").lower() == "true"
PROXY_SERVER = os.getenv(
    "PROXY_SERVER",
    "socks5://127.0.0.1:1080"
).strip()

MANUAL_RUN = os.getenv(
    "MANUAL_RUN",
    "false"
).lower() == "true"

HEADLESS_MODE = os.getenv(
    "HEADLESS",
    "auto"
).strip().lower()

BJ_TZ = ZoneInfo("Asia/Shanghai")


def log(msg):
    print(
        f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}",
        flush=True
    )


def save_debug_screenshot(page, prefix="hostship_error"):
    """保存调试截图，供 GitHub Actions 上传 Artifact 排查"""
    if not page:
        return
    try:
        filename = f"{prefix}_{int(time.time())}.png"
        page.screenshot(path=filename, full_page=True)
        log(f"📸 已保存调试截图: {filename}")
    except Exception as exc:
        log(f"⚠️ 保存截图失败: {exc}")


def server_id():
    if not SERVER_URL:
        return "未知"
    return SERVER_URL.rstrip("/").split("/")[-1]


def node_status(use_proxy=None):
    active = IS_PROXY if use_proxy is None else use_proxy
    if active:
        return "✅ 已启用"
    return "⚪ 未启用（直连）"


def get_days(text):
    if not text:
        return None

    patterns = [
        r"(\d+)\s*Days?\s*\(EXPIRES",
        r"EXPIRES[^\n\d]*\n?\s*(\d+)\s*Days?",
        r"Renewal\s+in\s+(\d+)\s*Days?",
        r"Renew\s+in\s+(\d+)\s*Days?",
        r"(\d+)\s*Days?\s+until\s+renewal",
        r"\b(\d+)\s*Days?\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return int(match.group(1))

    return None


def get_expire_date_str(text):
    if not text:
        return None
    match = re.search(r"EXPIRES\s+([A-Z0-9\s]+?)[\)\n\-]", text + "\n", re.I)
    if match:
        return match.group(1).strip().upper()
    return None


def beijing_now():
    return datetime.now(BJ_TZ)


def estimate_renew_date(status):
    days = get_days(status)
    if days is None:
        return None
    wait_days = days - 13 if days >= 14 else 0
    return (
        beijing_now().date()
        + timedelta(days=wait_days)
    )


def tg(text):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        log("⚠️ Telegram 未配置，跳过通知")
        return False

    try:
        proxies = None
        if IS_PROXY:
            proxies = {
                "http": PROXY_SERVER,
                "https": PROXY_SERVER,
            }

        response = requests.post(
            (
                "https://api.telegram.org/"
                f"bot{TG_BOT_TOKEN}/sendMessage"
            ),
            json={
                "chat_id": TG_CHAT_ID,
                "text": text,
            },
            timeout=20,
            proxies=proxies,
        )

        if response.ok:
            log("✅ Telegram 通知发送成功")
            return True

        log("❌ Telegram 通知失败: " + response.text)
        return False

    except Exception as exc:
        log(f"❌ Telegram 通知异常: {exc}")
        return False


def current_ip(use_proxy=None):
    active = IS_PROXY if use_proxy is None else use_proxy
    try:
        proxies = None
        if active:
            proxies = {
                "http": PROXY_SERVER,
                "https": PROXY_SERVER,
            }

        response = requests.get(
            "https://api.ipify.org",
            timeout=15,
            proxies=proxies,
        )

        if response.ok:
            return response.text.strip()

        return "获取失败"

    except Exception:
        return "获取失败"


def build_check_message(status, ip, use_proxy, reason="未到续期时间（需低于 14 天）"):
    days = get_days(status)
    renew_date = estimate_renew_date(status)
    now = beijing_now()

    lines = [
        "⏳ Host-Ship 检查完成",
        "",
        f"🖥️ 服务器：#{server_id()}",
        f"🌐 节点状态：{node_status(use_proxy)}",
        f"📍 出口IP：{ip}",
        f"🕗 检查时间：{now.strftime('%Y/%m/%d %H:%M')}",
        "",
        f"🔒 当前状态：{reason}",
    ]

    if days is not None:
        lines.append(f"⏱️ 剩余有效期：{status}")
    else:
        lines.append(f"📅 面板状态：{status}")

    if renew_date is not None and days is not None and days >= 14:
        lines.append(
            "📆 预计可续期："
            + renew_date.strftime("%Y/%m/%d")
        )

    lines.append("⏰ 自动检查：每天 08:00（北京时间）")
    return "\n".join(lines)


def build_success_message(before, after, ip, use_proxy):
    before_days = get_days(before)
    after_days = get_days(after)
    now = beijing_now()

    lines = [
        "🎉 Host-Ship 续期成功",
        "",
        f"🖥️ 服务器：#{server_id()}",
        f"🌐 节点状态：{node_status(use_proxy)}",
        f"📍 出口IP：{ip}",
        f"🕗 续期时间：{now.strftime('%Y/%m/%d %H:%M')}",
        "",
    ]

    if before_days is not None:
        lines.append(f"📅 续期前：约 {before_days} 天 ({before})")
    else:
        lines.append(f"📅 续期前：{before}")

    if after_days is not None:
        lines.append(f"✅ 续期后：约 {after_days} 天 ({after})")
    else:
        lines.append(f"✅ 续期后：{after}")

    lines.append("⏰ 自动检查：每天 08:00（北京时间）")
    return "\n".join(lines)


def build_error_message(title, reason, ip, use_proxy):
    now = beijing_now()
    return (
        f"{title}\n\n"
        f"🖥️ 服务器：#{server_id()}\n"
        f"🌐 节点状态：{node_status(use_proxy)}\n"
        f"📍 出口IP：{ip}\n"
        f"🕗 检查时间：{now.strftime('%Y/%m/%d %H:%M')}\n\n"
        f"⚠️ 原因：{reason}"
    )


def first_visible(page, selectors):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() and locator.is_visible():
                return locator
        except Exception:
            pass
    return None


LOGIN_SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'button:has-text("Sign In")',
    'button:has-text("Sign in")',
    'button:has-text("Login")',
    'button:has-text("Log in")',
    'button:has-text("Continue"):not(:has-text("Discord"))',
    'button:has-text("Complete the security check")',
]


def find_login_submit_button(page):
    """仅在登录页查找登录按钮，严格排除 Logout 和 Discord 按钮"""
    if "/auth/login" not in page.url:
        return None

    try:
        buttons = page.locator("button")
        count = buttons.count()
        for i in range(count):
            item = buttons.nth(i)
            if item.is_visible():
                txt = (item.inner_text(timeout=1000) or "").strip().lower()
                if "discord" not in txt and "logout" not in txt and "log out" not in txt:
                    return item
    except Exception:
        pass

    return first_visible(page, LOGIN_SUBMIT_SELECTORS)


def has_turnstile_token(page):
    """在主页面 DOM 中检查隐藏的 cf-turnstile-response 是否已生成 Token（绝不进入 iframe）"""
    try:
        return page.evaluate("""() => {
            const inputs = document.querySelectorAll(
                'input[name="cf-turnstile-response"], input[name="g-recaptcha-response"], [name*="turnstile" i]'
            );
            for (const inp of inputs) {
                if (inp.value && inp.value.trim().length > 20) return true;
            }
            return false;
        }""")
    except Exception:
        return False


def is_submit_ready(page, fallback_submit=None):
    """动态检查当前提交按钮是否已解除禁用且不再显示 security check"""
    try:
        if has_turnstile_token(page):
            return True

        submit = find_login_submit_button(page) if "/auth/login" in page.url else fallback_submit
        if not submit or not submit.is_visible():
            return False

        if submit.is_disabled(timeout=1000):
            return False

        btn_text = (submit.inner_text(timeout=1000) or "").strip().lower()
        if "security check" in btn_text or "logout" in btn_text or "discord" in btn_text:
            return False

        return True

    except Exception:
        return has_turnstile_token(page)


def warmup_mouse(page):
    """在页面加载初期生成自然鼠标移动事件，配合 Cloudflare jsd 静默脚本校验"""
    try:
        x1, y1 = random.uniform(280, 520), random.uniform(220, 380)
        x2, y2 = random.uniform(550, 820), random.uniform(320, 520)
        page.mouse.move(x1, y1, steps=random.randint(8, 14))
        time.sleep(random.uniform(0.12, 0.25))
        page.mouse.move(x2, y2, steps=random.randint(10, 18))
    except Exception:
        pass


def human_mouse_click(page, x, y, start_x=None, start_y=None):
    """使用纯物理鼠标轨迹点击目标坐标，模拟真人弧线移动与微小抖动"""
    jitter_x = x + random.uniform(-2.0, 2.0)
    jitter_y = y + random.uniform(-2.0, 2.0)

    if start_x is None or start_y is None:
        start_x = jitter_x + random.uniform(70, 150)
        start_y = jitter_y + random.uniform(-45, 35)

    page.mouse.move(start_x, start_y, steps=random.randint(5, 10))
    time.sleep(random.uniform(0.08, 0.16))

    mid_x = (start_x + jitter_x) / 2 + random.uniform(-25, 25)
    mid_y = (start_y + jitter_y) / 2 + random.uniform(-18, 18)
    page.mouse.move(mid_x, mid_y, steps=random.randint(8, 14))
    time.sleep(random.uniform(0.06, 0.14))

    page.mouse.move(jitter_x, jitter_y, steps=random.randint(12, 22))
    time.sleep(random.uniform(0.18, 0.32))
    page.mouse.down()
    time.sleep(random.uniform(0.08, 0.16))
    page.mouse.up()


def set_react_input_value(locator, text):
    """通过原生 HTMLInputElement value setter 强制写入并派发 React input/change 事件"""
    try:
        locator.evaluate(
            """(el, val) => {
                el.focus();
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype,
                    'value'
                ).set;
                nativeInputValueSetter.call(el, val);
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            text,
        )
    except Exception:
        pass


def human_type(page, locator, text):
    """
    安全且兼容 React 受控组件的真人输入：
    1. 鼠标移动到输入框并点击聚焦
    2. 清空原有内容并使用 press_sequentially 模拟逐字输入
    3. 严格校验 input_value()，若不一致则使用 React 原生 setter 修正，防止漏输或多出空格
    """
    try:
        box = locator.bounding_box(timeout=3000)
        if box:
            cx = box["x"] + box["width"] * random.uniform(0.3, 0.7)
            cy = box["y"] + box["height"] * random.uniform(0.35, 0.65)
            page.mouse.move(cx, cy, steps=random.randint(6, 12))
            time.sleep(random.uniform(0.08, 0.15))
            page.mouse.click(cx, cy)
        else:
            locator.click(timeout=3000)
    except Exception:
        try:
            locator.click(timeout=3000)
        except Exception:
            pass

    time.sleep(random.uniform(0.1, 0.2))

    try:
        locator.fill("")
    except Exception:
        pass

    try:
        locator.press_sequentially(text, delay=random.randint(35, 85))
    except Exception:
        for ch in text:
            page.keyboard.type(ch, delay=random.randint(35, 85))

    time.sleep(random.uniform(0.15, 0.25))

    # 校验实际输入框的值是否与预期完全一致（防止残留字符或意外空格）
    try:
        actual_val = locator.input_value(timeout=1500)
        if actual_val != text:
            set_react_input_value(locator, text)
            time.sleep(0.15)
    except Exception:
        set_react_input_value(locator, text)


def ensure_credentials_intact(user_input, pass_input):
    """在点击登录前再次确认账号密码没有因为 Tab/Space 操作被篡改或追加空格"""
    try:
        if user_input and user_input.input_value(timeout=1000) != HOSTSHIP_LOGIN:
            log("🔧 检测到用户名输入值异常，正在自动修正...")
            set_react_input_value(user_input, HOSTSHIP_LOGIN)
        if pass_input and pass_input.input_value(timeout=1000) != HOSTSHIP_PASSWORD:
            log("🔧 检测到密码框输入值被改动（如末尾多出空格），正在自动修正...")
            set_react_input_value(pass_input, HOSTSHIP_PASSWORD)
    except Exception:
        pass


def click_turnstile_box(page, password_locator=None, submit_locator=None, attempt=1):
    """
    【核心原则】绝不查询或定位 iframe[src*="challenges.cloudflare.com"]！
    第 1 优先级：密码框原生 Tab 焦点切换（自动跳过 Forgot password? 并确保焦点已离开 INPUT）+ Space。
    第 2 优先级：使用提交按钮正上方 48px 处的物理坐标点击。
    """
    start_x, start_y = None, None
    pw_bottom = 0
    if password_locator:
        try:
            pw_box = password_locator.bounding_box(timeout=2000)
            if pw_box:
                start_x = pw_box["x"] + pw_box["width"] / 2
                start_y = pw_box["y"] + pw_box["height"] / 2
                pw_bottom = pw_box["y"] + pw_box["height"]
        except Exception:
            pass

    # 策略 1（首选）：通过密码框原生焦点切换 (Tab 跳过 Forgot password? -> Space)
    if password_locator and attempt in (1, 3):
        try:
            log("⌨️ 尝试通过密码框原生焦点切换 (Tab + Space) 触发 Turnstile...")
            password_locator.focus(timeout=2000)
            time.sleep(random.uniform(0.15, 0.3))

            # 最多按 3 次 Tab，直到焦点既不在 INPUT 也不在 A (Forgot password?) 上
            for _ in range(3):
                page.keyboard.press("Tab")
                time.sleep(random.uniform(0.25, 0.4))
                active_tag = page.evaluate(
                    "() => (document.activeElement && document.activeElement.tagName) || ''"
                )
                if active_tag not in ("INPUT", "A"):
                    break

            active_tag = page.evaluate(
                "() => (document.activeElement && document.activeElement.tagName) || ''"
            )
            if active_tag not in ("INPUT", "A"):
                page.keyboard.press("Space")
                return True
        except Exception:
            pass

    # 策略 2：通过提交按钮正上方偏移计算坐标（Turnstile 紧贴在提交按钮上方约 48px 处）
    cur_submit = find_login_submit_button(page) or submit_locator
    if cur_submit:
        try:
            sub_box = cur_submit.bounding_box(timeout=2000)
            if sub_box:
                target_x = sub_box["x"] + 30
                target_y = sub_box["y"] - 48
                human_mouse_click(page, target_x, target_y, start_x, start_y)
                log(f"🖱️ 已通过提交按钮上方偏移物理坐标点击 Turnstile: ({int(target_x)}, {int(target_y)})")
                return True
        except Exception:
            pass

    # 策略 3：仅匹配位于密码框下方 (rect.y > pw_bottom) 的外层宿主容器
    try:
        box = page.evaluate("""(minY) => {
            const els = document.querySelectorAll('.cf-turnstile, [data-sitekey], form div, [role="dialog"] div');
            for (const el of els) {
                const rect = el.getBoundingClientRect();
                if (rect.y >= minY && rect.width >= 250 && rect.width <= 420 && rect.height >= 55 && rect.height <= 80) {
                    if (el.querySelectorAll('input:not([type="hidden"]), button, a').length === 0) {
                        return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
                    }
                }
            }
            return null;
        }""", pw_bottom)
        if box:
            target_x = box["x"] + 30
            target_y = box["y"] + (box["height"] / 2)
            human_mouse_click(page, target_x, target_y, start_x, start_y)
            log(f"🖱️ 已通过外层宿主容器物理坐标点击 Turnstile: ({int(target_x)}, {int(target_y)})")
            return True
    except Exception:
        pass

    return False


def wait_and_solve_turnstile(
    page,
    submit,
    password_locator=None,
    timeout_sec=50,
):
    """等待安全验证完成，支持键盘焦点与物理坐标交替触发"""
    start_time = time.time()
    last_click_time = 0.0
    click_attempts = 0

    while time.time() - start_time < timeout_sec:
        if is_submit_ready(page, submit):
            log("✅ 安全验证已通过，登录按钮已激活")
            return True

        now = time.time()
        elapsed = now - start_time

        if elapsed >= 5.0 and (now - last_click_time) >= 11.0 and click_attempts < 3:
            click_attempts += 1
            last_click_time = now
            log(f"⏳ 登录按钮仍禁用，尝试触发安全验证 (第 {click_attempts} 次)...")
            click_turnstile_box(
                page,
                password_locator=password_locator,
                submit_locator=submit,
                attempt=click_attempts,
            )

        time.sleep(1.0)

    return is_submit_ready(page, submit)


def is_on_server_detail_page(page):
    """严格判断当前是否已经处于具体服务器控制面板页（截图 3），而非 Dashboard 主页（截图 2）"""
    try:
        url = page.url
        if "/auth/login" in url:
            return False

        body_text = page.locator("body").inner_text(timeout=3000)
        if re.search(r"EXPIRES\s+[0-9A-Z]+|UPTIME|CPU\s+LOAD|DISK\s+USAGE", body_text, re.I):
            return True
    except Exception:
        pass
    return False


def navigate_to_server_panel(page, timeout_sec=35):
    """
    如果登录后停留在 Dashboard 主页（截图 2），自动点击 MANAGE SERVER 或跳转到 SERVER_URL 进入服务器详情页（截图 3）
    """
    start = time.time()
    sid = server_id()

    while time.time() - start < timeout_sec:
        if is_on_server_detail_page(page):
            return True

        url = page.url
        if "/auth/login" not in url:
            manage_selectors = [
                f'a[href*="{sid}"]',
                'a:has-text("MANAGE SERVER")',
                'button:has-text("MANAGE SERVER")',
                '[role="button"]:has-text("MANAGE SERVER")',
                'text="MANAGE SERVER"',
            ]
            clicked = False
            for sel in manage_selectors:
                try:
                    loc = page.locator(sel).first
                    if loc.count() and loc.is_visible():
                        log("🖱️ 当前位于 Dashboard 主页，正在点击 MANAGE SERVER 进入服务器面板...")
                        trigger_click_all_ways(page, loc)
                        clicked = True
                        break
                except Exception:
                    pass

            if clicked:
                time.sleep(3.0)
                if is_on_server_detail_page(page):
                    return True

            if SERVER_URL and sid not in page.url:
                log(f"🔗 正在直接跳转到服务器控制面板: {SERVER_URL}")
                try:
                    page.goto(SERVER_URL, wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    pass
                time.sleep(2.5)
                if is_on_server_detail_page(page):
                    return True

        time.sleep(1.0)

    return is_on_server_detail_page(page)


def get_login_error_banner(page):
    """提取登录页可能出现的错误提示（如密码错误、验证码过期等）"""
    try:
        err = page.evaluate("""() => {
            const selectors = [
                '[role="alert"]',
                '.toast',
                '.error',
                '[class*="error" i]',
                '[class*="alert" i]',
                '[class*="danger" i]',
                'form p'
            ];
            for (const sel of selectors) {
                const els = document.querySelectorAll(sel);
                for (const el of els) {
                    const txt = (el.innerText || '').trim();
                    if (txt && txt.length > 3 && txt.length < 150 && !/welcome|sign in to continue/i.test(txt)) {
                        return txt;
                    }
                }
            }
            return '';
        }""")
        return (err or "").strip()
    except Exception:
        return ""


def submit_login_form(page, user_input=None, pass_input=None):
    """
    验证通过后提交登录表单：
    1. 确保账号密码未被篡改（例如 Tab+Space 误输入空格）
    2. 优先使用 Playwright 原生 click 触发按钮点击，若未跳转则辅以 Enter / requestSubmit 重试
    3. 严控仅在 `/auth/login` 页面内操作，一旦离开立即停止，绝不误触 Dashboard 的 Logout
    """
    time.sleep(0.5)
    ensure_credentials_intact(user_input, pass_input)

    active_btn = find_login_submit_button(page)
    if active_btn:
        try:
            btn_label = (active_btn.inner_text(timeout=1500) or "").strip()
            log(f"🚀 正在提交登录 (按钮: {btn_label or 'Sign In'})...")
        except Exception:
            log("🚀 正在提交登录...")

        # 第 1 次点击：优先使用 Playwright 原生 click（自动等待可点击并触发完整 pointer/mouse 事件链）
        try:
            active_btn.click(timeout=3000)
        except Exception:
            try:
                box = active_btn.bounding_box(timeout=2000)
                if box:
                    human_mouse_click(
                        page,
                        box["x"] + box["width"] / 2,
                        box["y"] + box["height"] / 2,
                    )
            except Exception:
                pass

    leave_start = time.time()
    retried_submit = False

    while time.time() - leave_start < 18:
        if "/auth/login" not in page.url:
            return True

        # 如果 4 秒后仍在 /auth/login，检查是否有报错提示或需要补充触发 Enter / requestSubmit
        if not retried_submit and (time.time() - leave_start) >= 4.0:
            retried_submit = True
            err_txt = get_login_error_banner(page)
            if err_txt:
                log(f"⚠️ 登录页提示信息: {err_txt}")

            if "/auth/login" in page.url:
                ensure_credentials_intact(user_input, pass_input)
                btn_now = find_login_submit_button(page)
                if btn_now and not btn_now.is_disabled(timeout=1000):
                    log("🔄 页面仍停留在登录页，正在尝试回车与表单提交...")
                    try:
                        if pass_input:
                            pass_input.press("Enter", timeout=2000)
                        else:
                            btn_now.click(timeout=2000)
                    except Exception:
                        pass

                    time.sleep(1.0)
                    if "/auth/login" in page.url:
                        try:
                            page.evaluate("""() => {
                                const form = document.querySelector('form');
                                if (form && typeof form.requestSubmit === 'function') {
                                    form.requestSubmit();
                                }
                            }""")
                        except Exception:
                            pass

        time.sleep(0.5)

    err_txt = get_login_error_banner(page)
    if err_txt:
        log(f"❌ 登录失败页面提示: {err_txt}")

    return "/auth/login" not in page.url


def login_if_needed(page):
    """检查是否需要登录，如果需要则填写凭据、通过 Turnstile 验证，并进入目标服务器详情页"""
    time.sleep(2.0)
    warmup_mouse(page)

    user_selectors = [
        'input[name="username"]',
        'input[name="email"]',
        'input[type="email"]',
        'input[autocomplete="username"]',
        'input[placeholder*="Email" i]',
        'input[placeholder*="User" i]',
        'input:not([type="hidden"]):not([type="password"])',
    ]
    pass_selectors = [
        'input[name="password"]',
        'input[type="password"]',
        'input[autocomplete="current-password"]',
    ]

    user_input = first_visible(page, user_selectors)
    pass_input = first_visible(page, pass_selectors)

    if not user_input or not pass_input:
        if navigate_to_server_panel(page, timeout_sec=10):
            log("✅ 当前已处于登录状态并已进入服务器面板")
            return True
        user_input = first_visible(page, user_selectors)
        pass_input = first_visible(page, pass_selectors)

    if user_input and pass_input:
        if not HOSTSHIP_LOGIN or not HOSTSHIP_PASSWORD:
            raise RuntimeError("未配置 HOSTSHIP_LOGIN 或 HOSTSHIP_PASSWORD 环境变量")

        log("🔐 正在填写登录信息...")
        human_type(page, user_input, HOSTSHIP_LOGIN)
        time.sleep(random.uniform(0.25, 0.5))
        human_type(page, pass_input, HOSTSHIP_PASSWORD)

        submit_btn = find_login_submit_button(page)
        if not submit_btn:
            raise RuntimeError("未找到登录提交按钮")

        if not wait_and_solve_turnstile(
            page,
            submit_btn,
            password_locator=pass_input,
            timeout_sec=50,
        ):
            save_debug_screenshot(page, "hostship_turnstile_timeout")
            raise RuntimeError(
                "登录按钮始终处于禁用状态 (Complete the security check)，未能通过 Cloudflare 安全验证"
            )

        submit_login_form(page, user_input=user_input, pass_input=pass_input)

    if not navigate_to_server_panel(page, timeout_sec=35):
        save_debug_screenshot(page, "hostship_login_stuck")
        err_hint = get_login_error_banner(page)
        suffix = f"，页面提示: {err_hint}" if err_hint else ""
        raise RuntimeError(f"登录后未能进入服务器控制面板页面 (当前 URL: {page.url}{suffix})")

    log("✅ 登录成功，已进入服务器面板")
    return True


def is_renew_limit_reached(text):
    if not text:
        return False
    patterns = [
        r"already\s+renewed",
        r"cannot\s+renew\s+yet",
        r"only\s+renew\s+when",
        r"less\s+than\s+14\s+days",
        r"wait\s+until",
        r"not\s+eligible\s+for\s+renewal",
    ]
    for p in patterns:
        if re.search(p, text, re.I):
            return True
    return False


def get_renewal_text(page):
    """
    精准提取截图 3 右下角到期卡片信息：
    支持：
      EXPIRES 18 NOV
      5 Days
    并统一格式化为：'5 Days (EXPIRES 18 NOV)'
    """
    try:
        body_text = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return "未知状态"

    match_two_line = re.search(
        r"EXPIRES\s+([A-Z0-9 ]+?)\s*\n+\s*(\d+\s*Days?)",
        body_text,
        re.I,
    )
    if match_two_line:
        exp_str = re.sub(r"\s+", " ", match_two_line.group(1)).strip().upper()
        days_str = re.sub(r"\s+", " ", match_two_line.group(2)).strip()
        return f"{days_str} (EXPIRES {exp_str})"

    match_inline = re.search(
        r"(\d+\s*Days?\s*\(EXPIRES[^\)]+\))",
        body_text,
        re.I,
    )
    if match_inline:
        return re.sub(r"\s+", " ", match_inline.group(1)).strip()

    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    for idx, line_clean in enumerate(lines):
        if re.search(r"^EXPIRES\b", line_clean, re.I):
            if idx + 1 < len(lines) and re.search(r"\d+\s*Days?", lines[idx + 1], re.I):
                return f"{lines[idx + 1]} ({line_clean})"
            return line_clean

    for line_clean in lines:
        if re.search(r"\d+\s*Days?", line_clean, re.I) and len(line_clean) < 80:
            return line_clean

    return "未知状态"


def inspect_renew_elements(page):
    try:
        info = page.evaluate("""() => {
            const results = [];
            const els = document.querySelectorAll('button, a, [role="button"]');
            for (const el of els) {
                const txt = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
                const rect = el.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0 && /renew|extend|free/i.test(txt)) {
                    results.push({
                        tag: el.tagName,
                        text: txt.slice(0, 60),
                        disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
                        x: Math.round(rect.x),
                        y: Math.round(rect.y),
                        w: Math.round(rect.width),
                        h: Math.round(rect.height)
                    });
                }
            }
            return results;
        }""")
        return info or []
    except Exception:
        return []


def find_right_panel_renew_button(page):
    selectors = [
        'button:has-text("Renew")',
        'button:has-text("RENEW")',
        'button:has-text("Extend")',
        'a:has-text("Renew")',
        '[role="button"]:has-text("Renew")',
    ]
    for sel in selectors:
        loc = page.locator(sel)
        try:
            count = loc.count()
            for i in range(count):
                item = loc.nth(i)
                if item.is_visible():
                    return item
        except Exception:
            pass
    return None


def trigger_click_all_ways(page, btn):
    try:
        btn.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass

    try:
        btn.click(timeout=3000)
        return True
    except Exception:
        pass

    try:
        box = btn.bounding_box(timeout=2000)
        if box:
            human_mouse_click(
                page,
                box["x"] + box["width"] / 2,
                box["y"] + box["height"] / 2,
            )
            return True
    except Exception:
        pass

    return False


def renewal_succeeded(before, after, page_text=""):
    before_days = get_days(before)
    after_days = get_days(after)

    if before_days is not None and after_days is not None and after_days > before_days:
        return True

    before_exp = get_expire_date_str(before)
    after_exp = get_expire_date_str(after)
    if before_exp and after_exp and before_exp != after_exp:
        return True

    if re.search(
        r"successfully\s+renewed|renewal\s+successful|server\s+has\s+been\s+renewed|renewed\s+successfully",
        page_text,
        re.I,
    ):
        return True

    return False


def wait_for_renewal_result(page, before_status, timeout_sec=35):
    start = time.time()
    while time.time() - start < timeout_sec:
        after_status = get_renewal_text(page)
        try:
            body_text = page.locator("body").inner_text(timeout=2000)
        except Exception:
            body_text = ""

        if renewal_succeeded(before_status, after_status, body_text):
            return True, after_status

        time.sleep(1.5)

    return False, get_renewal_text(page)


def handle_post_click_flow(page, before_status):
    """处理点击续期按钮后可能弹出的确认弹窗、二次 Turnstile 验证或直接刷新结果"""
    time.sleep(2.5)

    after_now = get_renewal_text(page)
    try:
        body_now = page.locator("body").inner_text(timeout=2000)
    except Exception:
        body_now = ""
    if renewal_succeeded(before_status, after_now, body_now):
        return True, after_now

    modal_confirm_selectors = [
        '[role="dialog"] button:has-text("Renew")',
        '[role="dialog"] button:has-text("Confirm")',
        '[role="dialog"] button:has-text("Continue")',
        '[role="dialog"] button:has-text("Complete the security check")',
        '[role="dialog"] button[type="submit"]',
        '.modal button:has-text("Renew")',
        '.modal button:has-text("Confirm")',
    ]

    confirm_btn = first_visible(page, modal_confirm_selectors)
    if confirm_btn:
        log("🪟 检测到续期确认弹窗，正在处理弹窗内安全验证...")
        wait_and_solve_turnstile(page, confirm_btn, timeout_sec=45)
        confirm_btn_after = first_visible(page, modal_confirm_selectors) or confirm_btn
        trigger_click_all_ways(page, confirm_btn_after)
    else:
        click_turnstile_box(page, attempt=2)

    return wait_for_renewal_result(page, before_status, timeout_sec=35)


def resolve_headless():
    if HEADLESS_MODE in ("true", "1", "yes"):
        return True
    if HEADLESS_MODE in ("false", "0", "no"):
        return False
    return not bool(os.getenv("DISPLAY"))


def run_attempt(use_proxy):
    ip = current_ip(use_proxy)
    headless = resolve_headless()
    mode_str = "Headless" if headless else "Headed (XVFB/GUI)"
    engine_str = "Patchright" if USING_PATCHRIGHT else "Playwright"

    log(f"🌐 节点状态：{node_status(use_proxy)}")
    log(f"📍 当前出口IP：{ip}")
    log(f"🖥️ 浏览器模式：{mode_str} ({engine_str})")

    user_data_dir = tempfile.mkdtemp(prefix="hostship_profile_")
    page = None

    try:
        with sync_playwright() as p:
            launch_kwargs = {
                "user_data_dir": user_data_dir,
                "headless": headless,
                "no_viewport": True,
                "args": [
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--window-size=1440,1000",
                ],
            }
            if use_proxy:
                launch_kwargs["proxy"] = {"server": PROXY_SERVER}

            try:
                context = p.chromium.launch_persistent_context(
                    channel="chrome",
                    **launch_kwargs,
                )
            except Exception:
                context = p.chromium.launch_persistent_context(
                    **launch_kwargs,
                )

            page = context.pages[0] if context.pages else context.new_page()

            def on_response(response):
                try:
                    url = response.url
                    if (
                        "host-ship.com" in url
                        and response.request.method in ("POST", "PUT", "PATCH")
                        and not any(ext in url for ext in (".js", ".css", ".png", ".woff"))
                    ):
                        log(f"📡 网络响应 [{response.request.method}] HTTP {response.status} -> {url} | ")
                except Exception:
                    pass

            page.on("response", on_response)

            page.goto(SERVER_URL, wait_until="domcontentloaded", timeout=60000)
            try:
                page.bring_to_front()
            except Exception:
                pass

            login_if_needed(page)

            before_status = get_renewal_text(page)
            days = get_days(before_status)
            log(f"📊 当前服务器状态：{before_status}")

            if days is not None and days >= 14 and not MANUAL_RUN:
                log(f"⏳ 剩余有效期 {days} 天（需低于 14 天才可续期），本次仅检查")
                msg = build_check_message(before_status, ip, use_proxy)
                tg(msg)
                context.close()
                return True, None

            renew_btn = find_right_panel_renew_button(page)
            if not renew_btn:
                inspect_renew_elements(page)
                if days is not None and days >= 14:
                    msg = build_check_message(before_status, ip, use_proxy)
                    tg(msg)
                    context.close()
                    return True, None
                save_debug_screenshot(page, "hostship_no_renew_btn")
                raise RuntimeError("未能在面板中找到续期 (Renew) 按钮")

            if renew_btn.is_disabled(timeout=2000):
                if days is not None and days >= 14:
                    log("ℹ️ 续期按钮当前处于禁用状态（未到可续期时间）")
                    msg = build_check_message(before_status, ip, use_proxy)
                    tg(msg)
                    context.close()
                    return True, None

            log("🖱️ 正在点击续期按钮...")
            trigger_click_all_ways(page, renew_btn)

            ok, after_status = handle_post_click_flow(page, before_status)
            if ok:
                log(f"🎉 续期成功！状态更新为：{after_status}")
                msg = build_success_message(before_status, after_status, ip, use_proxy)
                tg(msg)
                context.close()
                return True, None

            try:
                body_after = page.locator("body").inner_text(timeout=3000)
            except Exception:
                body_after = ""

            if is_renew_limit_reached(body_after) or (days is not None and days >= 14):
                log("ℹ️ 面板提示暂未达到可续期条件")
                msg = build_check_message(before_status, ip, use_proxy)
                tg(msg)
                context.close()
                return True, None

            save_debug_screenshot(page, "hostship_renew_unchanged")
            context.close()
            raise RuntimeError(f"点击续期后状态未发生变化（当前状态：{after_status}）")

    except Exception as exc:
        err_msg = str(exc)
        log(f"⚠️ {err_msg}")
        return False, (err_msg, ip)

    finally:
        shutil.rmtree(user_data_dir, ignore_errors=True)


def main():
    log("======================================")
    log(" Host-Ship Free Auto Renew")
    log("======================================")

    if not SERVER_URL:
        log("❌ 未配置 SERVER_URL 环境变量")
        sys.exit(1)

    ok, err_info = run_attempt(IS_PROXY)
    if ok:
        sys.exit(0)

    if IS_PROXY:
        log("🔄 当前代理节点尝试未完成，正在自动切换为直连模式重试...")
        ok_direct, err_info_direct = run_attempt(False)
        if ok_direct:
            sys.exit(0)
        err_info = err_info_direct

    reason, ip = err_info if err_info else ("未知错误", "未知")
    msg = build_error_message(
        "❌ Host-Ship 自动续期失败",
        reason,
        ip,
        False if IS_PROXY else IS_PROXY,
    )
    tg(msg)
    sys.exit(1)


if __name__ == "__main__":
    main()
