def app(environ, start_response):
    start_response(
        "200 OK",
        [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Cache-Control", "no-store"),
        ],
    )
    return [b"TrendRadar static report is served from public/index.html.\n"]
