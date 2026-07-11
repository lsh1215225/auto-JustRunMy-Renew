#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import json
import socket
import signal
import subprocess
import requests
from typing import Optional
from urllib.parse import urlparse, parse_qs, unquote
from seleniumbase import SB
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

LOGIN_URL = "https://justrunmy.app/id/Account/Login"
DOMAIN    = "justrunmy.app"

# ============================================================
#  环境变量与全局变量
# ============================================================
EMAIL        = os.environ.get("JUSTRUNMY_EMAIL")
PASSWORD     = os.environ.get("JUSTRUNMY_PASSWORD")
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
TG_CHAT_ID   = os.environ.get("TG_CHAT_ID")

HY2_PROXY_URL = os.environ.get("HY2_PROXY_URL", "")
SOCKS_PORT = int(os.environ.get("SOCKS_PORT", "51080"))

if not EMAIL or not PASSWORD:
    print("❌ 致命错误：未找到 JUSTRUNMY_EMAIL 或 JUSTRUNMY_PASSWORD 环境变量！")
    sys.exit(1)

DYNAMIC_APP_NAME = "未知应用"
CURRENT_IP_INFO = "未知 IP"

# ============================================================
#  Hysteria2 代理模块（保持不变）
# ============================================================
class Hy2Proxy:
    def __init__(self, url):
        self.url = url
        self.proc = None

    def start(self):
        if not self.url:
            print("⚠️ 未提供 HY2_PROXY_URL")
            return False
        print("📡 启动 Hysteria2...")
        u = self.url.replace("hysteria2://", "").replace("hy2://", "")
        parsed = urlparse("scheme://" + u)
        params = parse_qs(parsed.query)
        hostname = parsed.hostname
        port = parsed.port
        server = f"[{hostname}]:{port}" if hostname and ':' in hostname else f"{hostname}:{port}"
        cfg = {
            "server": server,
            "auth": unquote(parsed.username),
            "tls": {
                "sni": params.get("sni", [hostname])[0],
                "insecure": params.get("insecure", ["0"])[0] == "1",
                "alpn": params.get("alpn", ["h3"])[0],
            },
            "socks5": {"listen": f"127.0.0.1:{SOCKS_PORT}"}
        }
        path = "/tmp/hy2.json"
        with open(path, "w") as f:
            json.dump(cfg, f)
        self.proc = subprocess.Popen(
            ["hysteria", "client", "-c", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True, text=True
        )
        for _ in range(30):
            time.sleep(1)
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", SOCKS_PORT)) == 0:
                    print("✅ HY2 已就绪")
                    break
        else:
            print("❌ HY2 启动失败")
            return False
        time.sleep(3)
        return True

    def stop(self):
        if self.proc:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            print("🛑 HY2 已停止")

    @property
    def proxy(self):
        return f"socks5://127.0.0.1:{SOCKS_PORT}"


def get_proxy_manager() -> Optional[Hy2Proxy]:
    if HY2_PROXY_URL:
        return Hy2Proxy(HY2_PROXY_URL)
    return None


def mask_ip(ip: str) -> str:
    return ip.rsplit(".", 1)[0] + ".***"


def mask_email(email: str) -> str:
    if "@" not in email:
        return email[0] + "*" * (len(email) - 2) + email[-1] if len(email) > 2 else email
    local, domain = email.split("@", 1)
    masked_local = local[0] + "*" * (len(local) - 2) + local[-1] if len(local) > 2 else local
    return f"{masked_local}@{domain}"


def check_ip(proxy: Optional[str] = None) -> str:
    try:
        proxies = {"http": proxy, "https": proxy} if proxy else None
        r = requests.get("http://ip-api.com/json/?fields=status,query,countryCode", proxies=proxies, timeout=30).json()
        if r.get("status") == "success":
            return f"{mask_ip(r['query'])} ({r['countryCode']}) [{'✅ 代理' if proxy else '⚠️ 直连'}]"
    except:
        pass
    return f"未知 IP [{'✅ 代理' if proxy else '⚠️ 直连'}]"


def start_proxy_with_retry(max_retries=5):
    proxy_manager = get_proxy_manager()
    if not proxy_manager:
        return None, None
    for attempt in range(1, max_retries + 1):
        print(f"🔄 尝试启动代理 ({attempt}/{max_retries})...")
        if proxy_manager.start():
            return proxy_manager, proxy_manager.proxy
        if attempt < max_retries:
            time.sleep(5)
    print("⚠️ 代理启动失败，继续直连")
    return None, None


# ============================================================
#  Telegram 推送模块（保持不变）
# ============================================================
def send_tg_message(status_icon, status_text, time_left):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    local_time = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() + 8 * 3600))
    masked = mask_email(EMAIL)
    text = (
        f"🎮 justrunmy.app 续期报告\n🖥 {DYNAMIC_APP_NAME}\n"
        f"👤 账号: <a href='tg://user?id={TG_CHAT_ID}'>{masked}</a>\n"
        f"🌐 IP: {CURRENT_IP_INFO}\n"
        f"🕐 运行时间: {local_time}\n"
        f"{status_icon} {status_text}\n"
        f"⏱️ 剩余: {time_left}"
    )
    try:
        requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                      json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
        print("  📩 Telegram 通知发送成功！")
    except Exception as e:
        print(f"  ⚠️ Telegram 通知异常: {e}")


