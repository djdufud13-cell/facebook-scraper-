import sys
import os
import time
import re
import random
import logging
import threading
import uuid
import queue
from urllib.parse import quote
from datetime import datetime

from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.sync_api import sync_playwright

app = Flask(__name__)
CORS(app)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('api_server.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

tasks = {}
task_lock = threading.Lock()

work_queue     = queue.Queue()    # 主线程 → Worker：提交任务
result_queue   = queue.Queue()    # Worker → 结果读取线程：返回结果
task_queue     = queue.Queue()    # Flask API → QueueProcessor：任务分派

def human_delay(min_sec=1, max_sec=3):
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)

def human_mouse_move(page, target_x, target_y, steps=8):
    start_x = random.randint(50, 400)
    start_y = random.randint(50, 400)
    for i in range(steps):
        progress = i / steps
        ease_progress = progress * progress * (3 - 2 * progress)
        current_x = int(start_x + (target_x - start_x) * ease_progress)
        current_y = int(start_y + (target_y - start_y) * ease_progress)
        current_x += random.randint(-5, 5)
        current_y += random.randint(-5, 5)
        page.mouse.move(current_x, current_y)
        time.sleep(random.uniform(0.02, 0.05))

def human_click(page, x, y):
    human_mouse_move(page, x, y)
    time.sleep(random.uniform(0.1, 0.2))
    page.mouse.click(x, y)
    logger.info(f"点击坐标: ({x}, {y})")

def human_scroll(page, distance=300, steps=5):
    for _ in range(steps):
        scroll_amount = distance // steps + random.randint(-50, 50)
        page.mouse.wheel(0, scroll_amount)
        time.sleep(random.uniform(0.3, 0.8))

def human_type(page, element, text):
    element.click()
    time.sleep(random.uniform(0.2, 0.4))
    element.fill('')
    time.sleep(random.uniform(0.1, 0.2))
    for char in text:
        if char == ' ':
            page.keyboard.press('Space')
        elif char == '\n':
            page.keyboard.press('Enter')
        else:
            page.keyboard.type(char, delay=random.uniform(50, 150))
        time.sleep(random.uniform(0.05, 0.15))
    logger.info(f"输入文本: {text[:20]}...")

class Task:
    def __init__(self, task_id, task_type, params):
        self.task_id = task_id
        self.task_type = task_type
        self.params = params
        self.status = "pending"
        self.progress = 0
        self.message = "等待执行"
        self.result = None
        self.error = None
        self.created_at = datetime.now().isoformat()
        self.started_at = None
        self.completed_at = None
        self.callback_url = params.get('callback_url')

    def update(self, status, progress=None, message=None, result=None, error=None):
        with task_lock:
            self.status = status
            if progress is not None:
                self.progress = progress
            if message is not None:
                self.message = message
            if result is not None:
                self.result = result
            if error is not None:
                self.error = error
            if status == "running" and self.started_at is None:
                self.started_at = datetime.now().isoformat()
            if status in ["completed", "failed"]:
                self.completed_at = datetime.now().isoformat()

def check_login_status(page):
    try:
        logger.info("检查登录状态...")
        time.sleep(1)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except:
            pass
        current_url = page.url
        logger.info(f"当前页面URL: {current_url}")
        if 'login' in current_url.lower():
            return False
        try:
            email_input = page.query_selector('#email')
            if email_input and email_input.is_visible():
                return False
        except:
            pass
        try:
            login_button = page.query_selector('button[name="login"]')
            if login_button and login_button.is_visible():
                return False
        except:
            pass
        try:
            content = page.content()
            if 'id="bluebarID"' in content or 'data-click="bluebar_logo"' in content:
                return True
        except:
            pass
        try:
            profile_avatar = page.query_selector('[data-pagelet="NavAvatar"]')
            if profile_avatar:
                return True
        except:
            pass
        if current_url == "https://www.facebook.com/" or current_url.startswith("https://www.facebook.com?"):
            return True
        return False
    except Exception as e:
        logger.error(f"检查登录状态时出错: {e}")
        return False

