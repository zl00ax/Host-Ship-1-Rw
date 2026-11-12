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
        r"EXPIRES[^\n\d]*\n\s*(\d+)\s*Days?",
        r"Renewal\s+in\s+(\d+)\s*Days?",
        r"Renew\s+in\s+(\d+)\s*Days?",
        r"(\d+)\s*Days?\s+until\s+renewal",
        r"^(\d+)\s*Days?\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return int(match.group(1))

    return None


def get_expire_date_str(text):
    if not text:
        return None
    match = re.search(r"EXPIRES\s+([A-Z0-9\s]+?)[\)\n]", text + "\n", re.I)
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


def is_submit_ready(page, submit):
    try:
        if has_turnstile_token(page) and not submit.is_disabled():
            return True

        if not submit.is_visible():
            return False

        if submit.is_disabled():
            return False

        btn_text = (submit.inner_text() or "").strip().lower()
        if "security check" in btn_text:
            return False

        return True

    except Exception:
        return False


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

    # 弧线中间过渡点
    mid_x = (start_x + jitter_x) / 2 + random.uniform(-25, 25)
    mid_y = (start_y + jitter_y) / 2 + random.uniform(-18, 18)
    page.mouse.move(mid_x, mid_y, steps=random.randint(8, 14))
    time.sleep(random.uniform(0.06, 0.14))

    # 移动到目标复选框中心先悬停片刻再按下
    page.mouse.move(jitter_x, jitter_y, steps=random.randint(12, 22))
    time.sleep(random.uniform(0.18, 0.32))
    page.mouse.down()
    time.sleep(random.uniform(0.08, 0.16))
    page.mouse.up()


def click_turnstile_box(page, password_locator=None, submit_locator=None, attempt=1):
    """
    【核心原则】绝不查询或定位 iframe[src*="challenges.cloudflare.com"]！
    避免触发 Cloudflare 对 Shadow DOM 内部 iframe 节点的探测陷阱。
    仅通过主文档宿主容器、表单间距及原生键盘焦点 (Tab+Space) 触发。
    """
    start_x, start_y = None, None
    if password_locator:
        try:
            pw_box = password_locator.bounding_box()
            if pw_box:
                start_x = pw_box["x"] + pw_box["width"] / 2
                start_y = pw_box["y"] + pw_box["height"] / 2
        except Exception:
            pass

    # 第 2 次重试时，结合原生键盘 Tab + Space 触发（无需任何坐标或 DOM 查询）
    if attempt == 2 and password_locator:
        try:
            log("⌨️ 尝试通过密码框原生焦点切换 (Tab + Space) 触发 Turnstile...")
            password_locator.click()
            time.sleep(random.uniform(0.2, 0.35))
            page.keyboard.press("Tab")
            time.sleep(random.uniform(0.35, 0.6))
            page.keyboard.press("Space")
            time.sleep(1.5)
            if has_turnstile_token(page):
                return True
        except Exception:
            pass

    # 1. 优先通过密码框与提交按钮之间的几何间距计算坐标（零 Turnstile DOM 接触）
    if password_locator and submit_locator:
        try:
            pw_box = password_locator.bounding_box()
            sub_box = submit_locator.bounding_box()
            if pw_box and sub_box:
                pw_bottom = pw_box["y"] + pw_box["height"]
                gap = sub_box["y"] - pw_bottom
                if gap >= 45:
                    target_x = sub_box["x"] + 30
                    target_y = pw_bottom + (gap / 2)
                    human_mouse_click(page, target_x, target_y, start_x, start_y)
                    log(f"🖱️ 已通过表单几何间距物理坐标点击 Turnstile: ({int(target_x)}, {int(target_y)})")
                    return True
        except Exception:
            pass

    # 2. 通过主文档外层宿主 div 尺寸匹配定位（不接触任何 iframe 标签）
    try:
        box = page.evaluate("""() => {
            const els = document.querySelectorAll('.cf-turnstile, [data-sitekey], form div, [role="dialog"] div, body div');
            for (const el of els) {
                const rect = el.getBoundingClientRect();
                if (rect.width >= 250 && rect.width <= 420 && rect.height >= 55 && rect.height <= 80) {
                    if (el.querySelectorAll('input:not([type="hidden"]), button').length === 0) {
                        return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
                    }
                }
            }
            return null;
        }""")
        if box:
            target_x = box["x"] + 30
            target_y = box["y"] + (box["height"] / 2)
            human_mouse_click(page, target_x, target_y, start_x, start_y)
            log(f"🖱️ 已通过外层宿主容器物理坐标点击 Turnstile: ({int(target_x)}, {int(target_y)})")
            return True
    except Exception:
        pass

    # 3. 保底：仅检查主文档宿主属性选择器
    host_selectors = [
        '.cf-turnstile',
        '[data-sitekey]',
        '[id*="turnstile" i]',
        '[class*="turnstile" i]',
    ]
    for selector in host_selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() and loc.is_visible():
                box = loc.bounding_box()
                if box and box["width"] >= 100 and box["height"] >= 35:
                    target_x = box["x"] + 30
                    target_y = box["y"] + (box["height"] / 2)
                    human_mouse_click(page, target_x, target_y, start_x, start_y)
                    log(f"🖱️ 已通过宿主选择器 ({selector}) 物理坐标点击 Turnstile: ({int(target_x)}, {int(target_y)})")
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
    """等待安全验证完成，严格控制点击频次，结合物理点击与键盘触发"""
    start_time = time.time()
    last_click_time = 0.0
    click_attempts = 0

    while time.time() - start_time < timeout_sec:
        if is_submit_ready(page, submit):
            log("✅ 安全验证已通过，登录按钮已激活")
            return True

        now = time.time()
        elapsed = now - start_time

        # 先等 6 秒给 Turnstile 自动静默校验；未通过则间隔 14 秒尝试（最多 3 次）
        if elapsed >= 6.0 and (now - last_click_time) >= 14.0 and click_attempts < 3:
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


