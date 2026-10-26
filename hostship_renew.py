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


def build_check_message(status, ip, reason="未到续期时间（需低于 14 天）"):
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
        f"🔒 当前状态：{reason}",
    ]

    if days is not None:
        lines.append(
            f"⏱️ 剩余有效期：{status}"
        )
    else:
        lines.append(
            f"📅 面板状态：{status}"
        )

    if renew_date is not None and days is not None and days >= 14:
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
        divs = page.locator("form div, [role='dialog'] div")
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
                    log("🖱️ 已通过尺寸匹配点击 Turnstile 区域")
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
                page.wait_for_timeout(1500)
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
        r"cannot\s+be\s+renewed\s+yet",
        r"already\s+renewed",
    ]
    for pattern in limit_patterns:
        if re.search(pattern, body_text, re.I):
            return True
    return False


def get_renewal_text(page):
    text = page.locator(
        "body"
    ).inner_text()

    expires_match = re.search(
        r"EXPIRES\s+([A-Z0-9\s]+?)\s*\n+\s*(\d+\s*Days?)",
        text,
        re.I,
    )
    if expires_match:
        exp_date = expires_match.group(1).strip()
        days_str = expires_match.group(2).strip()
        return f"{days_str} (EXPIRES {exp_date})"

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


def inspect_renew_elements(page):
    """打印页面上所有包含 Renew 字样的可见元素详情（标签、文本、坐标、属性），彻底告别盲猜"""
    info_list = page.evaluate("""() => {
        const results = [];
        const all = document.querySelectorAll('button, a, [role="button"], div, span');
        for (const el of all) {
            const text = (el.innerText || '').trim().replace(/\\s+/g, ' ');
            if (!text || !/renew/i.test(text) || text.length > 60) continue;
            const rect = el.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) continue;
            // 只记录叶子节点或直接按钮，避免整页父容器刷屏
            if (el.tagName === 'DIV' && el.querySelectorAll('button, a').length > 0) continue;
            results.push({
                tag: el.tagName.toLowerCase(),
                text: text,
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                w: Math.round(rect.width),
                h: Math.round(rect.height),
                disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
                href: el.getAttribute('href') || '',
                className: (el.className && typeof el.className === 'string') ? el.className.slice(0, 80) : ''
            });
        }
        return results;
    }""")
    log("🔍 页面上与 Renew 相关的元素列表：")
    for idx, item in enumerate(info_list):
        log(
            f"   [{idx}] <{item['tag']}> text='{item['text']}' "
            f"pos=({item['x']},{item['y']} {item['w']}x{item['h']}) "
            f"disabled={item['disabled']} href='{item['href']}'"
        )
    return info_list


def find_right_panel_renew_button(page):
    """
    精准定位右侧状态栏（EXPIRES 卡片下方）的 Renew 按钮，
    严格排除左侧导航栏（x < 300）的 'Renew server' 菜单和下方的 Upgrade 广告
    """
    inspect_renew_elements(page)

    ignore_words = [
        "upgrade",
        "premium",
        "slow server",
        "no renewals",
        "maximum",
        "limit reached",
        "never expire",
    ]

    # 1. 优先寻找位于页面右侧（x > 500）且文字为 Renew 的按钮/可点击元素
    candidates = page.locator("button, a, [role='button'], div")
    best_match = None

    try:
        count = candidates.count()
        for i in range(count):
            el = candidates.nth(i)
            if not el.is_visible():
                continue

            raw_text = (el.inner_text() or "").strip()
            clean_text = re.sub(r"\s+", " ", raw_text)
            if not clean_text or len(clean_text) > 30:
                continue

            lower_text = clean_text.lower()
            if any(w in lower_text for w in ignore_words):
                continue

            # 匹配 "Renew" 或 "Renew Now"
            if not re.match(r"^renew(?:\s+now)?$", lower_text, re.I):
                continue

            box = el.bounding_box()
            if not box:
                continue

            # 右侧面板的卡片宽度通常在 200~500 之间，且 x 坐标在右侧（> 500）
            if box["x"] > 500 and 80 <= box["width"] <= 550 and 24 <= box["height"] <= 80:
                tag_name = el.evaluate("el => el.tagName.toLowerCase()")
                log(
                    f"🎯 锁定右侧 Renew 按钮: <{tag_name}> '{clean_text}' "
                    f"坐标=({int(box['x'])}, {int(box['y'])}, {int(box['width'])}x{int(box['height'])})"
                )
                # 如果它是 button 或 a，直接返回；如果是外层 div，继续看里面有没有子 button
                if tag_name in ("button", "a"):
                    return el
                best_match = el
    except Exception as exc:
        log(f"⚠️ 扫描右侧按钮异常: {exc}")

    if best_match is not None:
        return best_match

    # 2. 退一步：查找任意 x > 300 的含 Renew 的 button
    buttons = page.locator("button")
    try:
        for i in range(buttons.count()):
            btn = buttons.nth(i)
            if not btn.is_visible():
                continue
            txt = re.sub(r"\s+", " ", (btn.inner_text() or "").strip()).lower()
            if any(w in txt for w in ignore_words):
                continue
            if "renew" in txt:
                box = btn.bounding_box()
                if box and box["x"] > 300:
                    return btn
    except Exception:
        pass

    return None