# ============================================================
#  页面脚本 & 工具（保持不变）
# ============================================================
# ... (省略 _EXPAND_JS、_EXISTS_JS、_SOLVED_JS、_COORDS_JS、_WININFO_JS、js_fill_input、_activate_window、_xdotool_click、handle_turnstile、login 函数，保持原样)

# 为了篇幅，这里只展示关键的 renew 函数，其余函数请保留你之前的完整代码

def renew(sb) -> bool:
    global DYNAMIC_APP_NAME, CURRENT_IP_INFO
    
    print("\n" + "="*50)
    print("   🚀 开始自动续期流程")
    print("="*50)
    
    print("🌐 进入控制面板: https://justrunmy.app/panel")
    sb.open("https://justrunmy.app/panel")
    time.sleep(4)

    # ==================== 新增：处理 Cookie 弹窗 ====================
    print("🍪 检查并处理 Cookie 弹窗...")
    try:
        if sb.is_element_visible('button:contains("Accept All")'):
            sb.click('button:contains("Accept All")')
            print("✅ 已点击 Accept All")
            time.sleep(2)
        elif sb.is_element_visible('button:contains("Save My Preferences")'):
            sb.click('button:contains("Save My Preferences")')
            print("✅ 已点击 Save My Preferences")
            time.sleep(2)
    except:
        pass
    # ============================================================

    print("🖱️ 自动读取应用名称并点击应用卡片...")

    # ==================== 应用卡片点击（支持 sharp_hypatia） ====================
    app_name = None
    card_selectors = [
        '[class*="app-card"]',
        '[class*="application"]',
        'div[role="button"]',
        'a[href*="/app/"]',
        'a[href*="/panel/"]',
        'h3',
        '.font-semibold'
    ]
    
    for sel in card_selectors:
        try:
            sb.wait_for_element(sel, timeout=15)
            text = sb.get_text(sel)
            if text and len(text.strip()) > 2 and "sharp" in text.lower() or "hypatia" in text.lower() or "application" in text.lower():
                app_name = text.strip()
                print(f"🎯 找到应用卡片: {app_name}")
                sb.click(sel)
                time.sleep(4)
                break
        except:
            pass

    if not app_name:
        # 后备：点击第一个应用卡片
        try:
            sb.wait_for_element('[class*="app-card"]', timeout=10)
            sb.click('[class*="app-card"]')
            time.sleep(4)
            app_name = "sharp_hypatia"
            print(f"✅ 已点击第一个应用卡片")
        except:
            pass

    if app_name:
        DYNAMIC_APP_NAME = app_name.strip()
        print(f"🎯 成功进入应用: {DYNAMIC_APP_NAME}")
    else:
        print("❌ 找不到应用卡片！")
        sb.save_screenshot("renew_app_not_found.png")
        send_tg_message("❌", "续期失败(找不到应用卡片)", "未知")
        return False
    # ============================================================

    print("🖱️ 点击 Reset Timer 按钮...")

    # ==================== 超强 Reset Timer 按钮查找 ====================
    reset_btn = None
    btn_selectors = [
        'button:contains("Reset Timer")',
        'button:contains("Reset Timer")',
        '[class*="reset"]',
        'button[style*="orange"]',
        'button.bg-orange',
        'button:contains("Reset")'
    ]
    
    for sel in btn_selectors:
        try:
            sb.wait_for_element(sel, timeout=15)
            reset_btn = sel
            print(f"✅ 找到 Reset Timer 按钮: {sel}")
            break
        except:
            pass

    if not reset_btn:
        print("⏳ Reset Timer 加载中（额外轮询 20 秒）...")
        for _ in range(20):
            time.sleep(1)
            for sel in btn_selectors:
                try:
                    sb.wait_for_element(sel, timeout=3)
                    reset_btn = sel
                    print(f"✅ 找到 Reset Timer 按钮: {sel}")
                    break
                except:
                    pass
            if reset_btn:
                break

    if reset_btn:
        try:
            sb.click(reset_btn)
            time.sleep(3)
        except Exception as e:
            print(f"⚠️ 点击按钮失败: {e}")
    else:
        print("❌ 找不到 Reset Timer 按钮！")
        sb.save_screenshot("renew_reset_btn_not_found.png")
        send_tg_message("❌", "续期失败(找不到按钮)", "未知")
        return False
    # ============================================================

    print("🛡️ 检查续期弹窗内是否需要 CF 验证...")
    if sb.execute_script(_EXISTS_JS):
        if not handle_turnstile(sb):
            print("❌ 弹窗内的 Turnstile 验证失败")
            sb.save_screenshot("renew_turnstile_fail.png")
            send_tg_message("❌", "续期失败(人机验证未过)", "未知")
            return False

    print("🖱️ 点击 Just Reset 确认续期...")
    try:
        sb.click('button:contains("Just Reset")')
        print("⏳ 提交续期请求，等待服务器处理...")
        time.sleep(5)
    except Exception as e:
        print(f"❌ 找不到 Just Reset 按钮: {e}")
        sb.save_screenshot("renew_just_reset_not_found.png")
        send_tg_message("❌", "续期失败(无法确认)", "未知")
        return False

    print("🔍 验证最终倒计时状态...")
    try:
        sb.refresh()
        time.sleep(4)
        timer_text = sb.get_text('span.font-mono.text-xl')
        print(f"⏱️ 当前应用剩余时间: {timer_text}")
        
        if "2 days" in timer_text or "3 days" in timer_text or "1 day" in timer_text:
            print("✅ 完美！续期任务圆满完成！")
            sb.save_screenshot("renew_success.png")
            send_tg_message("✅", "续期完成", timer_text)
            return True
        else:
            print("⚠️ 倒计时未重置到最高值，请人工检查。")
            sb.save_screenshot("renew_warning.png")
            send_tg_message("⚠️", "续期异常(请检查)", timer_text)
            return True 
    except Exception as e:
        print(f"⚠️ 读取倒计时失败: {e}")
        sb.save_screenshot("renew_timer_read_fail.png")
        send_tg_message("⚠️", "读取剩余时间失败", "未知")
        return False


# ============================================================
#  main 函数（保持不变，只需把 renew 函数替换进去）
# ============================================================
def main():
    print("=" * 50)
    print("   JustRunMy.app 自动登录与续期脚本")
    print("=" * 50)

    proxy_manager, proxy_url = start_proxy_with_retry(max_retries=5)

    print(f"🔍 正在检查 IP 信息（使用代理: {bool(proxy_url)})...")
    ip_info = check_ip(proxy_url)
    print(f"🌐 IP 信息：{ip_info}")
    global CURRENT_IP_INFO
    CURRENT_IP_INFO = ip_info

    sb_kwargs = {"uc": True, "test": True, "headless": False}
    if proxy_url:
        sb_kwargs["proxy"] = proxy_url
        print(f"🔗 挂载代理: {proxy_url}")
    else:
        print("🌐 未使用代理，直连访问")

    try:
        with SB(**sb_kwargs) as sb:
            print("✅ 浏览器已启动")
            if login(sb):
                renew(sb)
            else:
                print("\n❌ 登录失败，终止后续操作。")
                send_tg_message("❌", "登录失败", "未知")
    finally:
        if proxy_manager:
            proxy_manager.stop()


if __name__ == "__main__":
    main()
