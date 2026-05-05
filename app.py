def app(environ, start_response):
    start_response(
        "302 Found",
        [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Location", "/index.html"),
            ("Cache-Control", "public, max-age=0, must-revalidate"),
        ],
    )
    return [b"Redirecting to TrendRadar report.\n"]
