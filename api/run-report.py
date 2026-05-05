import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self._send_json(204, {})

    def do_GET(self):
        self._send_json(
            200,
            {
                "ok": True,
                "message": "Use POST to trigger a TrendRadar report run.",
            },
        )

    def do_POST(self):
        token = os.environ.get("GITHUB_DISPATCH_TOKEN")
        if not token:
            self._send_json(
                500,
                {
                    "ok": False,
                    "error": "Vercel 环境变量 GITHUB_DISPATCH_TOKEN 尚未配置。",
                },
            )
            return

        body = self._read_json_body()
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
                self._send_json(
                    202,
                    {
                        "ok": True,
                        "message": "TrendRadar report workflow dispatched.",
                        "github_status": response.status,
                    },
                )
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            self._send_json(
                error.code,
                {
                    "ok": False,
                    "error": "GitHub Actions 触发失败。",
                    "detail": detail,
                },
            )
        except Exception as error:
            self._send_json(
                500,
                {
                    "ok": False,
                    "error": f"触发请求失败：{error}",
                },
            )

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
