"""Reject every model request for the real-Codex integration control."""

from http.server import BaseHTTPRequestHandler, HTTPServer


class EmptyProvider(BaseHTTPRequestHandler):
    """Return a definite model error without contacting an external service."""

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        """Reject model requests with a response Codex cannot retry."""
        body = (
            b'{"error":{"message":"empty test provider",'
            b'"type":"invalid_request_error"}}'
        )
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # The base method permits callers to pass format by keyword.
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Keep the container's service log free of request details."""


def main() -> None:
    """Serve only the container loopback interface."""
    with HTTPServer(("127.0.0.1", 8765), EmptyProvider) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
