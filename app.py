import json
import os
import urllib.error
import urllib.request


def app(environ, start_response):
    if environ.get("PATH_INFO") == "/api/run-report":
        return _handle_run_report(environ, start_response)

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