def trigger_click_all_ways(page, locator, desc="按钮"):
    """使用 Playwright click + 真实鼠标移动点击 + JS dispatchEvent 确保 React 100% 收到点击事件"""
    try:
        locator.scroll_into_view_if_needed(timeout=5000)
        page.wait_for_timeout(300)
    except Exception:
        pass

    box = None
    try:
        box = locator.bounding_box()
    except Exception:
        pass

    if box:
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2
        log(f"🖱️ 移动鼠标并点击 {desc} 中心坐标: ({int(cx)}, {int(cy)})")
        page.mouse.move(cx, cy, steps=8)
        time.sleep(0.15)
        page.mouse.down()
        time.sleep(0.08)
        page.mouse.up()
        page.wait_for_timeout(500)

    try:
        locator.click(timeout=4000)
    except Exception:
        pass


def dump_page_diff(before_lines, page):
    """打印点击按钮后页面上新出现的文字（如弹窗内容、Toast 提示）"""
    try:
        current_text = page.locator("body").inner_text()
        current_lines = [
            line.strip()
            for line in current_text.splitlines()
            if line.strip()
        ]
        added = [
            line for line in current_lines
            if line not in before_lines and not line.startswith("[定时重启")
        ]
        if added:
            log(f"📄 点击后页面新增文本: {added[:15]}")
        else:
            log("📄 点击后页面文本无明显新增")
        return added
    except Exception:
        return []