def wait_for_server_panel_loaded(page, timeout_sec=30):
    start = time.time()
    while time.time() - start < timeout_sec:
        try:
            body_text = page.locator("body").inner_text(timeout=3000)
            if (
                re.search(r"EXPIRES|Renewal|Server\s+Details|Console|Power", body_text, re.I)
                and "/auth/login" not in page.url
            ):
                return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


def human_type(page, locator, text):
    """使用带鼠标移动的真实点击聚焦，并以随机按键间隔输入文本"""
    try:
        box = locator.bounding_box()
        if box:
            cx = box["x"] + box["width"] * random.uniform(0.3, 0.7)
            cy = box["y"] + box["height"] * random.uniform(0.35, 0.65)
            page.mouse.move(cx, cy, steps=random.randint(8, 15))
            time.sleep(random.uniform(0.08, 0.18))
            page.mouse.click(cx, cy)
        else:
            locator.click()
    except Exception:
        locator.click()

    time.sleep(random.uniform(0.15, 0.3))
    page.keyboard.press("Control+A")
    time.sleep(random.uniform(0.05, 0.12))
    page.keyboard.press("Backspace")
    time.sleep(random.uniform(0.1, 0.2))

    for ch in text:
        page.keyboard.type(ch, delay=random.randint(45, 115))
    time.sleep(random.uniform(0.2, 0.4))