def extract_user_links(page, keyword):
    logger.info(f"开始搜索关键词: {keyword}")
    links = []
    try:
        page.goto("https://www.facebook.com", wait_until="load", timeout=120000)
        human_delay(3, 5)
        
        if not check_login_status(page):
            return {"error": "未登录，请先在浏览器中登录Facebook", "links": []}
        
        search_box = None
        selectors = [
            'input[placeholder*="Search" i]',
            'input[type="search"]',
            '[aria-label*="Search" i]',
            'input[name="q"]',
            'input[data-testid="search-box-input"]'
        ]
        for sel in selectors:
            search_box = page.query_selector(sel)
            if search_box:
                logger.info(f"找到搜索框: {sel}")
                break
        if search_box:
            box = search_box.bounding_box()
            if box:
                human_click(page, int(box['x'] + box['width']/2), int(box['y'] + box['height']/2))
            human_delay(0.5, 1)
            human_type(page, search_box, keyword)
            human_delay(1, 2)
            page.keyboard.press("Enter")
            logger.info(f"搜索关键词: {keyword}")
            human_delay(5, 8)
        else:
            search_url = f"https://www.facebook.com/search?q={quote(keyword)}"
            page.goto(search_url, wait_until="load", timeout=60000)
            human_delay(5, 8)

        human_delay(2, 3)
        page_filter_selectors = [
            'span:text-is("公共主页")',
            'span:text("公共主页")',
            'span:text("Pages")',
        ]
        filter_clicked = False
        for sel in page_filter_selectors:
            try:
                elements = page.query_selector_all(sel)
                for element in elements:
                    if element and element.is_visible():
                        box = element.bounding_box()
                        if box and box['width'] > 30 and box['height'] > 10:
                            human_click(page, int(box['x'] + box['width']/2), int(box['y'] + box['height']/2))
                            logger.info(f"点击了筛选选项: {sel}")
                            filter_clicked = True
                            human_delay(2, 3)
                            break
                if filter_clicked:
                    break
            except:
                continue

        if not filter_clicked:
            pages_url = f"https://www.facebook.com/search?q={quote(keyword)}&filters=bp_exact"
            page.goto(pages_url, wait_until="load", timeout=60000)
        else:
            human_delay(5, 8)

        logger.info("等待搜索结果渲染...")
        human_delay(8, 12)

        all_links = []
        prev_height = 0
        bottom_count = 0

        for scroll_idx in range(20):
            try:
                js_script = """
                var results = [];
                var elements = document.querySelectorAll('a[href]');
                for (var i = 0; i < elements.length; i++) {
                    var href = elements[i].href;
                    if (href) {
                        var clean = href.split('?')[0];
                        if (clean.length < 200 && results.indexOf(clean) === -1) {
                            results.push(clean);
                        }
                    }
                }
                results;
                """
                current_links = page.evaluate(js_script)
                for link in current_links:
                    if link not in all_links:
                        all_links.append(link)
            except Exception as e:
                logger.warning(f"JS提取失败: {e}")

            current_height = page.evaluate("document.body.scrollHeight")
            if current_height == prev_height:
                bottom_count += 1
                if bottom_count >= 3:
                    break
            else:
                prev_height = current_height
                bottom_count = 0

            logger.info(f"第 {scroll_idx + 1} 次滚动，累计找到 {len(all_links)} 个链接")
            human_scroll(page, 800)
            human_delay(3, 5)

        user_link_patterns = [
            r'https://www\.facebook\.com/profile\.php\?id=\d+',
            r'https://www\.facebook\.com/([a-zA-Z0-9._-]+)+(\?.*)?$',
            r'https://www\.facebook\.com/[a-zA-Z0-9]+',
            r'https://www\.facebook\.com/pages/[^/]+/\d+',
        ]
        exclude_patterns = [
            'facebook.com/profile.php', 'facebook.com/reel/', 'facebook.com/groups/', 'facebook.com/friends/',
            'facebook.com/notifications/', 'facebook.com/help/', 'facebook.com/marketplace/',
            'facebook.com/watch/', 'facebook.com/gaming/', 'facebook.com/news/', 'facebook.com/sports/',
            'facebook.com/music/', 'facebook.com/tv/', 'facebook.com/newsfeed/',
            'facebook.com/settings/', 'facebook.com/login/', 'facebook.com/ads/',
            'facebook.com/search', 'facebook.com/hashtag/', 'facebook.com/explore/',
            'facebook.com/photo.php', 'facebook.com/photos/', 'facebook.com/media/',
            'facebook.com/album/', 'facebook.com/stories/', 'facebook.com/story/',
            'facebook.com/posts/', 'facebook.com/videos/', 'facebook.com/events/',
            'facebook.com/games/', 'facebook.com/offers/',
            'facebook.com/reactions/', 'facebook.com/comments/', 'facebook.com/shares/',
            'facebook.com/likes/', 'facebook.com/pfbid/',
            'about:', 'mailto:', 'tel:', 'javascript:', '#',
        ]

        logger.info(f"开始过滤 {len(all_links)} 个链接...")
        for idx, link in enumerate(all_links):
            if idx % 100 == 0:
                logger.info(f"过滤进度: {idx}/{len(all_links)}")
            is_valid = False
            for pattern in user_link_patterns:
                if re.search(pattern, link):
                    is_valid = True
                    break
            if is_valid:
                excluded = False
                for pattern in exclude_patterns:
                    if pattern in link:
                        excluded = True
                        break
                if not excluded and link not in links:
                    links.append(link)
                    if len(links) <= 20 or len(links) % 10 == 0:
                        logger.info(f"有效用户链接 #{len(links)}: {link}")

        logger.info(f"去重前: {len(links)} 个")
        links = list(set(links))
        logger.info(f"去重后: {len(links)} 个")
        links.sort(key=len, reverse=True)
        logger.info(f"共提取到 {len(links)} 个有效用户链接")
        return {"success": True, "links": links, "count": len(links)}
    except Exception as e:
        logger.error(f"搜索失败: {e}", exc_info=True)
        return {"error": str(e), "links": []}

