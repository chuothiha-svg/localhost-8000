import json
import os
import re
import secrets
import sqlite3
import string
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
PUBLIC_ROOT = ROOT / "public"
DATABASE = ROOT / "links.sqlite3"
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
SLUG_ALPHABET = string.ascii_letters + string.digits
SLUG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{2,31}$")


class AliasConflictError(Exception):
    pass


def initialize_database():
    with sqlite3.connect(DATABASE) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS short_links "
            "(slug TEXT PRIMARY KEY, target_url TEXT NOT NULL, owner_token TEXT)"
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(short_links)")}
        if "owner_token" not in columns:
            connection.execute("ALTER TABLE short_links ADD COLUMN owner_token TEXT")


def validate_slug(slug):
    if not isinstance(slug, str):
        raise ValueError("Tên link không hợp lệ.")
    slug = slug.strip()
    if not SLUG_PATTERN.fullmatch(slug) or slug.lower() == "api":
        raise ValueError("Tên link dùng 3–32 chữ cái, số hoặc dấu gạch ngang.")
    return slug


def create_short_link(target_url, requested_slug=""):
    owner_token = secrets.token_urlsafe(32)
    with sqlite3.connect(DATABASE) as connection:
        if requested_slug:
            slug = validate_slug(requested_slug)
            try:
                connection.execute(
                    "INSERT INTO short_links (slug, target_url, owner_token) VALUES (?, ?, ?)",
                    (slug, target_url, owner_token),
                )
            except sqlite3.IntegrityError:
                raise AliasConflictError("Tên link này đã được sử dụng.") from None
        else:
            while True:
                slug = "".join(secrets.choice(SLUG_ALPHABET) for _ in range(12))
                try:
                    connection.execute(
                        "INSERT INTO short_links (slug, target_url, owner_token) VALUES (?, ?, ?)",
                        (slug, target_url, owner_token),
                    )
                    break
                except sqlite3.IntegrityError:
                    continue
    return f"{PUBLIC_BASE_URL}/{slug}", owner_token


def find_target(slug):
    with sqlite3.connect(DATABASE) as connection:
        row = connection.execute(
            "SELECT target_url FROM short_links WHERE slug = ?", (slug,)
        ).fetchone()
    return row[0] if row else None


def rename_short_link(old_slug, new_slug, owner_token):
    new_slug = validate_slug(new_slug)
    if not isinstance(old_slug, str) or not SLUG_PATTERN.fullmatch(old_slug):
        return "missing"
    if not isinstance(owner_token, str):
        return "forbidden"

    with sqlite3.connect(DATABASE) as connection:
        row = connection.execute(
            "SELECT owner_token FROM short_links WHERE slug = ?", (old_slug,)
        ).fetchone()
        if not row:
            return "missing"
        if not row[0] or not secrets.compare_digest(row[0], owner_token):
            return "forbidden"
        try:
            connection.execute(
                "UPDATE short_links SET slug = ? WHERE slug = ?",
                (new_slug, old_slug),
            )
        except sqlite3.IntegrityError:
            return "exists"
    return "renamed"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_ROOT), **kwargs)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ("/", "/index.html", "/favicon.svg"):
            return super().do_GET()
        match = re.fullmatch(r"/([A-Za-z0-9][A-Za-z0-9-]{2,31})", path)
        if match:
            target_url = find_target(match.group(1))
            if not target_url:
                return self.send_error(404)
            self.send_response(302)
            self.send_header("Location", target_url)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_error(404)

    def do_POST(self):
        request_path = urlsplit(self.path).path
        if request_path not in ("/api/shorten", "/api/rename"):
            return self.send_error(404)

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if not 0 < content_length <= 10000:
                raise ValueError
            payload = json.loads(self.rfile.read(content_length))
            if not isinstance(payload, dict):
                raise ValueError
        except (ValueError, json.JSONDecodeError):
            return self.send_json({"error": "Yêu cầu không hợp lệ."}, 400)

        if request_path == "/api/rename":
            try:
                new_slug = validate_slug(payload.get("newSlug"))
                result = rename_short_link(
                    payload.get("oldSlug"),
                    new_slug,
                    payload.get("ownerToken"),
                )
            except ValueError as error:
                return self.send_json({"error": str(error)}, 400)
            if result == "missing":
                return self.send_json({"error": "Link cũ không còn tồn tại."}, 404)
            if result == "forbidden":
                return self.send_json({"error": "Không có quyền chỉnh sửa link này trên trình duyệt hiện tại."}, 403)
            if result == "exists":
                return self.send_json({"error": "Tên link này đã được sử dụng."}, 409)
            return self.send_json({"shorturl": f"{PUBLIC_BASE_URL}/{new_slug}"})

        try:
            target_url = payload.get("url", "").strip()
            parsed = urlsplit(target_url)
            if (
                len(target_url) > 5000
                or parsed.scheme not in ("http", "https")
                or not parsed.hostname
            ):
                raise ValueError
            requested_slug = payload.get("slug", "")
        except (ValueError, AttributeError):
            return self.send_json({"error": "Vui lòng nhập một URL http hoặc https hợp lệ."}, 400)
        try:
            short_url, owner_token = create_short_link(target_url, requested_slug)
        except AliasConflictError as error:
            return self.send_json({"error": str(error)}, 409)
        except ValueError as error:
            return self.send_json({"error": str(error)}, 400)
        self.send_json({"shorturl": short_url, "ownerToken": owner_token})

    def send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    initialize_database()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Gon Link is running at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()