def login_if_needed(page):
    """检查是否需要登录，如果需要则填写凭据并通过 Turnstile 验证"""
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
    submit_selectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Login")',
        'button:has-text("Sign in")',
        'button:has-text("Continue")',
        'button:has-text("Complete the security check")',
    ]

    user_input = first_visible(page, user_selectors)
    pass_input = first_visible(page, pass_selectors)

    if not user_input or not pass_input:
        if wait_for_server_panel_loaded(page, timeout_sec=8):
            log("✅ 当前已处于登录状态")
            return True
        user_input = first_visible(page, user_selectors)
        pass_input = first_visible(page, pass_selectors)
        if not user_input or not pass_input:
            return True

    if not HOSTSHIP_LOGIN or not HOSTSHIP_PASSWORD:
        raise RuntimeError("未配置 HOSTSHIP_LOGIN 或 HOSTSHIP_PASSWORD 环境变量")

    log("🔐 正在填写登录信息...")
    human_type(page, user_input, HOSTSHIP_LOGIN)
    time.sleep(random.uniform(0.3, 0.6))
    human_type(page, pass_input, HOSTSHIP_PASSWORD)

    submit_btn = first_visible(page, submit_selectors)
    if not submit_btn:
        raise RuntimeError("未找到登录提交按钮")

    if not wait_and_solve_turnstile(
        page,
        submit_btn,
        password_locator=pass_input,
        timeout_sec=50,
    ):
        raise RuntimeError(
            "登录按钮始终处于禁用状态 (Complete the security check)，未能通过 Cloudflare 安全验证"
        )

    log("🚀 正在提交登录...")
    try:
        box = submit_btn.bounding_box()
        if box:
            human_mouse_click(
                page,
                box["x"] + box["width"] / 2,
                box["y"] + box["height"] / 2,
            )
        else:
            submit_btn.click()
    except Exception:
        submit_btn.click()

    if not wait_for_server_panel_loaded(page, timeout_sec=35):
        raise RuntimeError("登录后未能成功加载服务器控制面板页面")

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
    try:
        body_text = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return "未知状态"

    match = re.search(
        r"(\d+\s*Days?\s*\(EXPIRES[^\)]+\))",
        body_text,
        re.I,
    )
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()

    for line in body_text.splitlines():
        line_clean = line.strip()
        if re.search(r"EXPIRES|\d+\s*Days?", line_clean, re.I) and len(line_clean) < 80:
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
        btn.scroll_into_view_if_needed(timeout=3000)
    except Exception:
        pass

    try:
        box = btn.bounding_box()
        if box:
            human_mouse_click(
                page,
                box["x"] + box["width"] / 2,
                box["y"] + box["height"] / 2,
            )
            return True
    except Exception:
        pass

    try:
        btn.click(timeout=5000)
        return True
    except Exception:
        pass

    return False


def dump_page_diff(before_text, after_text):
    before_lines = set(line.strip() for line in (before_text or "").splitlines() if line.strip())
    after_lines = [line.strip() for line in (after_text or "").splitlines() if line.strip()]
    added = [line for line in after_lines if line not in before_lines]
    if added:
        log("📄 页面新增内容: " + " | ".join(added[:6]))


def renewal_succeeded(before, after, page_text=""):
    before_days = get_days(before)
    after_days = get_days(after)

    if before_days is not None and after_days is not None and after_days > before_days:
        return True

    before_exp = get_expire_date_str(before)
    after_exp = get_expire_date_str(after)
    if before_exp and after_exp and before_exp != after_exp:
        return True

    if re.search(r" successfully\s+renewed|renewal\s+successful|server\s+has\s+been\s+renewed", page_text, re.I):
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
    """处理点击续期按钮后可能弹出的确认弹窗或二次 Turnstile 验证"""
    time.sleep(2.5)

    modal_confirm_selectors = [
        '[role="dialog"] button:has-text("Renew")',
        '[role="dialog"] button:has-text("Confirm")',
        '[role="dialog"] button:has-text("Continue")',
        '[role="dialog"] button[type="submit"]',
        '.modal button:has-text("Renew")',
        '.modal button:has-text("Confirm")',
    ]

    confirm_btn = first_visible(page, modal_confirm_selectors)
    if confirm_btn:
        log("🪟 检测到续期确认弹窗，正在处理弹窗内安全验证...")
        wait_and_solve_turnstile(page, confirm_btn, timeout_sec=45)
        trigger_click_all_ways(page, confirm_btn)
    else:
        # 即使没有单独确认按钮，也检查是否出现了内嵌 Turnstile
        click_turnstile_box(page, attempt=1)

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
                raise RuntimeError("未能在面板中找到续期 (Renew) 按钮")

            if renew_btn.is_disabled():
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

    # 如果启用了代理且因为 Cloudflare 验证被拦截，自动回退直连重试一次
    if IS_PROXY:
        log("🔄 当前代理节点 IP 疑似被 Cloudflare 标记拦截，正在自动切换为直连模式重试...")
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