def extract_user_info(page, user_url):
    logger.info(f"正在提取用户信息: {user_url}")
    try:
        page.goto(user_url, wait_until="load", timeout=60000)
        human_delay(5, 8)
        human_scroll(page, 300)
        human_delay(2, 3)

        phone = ""
        whatsapp = ""
        email = ""
        website = ""
        address = ""

        # ─────────────────────────────────────────────
        # Bug fix 1: 网站字段误取 Facebook CDN 链接
        # 原因: 正则匹配任何 >15 字符的 URL，Facebook CDN 链接很长被误抓
        # 修复: 只接受真实域名，排除 fbcdn / xx.fbcdn / static.xx.fbcdn / l.facebook
        # ─────────────────────────────────────────────
        try:
            content = page.content()
            
            # 电话: 优先带 + 的国际号码，排除纯数字 Facebook UID (12-15位)
            phone_patterns = [
                r'\+[0-9]{1,4}[\s.-]?\(?[0-9]{1,4}\)?[\s.-]?[0-9]{3,4}[\s.-]?[0-9]{4,5}',
                r'\+[0-9]{7,15}',
                r'\(?\+\d{1,3}\)?[\s.-]?[0-9]{8,12}',
            ]
            valid_phones = []
            for pattern in phone_patterns:
                phones = re.findall(pattern, content)
                for p in phones:
                    clean = re.sub(r'[^0-9+]', '', p)
                    if 8 <= len(clean) <= 16 and '+' in p:
                        valid_phones.append((p, clean))
            
            # 再试不带 + 的标准格式（印度手机号等）
            if not valid_phones:
                fallback_patterns = [
                    r'[0-9]{10,11}',  # 如 9883775947, 8056266662
                ]
                for pattern in fallback_patterns:
                    phones = re.findall(pattern, content)
                    for p in phones:
                        clean = re.sub(r'[^0-9+]', '', p)
                        if 10 <= len(clean) <= 11:
                            valid_phones.append((p, clean))
            
            unique_phones = []
            seen = set()
            for p, clean in valid_phones:
                if clean not in seen:
                    seen.add(clean)
                    unique_phones.append((p, clean))
            # 优先 + 号码，再按长度降序
            unique_phones.sort(key=lambda x: (('+' in x[0]) * -1, len(re.sub(r'\D', '', x[1])) * -1))
            if unique_phones:
                phone = unique_phones[0][0]
                logger.info(f"找到电话: {phone}")

            email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
            emails = re.findall(email_pattern, content)
            for em in emails:
                if all(kw not in em.lower() for kw in ['facebook', 'fb', 'noreply', 'support', 'instagram', 'twitter']):
                    email = em
                    logger.info(f"找到邮箱: {email}")
                    break

            # 网站: 排除 Facebook CDN 域名
            website_pattern = r'https?://[a-zA-Z0-9.-]+(?:\.[a-zA-Z]{2,}){1,3}(?:/[^\s]*)?'
            websites = re.findall(website_pattern, content)
            valid_websites = []
            for web in websites:
                if isinstance(web, tuple):
                    web = web[0]
                lower_web = web.lower()
                # 排除所有 Facebook 相关域名
                if any(bad in lower_web for bad in [
                    'facebook.com', 'fbcdn', 'fb.com', 'fbsb', 'instagram.com',
                    'static.xx.fbcdn', 'static.fbcdn', 'xx.fbcdn', 'l.facebook',
                    'lm.facebook', 'm.facebook', 'web.facebook',
                    'linkedin.com', 'twitter.com', 'youtu.be', 'youtube.com',
                    'pinterest.com', 'whatsapp.com',  # 不在网站字段
                ]):
                    continue
                # 排除 URL 参数中的 facebook 重定向
                if 'redirect' in lower_web or 'l.php' in lower_web:
                    continue
                # 最小有意义域名长度
                domain = lower_web.split('://')[-1].split('/')[0]
                if len(domain) < 6:
                    continue
                valid_websites.append(web)
            
            valid_websites.sort(key=len, reverse=True)
            if valid_websites:
                website = valid_websites[0]
                logger.info(f"找到网站: {website}")
        except Exception as e:
            logger.warning(f"正则提取失败: {e}")

        # ─────────────────────────────────────────────
        # Bug fix 2 & 3: WhatsApp 解析 & 电话去 Facebook UID
        # ─────────────────────────────────────────────
        all_links = page.query_selector_all('a')
        logger.info(f"找到 {len(all_links)} 个链接")

        for link_el in all_links:
            href = link_el.get_attribute('href') or ''
            href_lower = href.lower()
            text = link_el.inner_text() or ''
            
            # Bug fix 3: 排除 tel: 中的 Facebook UID
            # Facebook UID 是纯数字，真实电话带国家码
            if 'tel:' in href_lower and not phone:
                raw_phone = href.replace('tel:', '')
                # 必须是数字且带 + 才可能是真实电话
                if '+' in raw_phone or (raw_phone.isdigit() and len(raw_phone) >= 10):
                    phone = raw_phone
                    logger.info(f"找到电话(链接): {phone}")

            elif 'mailto:' in href_lower and not email:
                em = href.replace('mailto:', '')
                if '@' in em:
                    email = em
                    logger.info(f"找到邮箱(链接): {email}")

            elif 'http' in href_lower and not website:
                # Bug fix 2: WhatsApp 链接解析
                # 格式1: wa.me/91XXXXXXXXXX
                # 格式2: api.whatsapp.com/send?phone=91XXXXXXXXXX
                # 格式3: whatsapp.me/send?phone=...
                if 'wa.me/' in href_lower:
                    import urllib.parse
                    parsed = urllib.parse.urlparse(href)
                    path = parsed.path.lstrip('/')
                    # wa.me/91XXXXXXXXXX → +91XXXXXXXXXX
                    if path.isdigit():
                        whatsapp = '+' + path
                    else:
                        whatsapp = path
                    logger.info(f"找到WhatsApp(wa.me): {whatsapp}")
                
                elif 'api.whatsapp.com/send' in href_lower or 'whatsapp.me/send' in href_lower:
                    import urllib.parse
                    parsed = urllib.parse.urlparse(href)
                    query = urllib.parse.parse_qs(parsed.query)
                    if 'phone' in query:
                        raw_ph = query['phone'][0]
                        if not raw_ph.startswith('+'):
                            raw_ph = '+' + raw_ph
                        whatsapp = raw_ph
                        logger.info(f"找到WhatsApp(api): {whatsapp}")
                
                # Bug fix 1: 排除 l.facebook 重定向（含 wa.me）
                elif 'l.facebook.com/l.php' in href_lower:
                    import urllib.parse
                    parsed = urllib.parse.urlparse(href)
                    query = urllib.parse.parse_qs(parsed.query)
                    if 'u' in query:
                        redirect_url = urllib.parse.unquote(query['u'][0])
                        redirect_lower = redirect_url.lower()
                        # 检查重定向目标是否是 WhatsApp
                        if 'wa.me/' in redirect_lower:
                            path = redirect_lower.split('wa.me/')[1].split('?')[0].split('/')[0]
                            whatsapp = '+' + path if path.isdigit() else path
                            logger.info(f"找到WhatsApp(重定向): {whatsapp}")
                        # 排除重定向到 facebook.com 的网站
                        elif 'facebook.com' not in redirect_lower:
                            website = redirect_url
                            logger.info(f"找到网站(重定向): {website}")
                
                # 普通网站链接
                elif not any(bad in href_lower for bad in ['facebook.com', 'fbcdn', 'instagram', 'twitter', 'linkedin', 'youtube', 'pinterest']):
                    if not website:
                        website = href
                        logger.info(f"找到网站(链接): {website}")

        # 如果 WhatsApp 还是空的，从页面文字中找
        if not whatsapp:
            try:
                whatsapp_text = page.query_selector('[href*="wa.me"], [href*="whatsapp"]')
                if whatsapp_text:
                    href = whatsapp_text.get_attribute('href') or ''
                    if 'wa.me/' in href:
                        import urllib.parse
                        path = urllib.parse.urlparse(href).path.lstrip('/')
                        if path.isdigit():
                            whatsapp = '+' + path
                        else:
                            whatsapp = path
                        logger.info(f"找到WhatsApp(text): {whatsapp}")
            except:
                pass

        # 额外: 从页面结构找联系信息区域
        try:
            contact_selectors = [
                '[data-pagelet*="Contact"]',
                '[data-pagelet*="About"]',
                'div[aria-label*="Contact"]',
                'div[aria-label*="电话"]',
            ]
            for sel in contact_selectors:
                try:
                    el = page.query_selector(sel)
                    if el:
                        text = el.inner_text()
                        if '@' in text and not email:
                            emails_found = re.findall(email_pattern, text)
                            for em in emails_found:
                                if all(kw not in em.lower() for kw in ['facebook', 'noreply']):
                                    email = em
                                    logger.info(f"从联系区域找到邮箱: {email}")
                                    break
                except:
                    continue
        except:
            pass

        logger.info(f"提取完成: 电话={phone}, WhatsApp={whatsapp}, 邮箱={email}, 网站={website}")
        return {
            "success": True,
            "link": user_url,
            "phone": phone,
            "whatsapp": whatsapp,
            "email": email,
            "website": website,
            "address": address
        }
    except Exception as e:
        logger.error(f"提取用户 {user_url} 信息失败: {e}", exc_info=True)
        return {"error": str(e), "link": user_url}


