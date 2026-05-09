import json
import os
import re
import ssl
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


def app(environ, start_response):
    path = environ.get("PATH_INFO")
    if path == "/api/run-report":
        return _handle_run_report(environ, start_response)
    if path == "/api/feishu/events":
        return _handle_feishu_events(environ, start_response)

    start_response(
        "302 Found",
        [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Location", "/index.html"),
            ("Cache-Control", "public, max-age=0, must-revalidate"),
        ],
    )
    return [b"Redirecting to TrendRadar report.\n"]


def _handle_run_report(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET").upper()

    if method == "OPTIONS":
        return _json_response(start_response, "204 No Content", {})

    if method == "GET":
        return _json_response(
            start_response,
            "200 OK",
            {
                "ok": True,
                "message": "Use POST to trigger a TrendRadar report run.",
            },
        )

    if method != "POST":
        return _json_response(
            start_response,
            "405 Method Not Allowed",
            {
                "ok": False,
                "error": "Only POST is supported.",
            },
        )

    token = os.environ.get("GITHUB_DISPATCH_TOKEN")
    if not token:
        return _json_response(
            start_response,
            "500 Internal Server Error",
            {
                "ok": False,
                "error": "Vercel 环境变量 GITHUB_DISPATCH_TOKEN 尚未配置。",
            },
        )

    body = _read_json_body(environ)
    force_push = bool(body.get("force_push", True))
    repository = os.environ.get("TRENDRADAR_GITHUB_REPOSITORY", "1518338634-byte/trendradar")
    workflow = os.environ.get("TRENDRADAR_WORKFLOW_FILE", "update-vercel-report.yml")
    ref = os.environ.get("TRENDRADAR_GITHUB_REF", "master")

    payload = json.dumps(
        {
            "ref": ref,
            "inputs": {
                "force_push": "true" if force_push else "false",
            },
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/actions/workflows/{workflow}/dispatches",
        data=payload,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "TrendRadar-Vercel-Trigger",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return _json_response(
                start_response,
                "202 Accepted",
                {
                    "ok": True,
                    "message": "TrendRadar report workflow dispatched.",
                    "github_status": response.status,
                },
            )
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        return _json_response(
            start_response,
            f"{error.code} GitHub Error",
            {
                "ok": False,
                "error": "GitHub Actions 触发失败。",
                "detail": detail,
            },
        )
    except Exception as error:
        return _json_response(
            start_response,
            "500 Internal Server Error",
            {
                "ok": False,
                "error": f"触发请求失败：{error}",
            },
        )


def _handle_feishu_events(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET").upper()

    if method == "OPTIONS":
        return _json_response(start_response, "204 No Content", {})

    if method == "GET":
        return _json_response(
            start_response,
            "200 OK",
            {
                "ok": True,
                "message": "TrendRadar Feishu event endpoint is ready.",
            },
        )

    if method != "POST":
        return _json_response(
            start_response,
            "405 Method Not Allowed",
            {
                "ok": False,
                "error": "Only POST is supported.",
            },
        )

    data = _read_json_body(environ)

    if data.get("type") == "url_verification" and data.get("challenge"):
        if not _verify_feishu_token(data.get("token")):
            return _json_response(
                start_response,
                "403 Forbidden",
                {
                    "ok": False,
                    "error": "Invalid Feishu verification token.",
                },
            )
        return _json_response(start_response, "200 OK", {"challenge": data["challenge"]})

    header = data.get("header") or {}
    if header.get("token") and not _verify_feishu_token(header.get("token")):
        return _json_response(
            start_response,
            "403 Forbidden",
            {
                "ok": False,
                "error": "Invalid Feishu event token.",
            },
        )

    event_type = header.get("event_type") or data.get("event", {}).get("type")
    if event_type != "im.message.receive_v1":
        return _json_response(
            start_response,
            "200 OK",
            {
                "ok": True,
                "message": "Event ignored.",
            },
        )

    event = data.get("event") or {}
    message = event.get("message") or {}
    message_id = message.get("message_id")
    text = _extract_feishu_text(message)

    if not text:
        reply = "我收到了消息，但暂时只能处理文本指令。你可以发送网页链接，或说“总结最近热点”。"
    else:
        reply = _build_agent_reply(text)

    sent = False
    if message_id:
        sent = _reply_feishu_message(message_id, reply)

    return _json_response(
        start_response,
        "200 OK",
        {
            "ok": True,
            "replied": sent,
        },
    )


def _verify_feishu_token(token):
    expected = os.environ.get("FEISHU_VERIFICATION_TOKEN") or os.environ.get("FEISHU_VERIFY_TOKEN")
    return not expected or token == expected


def _extract_feishu_text(message):
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


def _build_agent_reply(user_text):
    try:
        context = _collect_summary_context(user_text)
        prompt = _build_summary_prompt(user_text, context)
        ai_reply = _call_chat_model(prompt)
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


def _collect_summary_context(user_text):
    urls = re.findall(r"https?://[^\s<>()\"']+", user_text)
    if urls:
        url = urls[0].rstrip("。；，,.")
        page_text = _fetch_url_text(url)
        return f"来源：{url}\n\n{page_text[:18000]}"

    report_text = _load_public_report_text()
    if report_text:
        return f"来源：TrendRadar 最新线上报告\n\n{report_text[:18000]}"

    return ""


def _fetch_url_text(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 TrendRadarFeishuAgent/1.0",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
        },
    )
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=20, context=context) as response:
        content_type = response.headers.get("Content-Type", "")
        raw = response.read(2_000_000)

    text = raw.decode("utf-8", errors="replace")
    if "html" in content_type.lower() or "<html" in text[:500].lower():
        return _html_to_text(text)
    return _normalize_text(text)


def _load_public_report_text():
    for path in (Path("public/report.html"), Path("public/index.html")):
        if path.exists():
            return _html_to_text(path.read_text(encoding="utf-8", errors="replace"))
    return ""


class _TextExtractor(HTMLParser):
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


def _html_to_text(html):
    parser = _TextExtractor()
    parser.feed(html)
    return _normalize_text(" ".join(parser.parts))


def _normalize_text(text):
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _build_summary_prompt(user_text, context):
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


def _call_chat_model(prompt):
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("AI_API_KEY")
    if not api_key:
        return ""

    base_url = (os.environ.get("DEEPSEEK_BASE_URL") or os.environ.get("AI_API_BASE") or "https://api.deepseek.com").rstrip("/")
    model = os.environ.get("DEEPSEEK_MODEL") or os.environ.get("AI_MODEL") or "deepseek-chat"
    url = f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你擅长从长文本中按指定主题精确定位并结构化总结，回复要清晰、简洁、可执行。",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": 0.2,
        "max_tokens": 1800,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    with urllib.request.urlopen(request, timeout=45) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()


def _get_feishu_tenant_token():
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        return ""

    payload = json.dumps(
        {
            "app_id": app_id,
            "app_secret": app_secret,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
        },
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))

    if data.get("code") != 0:
        raise RuntimeError(data.get("msg") or "获取 tenant_access_token 失败")
    return data.get("tenant_access_token", "")


def _reply_feishu_message(message_id, text):
    try:
        token = _get_feishu_tenant_token()
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

        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data.get("code") == 0
    except Exception as error:
        print(f"[feishu] reply failed: {error}")
        return False


def _read_json_body(environ):
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError:
        length = 0

    if length <= 0:
        return {}

    raw = environ["wsgi.input"].read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


def _json_response(start_response, status, payload):
    body = b"" if status.startswith("204") else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Cache-Control", "no-store"),
        ("Access-Control-Allow-Origin", "*"),
        ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
        ("Access-Control-Allow-Headers", "Content-Type"),
        ("Content-Length", str(len(body))),
    ]
    start_response(status, headers)
    return [body]
