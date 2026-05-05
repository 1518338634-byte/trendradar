from pathlib import Path


def app(environ, start_response):
    report_path = Path(__file__).parent / "public" / "index.html"

    if report_path.exists():
        body = report_path.read_bytes()
        start_response(
            "200 OK",
            [
                ("Content-Type", "text/html; charset=utf-8"),
                ("Cache-Control", "public, max-age=0, must-revalidate"),
            ],
        )
        return [body]

    start_response(
        "404 Not Found",
        [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Cache-Control", "no-store"),
        ],
    )
    return [b"TrendRadar report has not been generated yet.\n"]