# ===== Playwright Worker =====

def playwright_worker():
    """
    工作线程：所有 Playwright 操作都在此线程中运行。
    从 work_queue 接收任务，把结果放入 result_queue。
    """
    global playwright_page
    pw = None
    context = None
    try:
        pw = sync_playwright().start()
        user_data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'UserData')
        os.makedirs(user_data_dir, exist_ok=True)
        logger.info(f"[Worker] 使用用户数据目录: {user_data_dir}")
        
        context = pw.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
            viewport={'width': 1280, 'height': 800},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='zh-CN',
            args=['--disable-blink-features=AutomationControlled', '--disable-dev-shm-usage', '--no-default-browser-check']
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en-US', 'en'] });
            window.chrome = { runtime: {} };
        """)
        playwright_page = context.pages[0] if context.pages else context.new_page()
        logger.info("[Worker] 浏览器启动成功!")

        while True:
            item = work_queue.get()
            if item is None:  # 退出信号
                break
            
            task_id, func_name, args = item
            logger.info(f"[Worker] 执行任务 {task_id}: {func_name}")
            
            try:
                if func_name == 'extract_user_links':
                    result = extract_user_links(playwright_page, *args)
                elif func_name == 'extract_user_info':
                    result = extract_user_info(playwright_page, *args)
                elif func_name == 'check_login':
                    result = check_login_status(playwright_page)
                else:
                    result = {"error": f"Unknown func: {func_name}"}
                
                # 保证 result 永远是 dict（含 error 键）
                if not isinstance(result, dict):
                    result = {"success": True, "data": result}
                
                result_queue.put((task_id, "ok", result))
                logger.info(f"[Worker] 任务 {task_id} 完成")
                
            except Exception as e:
                logger.error(f"[Worker] 执行失败: {e}", exc_info=True)
                result_queue.put((task_id, "error", {"error": str(e)}))

    except Exception as e:
        logger.error(f"[Worker] 初始化失败: {e}", exc_info=True)
        result_queue.put(("__init__", "error", {"error": str(e)}))
    finally:
        if context:
            context.close()
        if pw:
            pw.stop()
        logger.info("[Worker] 浏览器已关闭")


# 结果读取线程：把 result_queue 中的结果分发给等待的 submit_work 调用
pending_events = {}           # task_id → threading.Event
pending_results = {}          # task_id → (status, data)
pending_lock = threading.Lock()

def result_reader():
    """读取 result_queue，分发到对应的等待调用"""
    while True:
        try:
            item = result_queue.get()
            if item is None:
                break
            task_id, status, data = item
            with pending_lock:
                pending_results[task_id] = (status, data)
                evt = pending_events.pop(task_id, None)
            if evt:
                evt.set()
        except queue.Empty:
            continue

def submit_work(task_id, func_name, args):
    """
    同步提交任务到 worker 线程，等待结果返回。
    返回 dict（永远是 dict，含 error 键表示失败）。
    """
    evt = threading.Event()
    with pending_lock:
        pending_events[task_id] = evt
    work_queue.put((task_id, func_name, args))
    evt.wait(timeout=300)
    with pending_lock:
        result = pending_results.pop(task_id, ("error", {"error": "Timeout"}))
    status, data = result
    if status == "error":
        return data  # dict with 'error' key
    return data       # dict (success=True or contains result)


# ===== Flask API =====

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})

@app.route('/api/login/status', methods=['GET'])
def login_status():
    try:
        result = submit_work("__login__", 'check_login', ())
        return jsonify({"success": True, "is_logged_in": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/tasks', methods=['POST'])
def create_task():
    try:
        data = request.get_json()
        task_type = data.get('type')
        params = data.get('params', {})
        if task_type not in ['search', 'scrape', 'user_info']:
            return jsonify({"error": "无效的任务类型"}), 400
        task_id = str(uuid.uuid4())
        task = Task(task_id, task_type, params)
        with task_lock:
            tasks[task_id] = task
        task_queue.put((task_id, task_type, params))
        return jsonify({"success": True, "task_id": task_id, "status": "pending"})
    except Exception as e:
        logger.error(f"创建任务失败: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/api/tasks/<task_id>', methods=['GET'])
def get_task_status(task_id):
    try:
        with task_lock:
            task = tasks.get(task_id)
            if not task:
                return jsonify({"error": "任务不存在"}), 404
            return jsonify({
                "success": True,
                "task_id": task.task_id,
                "type": task.task_type,
                "status": task.status,
                "progress": task.progress,
                "message": task.message,
                "result": task.result,
                "error": task.error,
                "created_at": task.created_at,
                "started_at": task.started_at,
                "completed_at": task.completed_at
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/tasks', methods=['GET'])
def list_tasks():
    try:
        with task_lock:
            task_list = [{
                "task_id": t.task_id, "type": t.task_type,
                "status": t.status, "progress": t.progress,
                "message": t.message, "created_at": t.created_at
            } for t in tasks.values()]
        return jsonify({"success": True, "tasks": task_list, "count": len(task_list)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def queue_processor():
    """处理任务队列（每个任务独立调用 submit_work）"""
    while True:
        try:
            item = task_queue.get()
        except queue.Empty:
            continue
        if item is None:
            break
        
        task_id, task_type, params = item
        
        with task_lock:
            task = tasks.get(task_id)
            if not task:
                continue
        
        task.update("running", 0, "任务开始执行...")
        
        try:
            if task_type == 'search':
                keyword = params.get('keyword')
                result = submit_work(task_id, 'extract_user_links', (keyword,))
                if "error" in result:
                    task.update("failed", 100, result["error"], error=result["error"])
                else:
                    task.update("completed", 100, "搜索完成", result=result)
            
            elif task_type == 'user_info':
                url = params.get('url')
                result = submit_work(task_id, 'extract_user_info', (url,))
                if "error" in result:
                    task.update("failed", 100, result["error"], error=result["error"])
                else:
                    task.update("completed", 100, "获取用户信息完成", result=result)
            
            elif task_type == 'scrape':
                keyword = params.get('keyword')
                search_result = submit_work(task_id, 'extract_user_links', (keyword,))
                
                if "error" in search_result:
                    task.update("failed", 100, search_result["error"], error=search_result["error"])
                    continue
                
                links = search_result.get('links', [])
                results = []
                
                for idx, link in enumerate(links):
                    progress = 50 + int((idx / max(len(links), 1)) * 50)
                    task.update("running", progress, f"正在抓取第 {idx + 1}/{len(links)} 个用户")
                    logger.info(f"正在抓取第 {idx + 1}/{len(links)} 个用户")
                    
                    info_result = submit_work(task_id, 'extract_user_info', (link,))
                    if isinstance(info_result, dict) and info_result.get('success'):
                        results.append(info_result)
                    elif isinstance(info_result, dict) and "error" in info_result:
                        logger.warning(f"抓取失败: {link} - {info_result['error']}")
                    
                    human_delay(2, 4)
                
                task.update("completed", 100, f"抓取完成，共 {len(results)} 条数据", result={
                    "success": True,
                    "count": len(results),
                    "results": results
                })
            
            # 回调
            if task.callback_url:
                try:
                    import requests as _requests
                    _requests.post(task.callback_url, json={
                        "task_id": task_id, "status": task.status,
                        "result": task.result, "error": task.error
                    }, timeout=30)
                except Exception as e:
                    logger.warning(f"回调失败: {e}")
        
        except Exception as e:
            logger.error(f"执行任务失败 {task_id}: {e}", exc_info=True)
            with task_lock:
                t = tasks.get(task_id)
                if t:
                    t.update("failed", 100, str(e), error=str(e))


if __name__ == "__main__":
    logger.info("正在初始化API服务器...")
    
    # 启动工作线程和结果读取线程
    threading.Thread(target=playwright_worker, daemon=True, name="PlaywrightWorker").start()
    threading.Thread(target=result_reader, daemon=True, name="ResultReader").start()
    threading.Thread(target=queue_processor, daemon=True, name="QueueProcessor").start()
    
    logger.info("=" * 70)
    logger.info("API服务器启动成功!")
    logger.info("=" * 70)
    logger.info("HTTP API端点:")
    logger.info("  GET  /api/health              - 健康检查")
    logger.info("  GET  /api/login/status        - 检查登录状态")
    logger.info("  POST /api/tasks               - 创建异步任务")
    logger.info("  GET  /api/tasks/<task_id>     - 查询任务状态（轮询）")
    logger.info("  GET  /api/tasks               - 列出所有任务")
    logger.info("")
    logger.info("任务类型:")
    logger.info('  search   - 搜索用户: {"type":"search","params":{"keyword":"..."}}')
    logger.info('  scrape   - 完整抓取: {"type":"scrape","params":{"keyword":"..."}}')
    logger.info('  user_info- 获取用户信息: {"type":"user_info","params":{"url":"..."}}')
    logger.info("")
    logger.info("可选参数: callback_url - 任务完成时回调URL")
    logger.info("=" * 70)
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
