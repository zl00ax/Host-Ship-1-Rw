#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


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

STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});
window.chrome = window.chrome || {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {}
};
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en']
});
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5]
});
"""


def log(msg):
    print(
        f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}",
        flush=True
    )


def server_id():
    if not SERVER_URL:
        return "未知"

    return SERVER_URL.rstrip("/").split("/")[-1]


def node_status():
    if IS_PROXY:
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

    # 面板规则：低于 14 天（<= 13 天）时才可续期
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

        log(
            "❌ Telegram 通知失败: "
            + response.text
        )

        return False

    except Exception as exc:
        log(
            f"❌ Telegram 通知异常: {exc}"
        )
        return False


def current_ip():
    try:
        proxies = None

        if IS_PROXY:
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


def build_check_message(status, ip):
    days = get_days(status)
    renew_date = estimate_renew_date(status)
    now = beijing_now()

    lines = [
        "⏳ Host-Ship 检查完成",
        "",
        f"🖥️ 服务器：#{server_id()}",
        f"🌐 节点状态：{node_status()}",
        f"📍 出口IP：{ip}",
        f"🕗 检查时间：{now.strftime('%Y/%m/%d %H:%M')}",
        "",
        "🔒 当前状态：未到续期时间（需低于 14 天）",
    ]

    if days is not None:
        lines.append(
            f"⏱️ 剩余有效期：{status}"
        )
        wait_days = max(0, days - 13)
        lines.append(
            f"⏳ 距离可续期：约 {wait_days} 天"
        )
    else:
        lines.append(
            f"📅 面板状态：{status}"
        )

    if renew_date is not None:
        lines.append(
            "📆 预计可续期："
            + renew_date.strftime("%Y/%m/%d")
        )

    lines.append(
        "⏰ 自动检查：每天 08:00（北京时间）"
    )

    return "\n".join(lines)


def build_success_message(before, after, ip):
    before_days = get_days(before)
    after_days = get_days(after)
    now = beijing_now()

    lines = [
        "🎉 Host-Ship 续期成功",
        "",
        f"🖥️ 服务器：#{server_id()}",
        f"🌐 节点状态：{node_status()}",
        f"📍 出口IP：{ip}",
        f"🕗 续期时间：{now.strftime('%Y/%m/%d %H:%M')}",
        "",
    ]

    if before_days is not None:
        lines.append(
            f"📅 续期前：约 {before_days} 天 ({before})"
        )
    else:
        lines.append(
            f"📅 续期前：{before}"
        )

    if after_days is not None:
        lines.append(
            f"✅ 续期后：约 {after_days} 天 ({after})"
        )
    else:
        lines.append(
            f"✅ 续期后：{after}"
        )

    lines.append(
        "⏰ 自动检查：每天 08:00（北京时间）"
    )

    return "\n".join(lines)


def build_error_message(title, reason, ip):
    now = beijing_now()

    return (
        f"{title}\n\n"
        f"🖥️ 服务器：#{server_id()}\n"
        f"🌐 节点状态：{node_status()}\n"
        f"📍 出口IP：{ip}\n"
        f"🕗 检查时间：{now.strftime('%Y/%m/%d %H:%M')}\n\n"
        f"⚠️ 原因：{reason}"
    )


def first_visible(page, selectors):
    for selector in selectors:
        locator = page.locator(
            selector
        ).first

        try:
            if (
                locator.count()
                and locator.is_visible()
            ):
                return locator

        except Exception:
            pass

    return None


def is_submit_ready(submit):
    try:
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


def click_turnstile_box(page, password_locator=None, submit_locator=None):
    """尝试定位并点击 Cloudflare Turnstile 验证框"""
    for frame in page.frames:
        frame_url = (frame.url or "").lower()
        if "challenges.cloudflare.com" in frame_url or "turnstile" in frame_url:
            try:
                cb = frame.locator('input[type="checkbox"], [role="checkbox"]').first
                if cb.count() and cb.is_visible():
                    cb.click(timeout=3000)
                    log("🖱️ 已通过 iframe 内部元素点击 Turnstile")
                    return True
            except Exception:
                pass

            try:
                frame_el = frame.frame_element()
                box = frame_el.bounding_box()
                if box and box["width"] >= 100 and box["height"] >= 35:
                    target_x = box["x"] + 28
                    target_y = box["y"] + box["height"] / 2
                    page.mouse.move(target_x, target_y, steps=8)
                    time.sleep(0.15)
                    page.mouse.click(target_x, target_y)
                    log("🖱️ 已通过 iframe 坐标点击 Turnstile")
                    return True
            except Exception:
                pass

    turnstile_selectors = [
        'iframe[src*="challenges.cloudflare.com"]',
        'iframe[src*="turnstile"]',
        'iframe[title*="Cloudflare" i]',
        'iframe[title*="widget" i]',
        '.cf-turnstile',
        '[data-sitekey]',
        '[id*="turnstile" i]',
        '[class*="turnstile" i]',
    ]

    for selector in turnstile_selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() and loc.is_visible():
                box = loc.bounding_box()
                if box and box["width"] >= 150 and box["height"] >= 40:
                    target_x = box["x"] + 28
                    target_y = box["y"] + box["height"] / 2
                    page.mouse.move(target_x, target_y, steps=8)
                    time.sleep(0.15)
                    page.mouse.click(target_x, target_y)
                    log(f"🖱️ 已通过容器 ({selector}) 坐标点击 Turnstile")
                    return True
        except Exception:
            pass

    try:
        divs = page.locator("form div")
        count = divs.count()
        for i in range(count):
            div = divs.nth(i)
            if not div.is_visible():
                continue
            box = div.bounding_box()
            if (
                box
                and 240 <= box["width"] <= 420
                and 55 <= box["height"] <= 80
            ):
                if div.locator("input, button").count() == 0:
                    target_x = box["x"] + 28
                    target_y = box["y"] + box["height"] / 2
                    page.mouse.move(target_x, target_y, steps=8)
                    time.sleep(0.15)
                    page.mouse.click(target_x, target_y)
                    log("🖱️ 已通过表单内尺寸匹配点击 Turnstile 区域")
                    return True
    except Exception:
        pass

    if password_locator and submit_locator:
        try:
            pw_box = password_locator.bounding_box()
            sub_box = submit_locator.bounding_box()
            if pw_box and sub_box:
                pw_bottom = pw_box["y"] + pw_box["height"]
                gap = sub_box["y"] - pw_bottom
                if gap >= 50:
                    target_x = sub_box["x"] + 28
                    target_y = pw_bottom + (gap / 2)
                    page.mouse.move(target_x, target_y, steps=8)
                    time.sleep(0.15)
                    page.mouse.click(target_x, target_y)
                    log("🖱️ 已通过密码框与提交按钮间距点击 Turnstile 区域")
                    return True
        except Exception:
            pass

    return False


def wait_and_solve_turnstile(
    page,
    submit,
    password_locator=None,
    timeout_sec=35,
):
    """等待安全验证完成，必要时主动点击 Turnstile"""
    start_time = time.time()
    click_attempts = 0

    while time.time() - start_time < timeout_sec:
        if is_submit_ready(submit):
            log("✅ 安全验证已通过，登录按钮已激活")
            return True

        elapsed = time.time() - start_time
        if elapsed >= 3.0 and int(elapsed) // 5 > click_attempts:
            click_attempts += 1
            log(f"⏳ 登录按钮仍禁用，尝试触发安全验证 (第 {click_attempts} 次)...")
            click_turnstile_box(
                page,
                password_locator=password_locator,
                submit_locator=submit,
            )

        page.wait_for_timeout(1000)

    return is_submit_ready(submit)


def wait_for_server_panel_loaded(page, timeout_sec=15):
    """等待服务器详情页右侧状态卡片渲染完成"""
    start_time = time.time()
    while time.time() - start_time < timeout_sec:
        try:
            body_text = page.locator("body").inner_text()
            if any(
                kw in body_text.upper()
                for kw in ["EXPIRES", "UPTIME", "CPU LOAD", "RENEW"]
            ):
                page.wait_for_timeout(1000)
                return True
        except Exception:
            pass
        page.wait_for_timeout(1000)
    return False


def login_if_needed(page):
    page.goto(
        SERVER_URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    page.wait_for_timeout(3000)

    for _ in range(3):
        title_text = (page.title() or "").lower()
        body_lower = page.locator("body").inner_text().lower()
        if (
            "just a moment" in title_text
            or "verify you are human" in body_lower
        ):
            log("🛡️ 检测到 Cloudflare 全屏拦截页，尝试通过...")
            click_turnstile_box(page)
            page.wait_for_timeout(4000)
        else:
            break

    body = page.locator(
        "body"
    ).inner_text().lower()

    if (
        "/server/" in page.url
        and "password" not in body
    ):
        wait_for_server_panel_loaded(page)
        return True

    email = first_visible(
        page,
        [
            'input[name="email"]',
            'input[type="email"]',
            'input[name="username"]',
            'input[autocomplete="username"]',
        ],
    )

    password = first_visible(
        page,
        [
            'input[name="password"]',
            'input[type="password"]',
            'input[autocomplete="current-password"]',
        ],
    )

    if not email or not password:
        log(
            "❌ 没找到登录框，"
            f"当前页面: {page.url}"
        )
        return False

    if (
        not HOSTSHIP_LOGIN
        or not HOSTSHIP_PASSWORD
    ):
        log(
            "❌ 缺少 HOSTSHIP_LOGIN "
            "/ HOSTSHIP_PASSWORD"
        )
        return False

    log("🔐 正在填写登录信息...")

    email.click()
    page.wait_for_timeout(200)
    email.fill(HOSTSHIP_LOGIN)

    page.wait_for_timeout(300)

    password.click()
    page.wait_for_timeout(200)
    password.fill(HOSTSHIP_PASSWORD)

    submit = first_visible(
        page,
        [
            'button[type="submit"]',
            'button:has-text("Login")',
            'button:has-text("Sign in")',
            'button:has-text("Log in")',
        ],
    )

    if not submit:
        log("❌ 没找到登录按钮")
        return False

    if not wait_and_solve_turnstile(
        page,
        submit,
        password_locator=password,
        timeout_sec=35,
    ):
        btn_label = ""
        try:
            btn_label = submit.inner_text().strip()
        except Exception:
            pass
        log(
            "⚠️ 登录按钮始终处于禁用状态 "
            f"({btn_label or 'disabled'})，未能通过 Cloudflare 安全验证"
        )
        return False

    log("🚀 点击登录按钮...")
    try:
        submit.click(timeout=10000)
    except PlaywrightTimeoutError:
        log("❌ 点击登录按钮超时")
        return False

    for _ in range(10):
        page.wait_for_timeout(1500)
        if "/auth/" not in page.url and "/login" not in page.url:
            break

    text = page.locator(
        "body"
    ).inner_text().lower()

    challenge_words = [
        "captcha",
        "verify you are human",
        "complete the security check",
    ]

    if (
        "/server/" not in page.url
        and any(word in text for word in challenge_words)
    ):
        log(
            "⚠️ 检测到验证码/"
            "安全验证未通过"
        )
        return False

    if "/server/" not in page.url:
        page.goto(
            SERVER_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

    wait_for_server_panel_loaded(page)
    return "/server/" in page.url


def is_renew_limit_reached(body_text):
    """检测是否处于未满续期窗口状态（如 Maximum 14 days reached）"""
    limit_patterns = [
        r"Renew\s+Limit\s+Reached",
        r"Maximum\s+\d+\s+days?\s+reached",
        r"You\s+can\s+renew\s+again\s+tomorrow",
        r"when\s+it\s+drops\s+below\s+\d+\s+days?",
    ]
    for pattern in limit_patterns:
        if re.search(pattern, body_text, re.I):
            return True
    return False


def get_renewal_text(page):
    text = page.locator(
        "body"
    ).inner_text()

    # 1. 匹配新版 Jexactyl 面板卡片格式：EXPIRES 6 NOV \n 17 Days
    expires_match = re.search(
        r"EXPIRES\s+([A-Z0-9\s]+?)\s*\n+\s*(\d+\s*Days?)",
        text,
        re.I,
    )
    if expires_match:
        exp_date = expires_match.group(1).strip()
        days_str = expires_match.group(2).strip()
        return f"{days_str} (EXPIRES {exp_date})"

    # 2. 兼容旧版格式
    patterns = [
        r"Renewal\s+in\s+\d+\s+Days?",
        r"Renew\s+in\s+\d+\s+Days?",
        r"\d+\s+Days?\s+until\s+renewal",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.I,
        )
        if match:
            return match.group(0)

    # 3. 匹配达到上限的提示
    max_match = re.search(
        r"Maximum\s+\d+\s+days?\s+reached",
        text,
        re.I,
    )
    if max_match:
        return max_match.group(0)

    if re.search(
        r"Renew\s+Limit\s+Reached",
        text,
        re.I,
    ):
        return "Renew Limit Reached"

    return "未识别"


def find_renew_button(page):
    """精准查找右侧面板的 Renew 按钮，排除广告容器和外层干扰元素"""
    ignore_words = [
        "upgrade",
        "premium",
        "slow server",
        "no renewals",
        "maximum",
        "limit reached",
        "never expire",
    ]

    # 优先查找原生 <button> 标签且文本简短明确的按钮
    buttons = page.locator("button")
    try:
        count = buttons.count()
        for i in range(count):
            btn = buttons.nth(i)
            if not btn.is_visible():
                continue
            raw_text = (btn.inner_text() or "").strip()
            clean_text = re.sub(r"\s+", " ", raw_text).lower()
            if not clean_text:
                continue
            if any(w in clean_text for w in ignore_words):
                continue
            if re.match(
                r"^(?:renew(?:\s+now|\s+server|\s+for\s+free)?|extend(?:\s+server)?|add\s+\d+\s+days?)$",
                clean_text,
                re.I,
            ):
                return btn
    except Exception:
        pass

    # 备选：查找带有 role="button" 或 <a> 标签的 Renew 按钮
    fallback_candidates = [
        page.get_by_role(
            "button",
            name=re.compile(
                r"^(?:Renew(?:\s+Now|\s+Server|\s+for\s+free)?|Extend(?:\s+Server)?)$",
                re.I,
            ),
        ),
        page.locator("a, [role='button']").filter(
            has_text=re.compile(r"^\s*Renew\s*$", re.I)
        ),
    ]

    for group in fallback_candidates:
        try:
            count = group.count()
            for i in range(count):
                item = group.nth(i)
                if not item.is_visible():
                    continue
                btn_text = (item.inner_text() or "").strip().lower()
                if any(w in btn_text for w in ignore_words):
                    continue
                return item
        except Exception:
            pass

    return None


def robust_click(page, locator, desc="按钮"):
    """确保元素滚动到可视区域并执行可靠点击（原生 click + 坐标兜底）"""
    try:
        locator.scroll_into_view_if_needed(timeout=5000)
        page.wait_for_timeout(300)
    except Exception:
        pass

    try:
        locator.click(timeout=5000)
        log(f"🖱️ 已点击 {desc}")
        return True
    except Exception as e:
        log(f"⚠️ 常规点击 {desc} 失败 ({e})，尝试坐标与 JS 点击...")

    try:
        box = locator.bounding_box()
        if box:
            cx = box["x"] + box["width"] / 2
            cy = box["y"] + box["height"] / 2
            page.mouse.move(cx, cy, steps=5)
            time.sleep(0.1)
            page.mouse.click(cx, cy)
            log(f"🖱️ 已通过鼠标坐标点击 {desc}")
            return True
    except Exception:
        pass

    try:
        locator.evaluate("el => el.click()")
        log(f"🖱️ 已通过 JS 触发点击 {desc}")
        return True
    except Exception:
        return False


def confirm_renewal(page, before, first_renew_btn=None):
    """
    处理点击 Renew 后的所有可能流程：
    1. 弹出模态确认框（含各种按钮文案或内嵌 Turnstile）
    2. 无弹窗但页面出现 Turnstile 验证
    3. 点击一次后直接由后端 API 完成续期
    """
    page.wait_for_timeout(2000)

    # 先检查是否直接完成了续期
    body_text = page.locator("body").inner_text()
    after = get_renewal_text(page)
    if renewal_succeeded(before, after, body_text):
        log("✅ 点击 Renew 后已直接完成续期（无需二次弹窗）")
        return True

    # 检查是否有可能弹出了 Turnstile 验证框
    if click_turnstile_box(page):
        log("⏳ 检测到续期阶段 Turnstile 验证，等待通过...")
        page.wait_for_timeout(4000)

    # 查找页面上所有可能的弹窗确认按钮
    modal_confirm_selectors = [
        # 标准 role="dialog" 内部的按钮
        '[role="dialog"] button:has-text("Renew")',
        '[role="dialog"] button:has-text("Confirm")',
        '[role="dialog"] button:has-text("Yes")',
        '[role="dialog"] button:has-text("Continue")',
        '[role="dialog"] button[type="submit"]',
        # 常见 Jexactyl / React Modal / SweetAlert2 容器内的确认按钮
        '[class*="modal" i] button:has-text("Renew")',
        '[class*="modal" i] button:has-text("Confirm")',
        '[class*="dialog" i] button:has-text("Renew")',
        '[class*="dialog" i] button:has-text("Confirm")',
        '.swal2-confirm',
        # 页面上明确叫 Renew now / Confirm renewal 的按钮
        'button:has-text("Renew now")',
        'button:has-text("Renew Now")',
        'button:has-text("Renew Server")',
        'button:has-text("Confirm")',
    ]

    ignore_words = ["cancel", "close", "no", "upgrade", "premium"]

    for attempt in range(4):
        # 1. 尝试按选择器匹配弹窗确认按钮
        for sel in modal_confirm_selectors:
            try:
                loc = page.locator(sel)
                cnt = loc.count()
                for i in range(cnt):
                    btn = loc.nth(i)
                    if not btn.is_visible() or btn.is_disabled():
                        continue
                    txt = (btn.inner_text() or "").strip().lower()
                    if any(w in txt for w in ignore_words):
                        continue
                    log(f"✅ 检测到确认弹窗按钮 [{txt}]，正在点击...")
                    robust_click(page, btn, f"弹窗确认按钮 ({txt})")
                    page.wait_for_timeout(2000)
                    return True
            except Exception:
                pass

        # 2. 如果页面上同时存在 2 个及以上可见的 "Renew" 按钮，最后一个通常是新弹出的 Modal 确认按钮
        try:
            renew_btns = page.locator("button").filter(
                has_text=re.compile(r"^\s*(?:Renew(?:\s+Now|\s+Server)?|Confirm|Yes)\s*$", re.I)
            )
            visible_btns = []
            for i in range(renew_btns.count()):
                b = renew_btns.nth(i)
                if b.is_visible() and not b.is_disabled():
                    visible_btns.append(b)

            if len(visible_btns) >= 2:
                target_btn = visible_btns[-1]
                txt = (target_btn.inner_text() or "").strip()
                log(f"✅ 检测到第二个激活的确认按钮 [{txt}]，正在点击...")
                robust_click(page, target_btn, f"二次确认按钮 ({txt})")
                page.wait_for_timeout(2000)
                return True
        except Exception:
            pass

        # 3. 检查是否因为第一次点击没触发反应，尝试补点一次原按钮
        if attempt == 1 and first_renew_btn is not None:
            body_now = page.locator("body").inner_text()
            after_now = get_renewal_text(page)
            if not renewal_succeeded(before, after_now, body_now):
                log("🔄 未检测到弹窗或状态变化，尝试使用鼠标坐标再次点击 Renew 按钮...")
                try:
                    box = first_renew_btn.bounding_box()
                    if box:
                        page.mouse.click(
                            box["x"] + box["width"] / 2,
                            box["y"] + box["height"] / 2,
                        )
                except Exception:
                    pass

        click_turnstile_box(page)
        page.wait_for_timeout(1500)

        body_text = page.locator("body").inner_text()
        after = get_renewal_text(page)
        if renewal_succeeded(before, after, body_text):
            return True

    log("⚠️ 未检测到标准确认弹窗，继续检查续期结果...")
    return True


def renewal_succeeded(before, after, body_text):
    text = body_text.lower()
    success_words = [
        "renewed successfully",
        "renewal successful",
        "successfully renewed",
        "has been renewed",
        "server renewed",
        "renew limit reached",
        "maximum 14 days reached",
        "you can renew again",
    ]

    if any(word in text for word in success_words):
        return True

    before_days = get_days(before)
    after_days = get_days(after)

    if (
        before_days is not None
        and after_days is not None
        and after_days > before_days
    ):
        return True

    # 对比 EXPIRES 日期字符串是否发生变化（例如从 5 NOV 变成 6 NOV 或 19 NOV）
    before_exp = get_expire_date_str(before)
    after_exp = get_expire_date_str(after)
    if (
        before_exp
        and after_exp
        and before_exp != after_exp
    ):
        return True

    return False


def wait_for_renewal_result(page, before, api_renew_ok=False):
    """轮询页面状态并刷新页面，避免 SPA 缓存导致读取到旧的剩余天数"""
    after = get_renewal_text(page)

    for attempt in range(6):
        body_text = page.locator(
            "body"
        ).inner_text()
        after = get_renewal_text(page)

        if renewal_succeeded(
            before,
            after,
            body_text,
        ):
            return True, after

        page.wait_for_timeout(2000)

        # 在第 2 次和第 4 次轮询时主动刷新页面，强制从服务端拉取最新到期时间
        if attempt in (1, 3):
            log("🔄 刷新页面以获取最新到期状态...")
            page.reload(
                wait_until="domcontentloaded",
                timeout=60000,
            )
            wait_for_server_panel_loaded(page)

    # 如果监听到了后端 renew 接口返回 200/204 成功，也视为成功
    if api_renew_ok:
        after = get_renewal_text(page)
        return True, after

    return False, after


def resolve_headless():
    if HEADLESS_MODE in ("true", "1", "yes"):
        return True
    if HEADLESS_MODE in ("false", "0", "no"):
        return False
    return not bool(os.getenv("DISPLAY"))


def main():
    if not SERVER_URL.startswith(
        "https://panel.host-ship.com/server/"
    ):
        log("❌ SERVER_URL 不正确")

        tg(
            "❌ Host-Ship 配置错误\n"
            "SERVER_URL 不是服务器详情页地址"
        )

        return 1

    log("======================================")
    log(" Host-Ship Free Auto Renew")
    log("======================================")

    log(
        f"🌐 节点状态：{node_status()}"
    )

    ip = current_ip()

    log(
        f"📍 当前出口IP：{ip}"
    )

    use_headless = resolve_headless()
    log(
        f"🖥️ 浏览器模式：{'Headless' if use_headless else 'Headed (XVFB/GUI)'}"
    )

    with sync_playwright() as p:
        launch_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--window-size=1440,1000",
        ]

        browser = p.chromium.launch(
            headless=use_headless,
            proxy={
                "server": PROXY_SERVER
            }
            if IS_PROXY
            else None,
            args=launch_args,
        )

        temp_page = browser.new_page()
        native_ua = temp_page.evaluate("() => navigator.userAgent")
        temp_page.close()
        clean_ua = native_ua.replace("HeadlessChrome/", "Chrome/")

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 1000,
            },
            user_agent=clean_ua,
            locale="en-US",
        )
        context.add_init_script(STEALTH_INIT_SCRIPT)

        page = context.new_page()

        # 监听网络请求，捕捉是否触发了后端的 renew API
        renew_api_status = {"called": False, "ok": False, "status": None, "body": ""}

        def on_response(response):
            try:
                url_lower = response.url.lower()
                if "renew" in url_lower and response.request.method in ("POST", "PUT", "PATCH"):
                    renew_api_status["called"] = True
                    renew_api_status["status"] = response.status
                    renew_api_status["ok"] = 200 <= response.status < 300
                    try:
                        renew_api_status["body"] = response.text()[:300]
                    except Exception:
                        pass
                    log(f"📡 捕获到续期 API 响应: HTTP {response.status} ({response.url})")
            except Exception:
                pass

        page.on("response", on_response)

        try:
            if not login_if_needed(page):
                page.screenshot(
                    path="hostship_login_fail.png",
                    full_page=True,
                )

                tg(
                    build_error_message(
                        "❌ Host-Ship 登录失败",
                        "登录失败或遇到 Cloudflare 安全验证拦截",
                        ip,
                    )
                )

                return 1

            log("✅ 登录成功")

            before = get_renewal_text(page)

            log(
                f"📅 当前续期状态：{before}"
            )

            body = page.locator(
                "body"
            ).inner_text()

            if is_renew_limit_reached(body):
                log(
                    "⏳ 目前未到续期时间（Maximum 14 days reached），"
                    "不进行操作"
                )

                if MANUAL_RUN:
                    tg(
                        build_check_message(
                            before,
                            ip,
                        )
                    )

                return 0

            button = find_renew_button(page)

            if not button:
                page.screenshot(
                    path="hostship_no_renew_button.png",
                    full_page=True,
                )

                tg(
                    build_error_message(
                        "⚠️ Host-Ship 需要检查",
                        (
                            "没有找到可用的 "
                            f"Renew 按钮；当前状态：{before}"
                        ),
                        ip,
                    )
                )

                return 1

            try:
                disabled = button.is_disabled()
            except Exception:
                disabled = False

            if disabled:
                log(
                    "⏳ Renew 按钮当前不可点击（disabled）"
                )

                if MANUAL_RUN:
                    tg(
                        build_check_message(
                            before,
                            ip,
                        )
                    )

                return 0

            log(
                "🔄 已到续期窗口，"
                "点击 Renew..."
            )

            robust_click(page, button, "Renew 主按钮")

            if not confirm_renewal(page, before, first_renew_btn=button):
                page.screenshot(
                    path="hostship_confirm_fail.png",
                    full_page=True,
                )

                tg(
                    build_error_message(
                        "❌ Host-Ship 续期确认失败",
                        (
                            "点击第一层 Renew 后，"
                            "未能完成二次确认"
                        ),
                        ip,
                    )
                )

                return 1

            success, after = wait_for_renewal_result(
                page,
                before,
                api_renew_ok=renew_api_status["ok"],
            )

            if success:
                log(
                    "✅ 续期成功："
                    f"{before} -> {after}"
                )

                tg(
                    build_success_message(
                        before,
                        after,
                        ip,
                    )
                )

                return 0

            # 如果 API 明确返回了错误码（例如 400/403/429 提示还未到可续期时间）
            if renew_api_status["called"] and not renew_api_status["ok"]:
                log(
                    f"⚠️ 续期 API 返回状态码 {renew_api_status['status']}: "
                    f"{renew_api_status['body']}"
                )

            page.screenshot(
                path="hostship_renew_uncertain.png",
                full_page=True,
            )

            log(
                "⚠️ 已点击续期，"
                "但无法确认结果"
            )

            extra_api_info = (
                f"\nAPI响应：HTTP {renew_api_status['status']} ({renew_api_status['body']})"
                if renew_api_status["called"]
                else "\nAPI响应：未捕获到后端续期请求"
            )

            tg(
                build_error_message(
                    "⚠️ Host-Ship 续期结果需要检查",
                    (
                        f"续期前：{before}；"
                        f"续期后：{after}"
                        f"{extra_api_info}"
                    ),
                    ip,
                )
            )

            return 1

        except Exception as exc:
            log(
                f"❌ 运行异常：{exc}"
            )

            try:
                page.screenshot(
                    path="hostship_error.png",
                    full_page=True,
                )
            except Exception:
                pass

            tg(
                build_error_message(
                    "❌ Host-Ship 自动续期异常",
                    str(exc),
                    ip,
                )
            )

            return 1

        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