def handle_post_click_flow(page, before, right_renew_btn, api_tracker):
    """
    处理点击右侧 Renew 后的完整交互：
    - 检测页面 URL 变化或新增弹窗文本
    - 处理弹窗内可能存在的 Cloudflare Turnstile 验证码
    - 点击弹窗内的确认按钮
    - 如果右侧按钮毫无反应，尝试点击左侧导航栏的 'Renew server' 页面进行续期
    """
    before_body = page.locator("body").inner_text()
    before_lines = set(
        line.strip() for line in before_body.splitlines() if line.strip()
    )

    trigger_click_all_ways(page, right_renew_btn, "右侧 Renew 主按钮")
    page.wait_for_timeout(2500)

    added_lines = dump_page_diff(before_lines, page)

    # 如果第一次点完页面没有任何新增文本，也没触发任何 API，可能是点到了按钮里的图标或外层，尝试用 JS 直接点击该元素及其父/子元素
    if not added_lines and not api_tracker["called"]:
        log("🔄 第一次点击未触发弹窗或 API，尝试通过 JS 触发按钮及父级点击事件...")
        try:
            right_renew_btn.evaluate("""el => {
                el.click();
                if (el.parentElement) el.parentElement.click();
                const btn = el.querySelector('button, a');
                if (btn) btn.click();
            }""")
        except Exception:
            pass
        page.wait_for_timeout(2500)
        added_lines = dump_page_diff(before_lines, page)

    # 检查是否已经直接续期成功或弹出提示（如冷却时间未到）
    body_now = page.locator("body").inner_text()
    after_now = get_renewal_text(page)
    if renewal_succeeded(before, after_now, body_now):
        log("✅ 点击后已直接完成续期")
        return True

    # 检查页面上是否出现了 Turnstile 验证框（很多 Jexactyl 面板点击 Renew 后会在弹窗或按钮下方渲染 Turnstile）
    for wait_round in range(6):
        if click_turnstile_box(page):
            log(f"⏳ 已点击续期阶段的 Turnstile 验证框 (第 {wait_round + 1} 次)，等待验证通过...")
            page.wait_for_timeout(3500)
        else:
            break

    # 扫描当前页面所有按钮，看看有没有新出现的弹窗确认按钮（Confirm / Renew now / Yes 等）
    inspect_renew_elements(page)

    modal_selectors = [
        '[role="dialog"] button',
        '[class*="modal" i] button',
        '[class*="dialog" i] button',
        '.swal2-confirm',
        'button:has-text("Renew now")',
        'button:has-text("Renew Now")',
        'button:has-text("Confirm")',
        'button:has-text("Yes")',
        'button:has-text("Continue")',
        'button[type="submit"]',
    ]

    ignore_words = ["cancel", "close", "no", "upgrade", "premium", " dismissal"]

    for attempt in range(4):
        click_turnstile_box(page)

        for sel in modal_selectors:
            try:
                loc = page.locator(sel)
                for i in range(loc.count()):
                    btn = loc.nth(i)
                    if not btn.is_visible():
                        continue
                    txt = re.sub(r"\s+", " ", (btn.inner_text() or "").strip())
                    if not txt or any(w in txt.lower() for w in ignore_words):
                        continue
                    if btn.is_disabled():
                        log(f"⏳ 发现弹窗按钮 [{txt}] 但处于禁用状态，尝试等待 Turnstile 解锁...")
                        click_turnstile_box(page)
                        page.wait_for_timeout(3000)
                    if not btn.is_disabled():
                        log(f"✅ 点击弹窗确认按钮: [{txt}]")
                        trigger_click_all_ways(page, btn, f"弹窗确认按钮 ({txt})")
                        page.wait_for_timeout(2500)
                        dump_page_diff(before_lines, page)
                        return True
            except Exception:
                pass

        page.wait_for_timeout(1500)

    # 如果右侧的 Renew 按钮点击后完全是死按钮（前端 Bug），尝试点击左侧边栏的 "Renew server" 菜单项或者直接请求后端续期 API
    if not api_tracker["called"]:
        log("⚠️ 点击右侧 Renew 未触发任何后端请求，尝试查找左侧菜单 'Renew server' 或直接调用后端续期 API...")

        # 尝试点击左侧导航栏中的 Renew server
        try:
            left_renew = page.locator("a, button, div, span").filter(
                has_text=re.compile(r"^Renew\s+server$", re.I)
            ).first
            if left_renew.count() and left_renew.is_visible():
                log("🧭 发现左侧边栏 'Renew server' 入口，正在点击进入...")
                trigger_click_all_ways(page, left_renew, "左侧 Renew server 菜单")
                page.wait_for_timeout(3000)
                dump_page_diff(before_lines, page)
                inspect_renew_elements(page)

                # 如果进入了专门的续期子页面或弹出了新界面，处理里面的 Turnstile 和按钮
                for _ in range(3):
                    click_turnstile_box(page)
                    page.wait_for_timeout(2000)

                sub_btns = page.locator("button")
                for i in range(sub_btns.count()):
                    b = sub_btns.nth(i)
                    if not b.is_visible() or b.is_disabled():
                        continue
                    t = re.sub(r"\s+", " ", (b.inner_text() or "").strip())
                    if re.search(r"renew|confirm|extend", t, re.I) and not any(
                        w in t.lower() for w in ignore_words
                    ):
                        log(f"🖱️ 在子界面中点击续期按钮: [{t}]")
                        trigger_click_all_ways(page, b, f"子页面按钮 ({t})")
                        page.wait_for_timeout(3000)
                        break
        except Exception as exc:
            log(f"⚠️ 尝试左侧菜单异常: {exc}")

    # 终极保底：如果还是没有触发任何 renew API，在浏览器上下文内直接用 fetch 探测常见的 Jexactyl/Pterodactyl 续期 API 端点
    if not api_tracker["called"]:
        srv_id = server_id()
        log(f"📡 尝试通过浏览器会话直接调用后端续期接口 (Server ID: {srv_id})...")
        api_results = page.evaluate("""async (srvId) => {
            const csrfMeta = document.querySelector('meta[name="csrf-token"]');
            const xsrfCookie = document.cookie.split('; ').find(row => row.startsWith('XSRF-TOKEN='));
            const xsrfToken = xsrfCookie ? decodeURIComponent(xsrfCookie.split('=')[1]) : '';
            const headers = {
                'Accept': 'application/json, text/plain, */*',
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            };
            if (csrfMeta && csrfMeta.content) headers['X-CSRF-TOKEN'] = csrfMeta.content;
            if (xsrfToken) headers['X-XSRF-TOKEN'] = xsrfToken;

            const endpoints = [
                `/api/client/servers/${srvId}/renew`,
                `/api/client/servers/${srvId}/renewal`,
                `/api/client/store/renew/${srvId}`,
            ];
            const logs = [];
            for (const ep of endpoints) {
                try {
                    const res = await fetch(ep, {
                        method: 'POST',
                        headers: headers,
                        credentials: 'same-origin',
                        body: JSON.stringify({})
                    });
                    const txt = await res.text();
                    logs.push({ ep, status: res.status, body: txt.slice(0, 200) });
                    if (res.status >= 200 && res.status < 300) break;
                } catch (e) {
                    logs.push({ ep, status: 0, body: String(e) });
                }
            }
            return logs;
        }""", srv_id)

        for r in api_results:
            log(f"   -> POST {r['ep']} => HTTP {r['status']} | {r['body']}")

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
    """轮询并重新回到服务器主页检查最新到期天数"""
    after = get_renewal_text(page)

    for attempt in range(5):
        if SERVER_URL not in page.url:
            page.goto(SERVER_URL, wait_until="domcontentloaded", timeout=60000)
            wait_for_server_panel_loaded(page)

        body_text = page.locator("body").inner_text()
        after = get_renewal_text(page)

        if renewal_succeeded(before, after, body_text):
            return True, after

        page.wait_for_timeout(2000)

        if attempt in (1, 3):
            log("🔄 刷新页面以获取最新到期状态...")
            page.goto(SERVER_URL, wait_until="domcontentloaded", timeout=60000)
            wait_for_server_panel_loaded(page)

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

        # 监听所有非静态资源的 POST/PUT/PATCH/DELETE 请求以及含 renew 的请求
        api_tracker = {"called": False, "ok": False, "status": None, "body": ""}

        def on_response(response):
            try:
                url = response.url
                method = response.request.method
                if any(ext in url for ext in (".js", ".css", ".png", ".woff", ".svg", "cloudflare")):
                    return
                if method in ("POST", "PUT", "PATCH", "DELETE") or "renew" in url.lower():
                    body_preview = ""
                    try:
                        body_preview = response.text()[:300].replace("\n", " ")
                    except Exception:
                        pass
                    log(f"📡 网络响应 [{method}] HTTP {response.status} -> {url} | {body_preview}")
                    if "renew" in url.lower():
                        api_tracker["called"] = True
                        api_tracker["status"] = response.status
                        api_tracker["ok"] = 200 <= response.status < 300
                        api_tracker["body"] = body_preview
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

            button = find_right_panel_renew_button(page)

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
                disabled = button.is_disabled() or (
                    button.get_attribute("aria-disabled") == "true"
                )
            except Exception:
                disabled = False

            if disabled:
                log(
                    "⏳ Renew 按钮当前处于禁用状态（未到可续期冷却窗口）"
                )

                if MANUAL_RUN:
                    tg(
                        build_check_message(
                            before,
                            ip,
                            reason="Renew 按钮当前处于禁用/冷却状态",
                        )
                    )

                return 0

            log(
                "🔄 已定位右侧 Renew 按钮，开始执行续期流程..."
            )

            handle_post_click_flow(page, before, button, api_tracker)

            success, after = wait_for_renewal_result(
                page,
                before,
                api_renew_ok=api_tracker["ok"],
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

            # 如果后端明确返回了冷却限制提示（例如 400/429 Too Many Requests 或未到时间）
            api_body_lower = (api_tracker.get("body") or "").lower()
            if any(
                kw in api_body_lower
                for kw in ("limit", "maximum", "already", "wait", "cooldown", "hours", "days", "cannot")
            ):
                log(f"⏳ 后端接口提示当前暂不可续期: {api_tracker['body']}")
                if MANUAL_RUN:
                    tg(
                        build_check_message(
                            before,
                            ip,
                            reason=f"后端提示：{api_tracker['body']}",
                        )
                    )
                return 0

            page.screenshot(
                path="hostship_renew_uncertain.png",
                full_page=True,
            )

            log(
                "⚠️ 已点击续期，但无法确认结果"
            )

            extra_api_info = (
                f"\nAPI响应：HTTP {api_tracker['status']} ({api_tracker['body']})"
                if api_tracker["called"]
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
