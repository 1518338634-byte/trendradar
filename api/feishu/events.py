import json
import os
import re
import ssl
import urllib.request
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler
from pathlib import Path


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self._send_json(204, {})

    def do_GET(self):
        self._send_json(
            200,
            {
                "ok": True,
                "message": "TrendRadar Feishu event endpoint is ready.",
            },
        )

    def do_POST(self):
        data = self._read_json_body()

        if data.get("type") == "url_verification" and data.get("challenge"):
            if not verify_feishu_token(data.get("token")):
                self._send_json(403, {"ok": False, "error": "Invalid verification token."})
                return
            self._send_json(200, {"challenge": data["challenge"]})
            return

        header = data.get("header") or {}
        if header.get("token") and not verify_feishu_token(header.get("token")):
            self._send_json(403, {"ok": False, "error": "Invalid event token."})
            return

        event_type = header.get("event_type") or data.get("event", {}).get("type")
        if event_type != "im.message.receive_v1":
            self._send_json(200, {"ok": True, "message": "Event ignored."})
            return

        event = data.get("event") or {}
        message = event.get("message") or {}
        message_id = message.get("message_id")
        text = extract_feishu_text(message)

        if not text:
            reply = "我收到了消息，但暂时只能处理文本指令。你可以发送网页链接，或说“总结最近热点”。"
        else:
            reply = build_agent_reply(text)

        sent = reply_feishu_message(message_id, reply) if message_id else False
        self._send_json(200, {"ok": True, "replied": sent})

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _send_json(self, status, payload):
        body = b"" if status == 204 else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)


def verify_feishu_token(token):
    expected = os.environ.get("FEISHU_VERIFICATION_TOKEN") or os.environ.get("FEISHU_VERIFY_TOKEN")
    return not expected or token == expected


def extract_feishu_text(message):
    content = message.get("content")
    if not content:
        return ""

    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return content.strip()

    if not isinstance(content, dict):
        return ""

    text = content.get("text") or ""
    text = re.sub(r"<at\b[^>]*>.*?</at>", "", text)
    return text.strip()


def build_agent_reply(user_text):
    try:
        context = collect_summary_context(user_text)
        prompt = build_summary_prompt(user_text, context)
        ai_reply = call_chat_model(prompt)
        if ai_reply:
            return ai_reply
    except Exception as error:
        return (
            "我收到你的指令了，但处理内容时遇到问题。\n\n"
            f"错误信息：{error}\n\n"
            "你可以重新发送一个网页链接，或者明确说明要总结的关键词、时间范围。"
        )

    return (
        "我收到你的指令了。\n\n"
        "目前我可以先处理：\n"
        "1. 总结网页链接中的指定内容；\n"
        "2. 总结当前 TrendRadar 线上报告；\n"
        "3. 根据关键词提取相关热点。\n\n"
        "你可以这样发：\n"
        "帮我总结这篇文章中关于用户增长策略的部分：https://example.com"
    )


def collect_summary_context(user_text):
    urls = re.findall(r"https?://[^\s<>()\"']+", user_text)
    if urls:
        url = urls[0].rstrip("。；，,.")
        page_text = fetch_url_text(url)
        return f"来源：{url}\n\n{page_text[:18000]}"

    report_text = load_public_report_text()
    if report_text:
        return f"来源：TrendRadar 最新线上报告\n\n{report_text[:18000]}"

    return ""


def fetch_url_text(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 TrendRadarFeishuAgent/1.0",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
        },
    )
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=15, context=context) as response:
        content_type = response.headers.get("Content-Type", "")
        raw = response.read(2_000_000)

    text = raw.decode("utf-8", errors="replace")
    if "html" in content_type.lower() or "<html" in text[:500].lower():
        return html_to_text(text)
    return normalize_text(text)


def load_public_report_text():
    for path in (Path("public/report.html"), Path("public/index.html")):
        if path.exists():
            return html_to_text(path.read_text(encoding="utf-8", errors="replace"))
    return ""


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip_depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg", "canvas"}:
            self.skip_depth += 1
        if tag in {"p", "br", "li", "h1", "h2", "h3", "h4", "section", "article", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg", "canvas"} and self.skip_depth:
            self.skip_depth -= 1
        if tag in {"p", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip_depth:
            text = data.strip()
            if text:
                self.parts.append(text)


def html_to_text(html):
    parser = TextExtractor()
    parser.feed(html)
    return normalize_text(" ".join(parser.parts))


def normalize_text(text):
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def build_summary_prompt(user_text, context):
    return (
        "你是飞书里的 TrendRadar 内容总结 Agent。请严格根据用户指定范围总结，"
        "不要泛泛总结全文。如果指令不明确，要先提出待确认问题。\n\n"
        "默认输出结构：\n"
        "一句话概括\n"
        "核心要点\n"
        "关键数据或事实\n"
        "重要结论\n"
        "后续建议或待确认问题\n\n"
        f"用户指令：{user_text}\n\n"
        f"可用内容：\n{context or '暂无可用内容。'}"
    )


def call_chat_model(prompt):
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("AI_API_KEY")
    if not api_key:
        return ""

    base_url = (os.environ.get("DEEPSEEK_BASE_URL") or os.environ.get("AI_API_BASE") or "https://api.deepseek.com").rstrip("/")
    model = os.environ.get("DEEPSEEK_MODEL") or os.environ.get("AI_MODEL") or "deepseek-chat"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你擅长从长文本中按指定主题精确定位并结构化总结，回复要清晰、简洁、可执行。",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 1800,
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    with urllib.request.urlopen(request, timeout=25) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()


def get_feishu_tenant_token():
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        return ""

    payload = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode("utf-8")
    request = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(request, timeout=15) as response:
        data = json.loads(response.read().decode("utf-8"))

    if data.get("code") != 0:
        raise RuntimeError(data.get("msg") or "获取 tenant_access_token 失败")
    return data.get("tenant_access_token", "")


def reply_feishu_message(message_id, text):
    if not message_id:
        return False

    try:
        token = get_feishu_tenant_token()
        if not token:
            return False

        payload = json.dumps(
            {
                "msg_type": "text",
                "content": json.dumps({"text": text[:12000]}, ensure_ascii=False),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )

        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data.get("code") == 0
    except Exception as error:
        print(f"[feishu] reply failed: {error}")
        return False
