const SLUG_PATTERN = /^[A-Za-z0-9][A-Za-z0-9-]{2,31}$/;

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store"
    }
  });
}

function validateSlug(slug) {
  if (typeof slug !== "string") throw new Error("Tên link không hợp lệ.");
  const value = slug.trim();
  if (!SLUG_PATTERN.test(value) || value.toLowerCase() === "api") {
    throw new Error("Tên link dùng 3–32 chữ cái, số hoặc dấu gạch ngang.");
  }
  return value;
}

async function readPayload(request) {
  if (Number(request.headers.get("Content-Length") || 0) > 10000) {
    throw new Error("Yêu cầu quá lớn.");
  }
  const payload = await request.json();
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("Yêu cầu không hợp lệ.");
  }
  return payload;
}

function randomSlug() {
  return crypto.randomUUID().replaceAll("-", "").slice(0, 12);
}

async function shorten(request, env) {
  let payload;
  try {
    payload = await readPayload(request);
  } catch (error) {
    return json({ error: error.message || "Yêu cầu không hợp lệ." }, 400);
  }

  if (typeof payload.url !== "string" || payload.url.length > 5000) {
    return json({ error: "Vui lòng nhập một URL hợp lệ." }, 400);
  }

  let target;
  try {
    target = new URL(payload.url.trim());
  } catch {
    return json({ error: "Vui lòng nhập một URL hợp lệ." }, 400);
  }
  if (!["http:", "https:"].includes(target.protocol) || !target.hostname) {
    return json({ error: "Chỉ chấp nhận URL http hoặc https." }, 400);
  }

  let requestedSlug = "";
  try {
    if (payload.slug) requestedSlug = validateSlug(payload.slug);
  } catch (error) {
    return json({ error: error.message }, 400);
  }

  const ownerToken = `${crypto.randomUUID()}${crypto.randomUUID()}`;
  const attempts = requestedSlug ? 1 : 5;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const slug = requestedSlug || randomSlug();
    try {
      await env.DB.prepare(
        "INSERT INTO short_links (slug, target_url, owner_token) VALUES (?, ?, ?)"
      ).bind(slug, target.href, ownerToken).run();
      return json({ shorturl: `${new URL(request.url).origin}/${slug}`, ownerToken });
    } catch {
      if (requestedSlug) return json({ error: "Tên link này đã được sử dụng." }, 409);
    }
  }
  return json({ error: "Không tạo được mã link. Hãy thử lại." }, 503);
}

async function rename(request, env) {
  let payload;
  try {
    payload = await readPayload(request);
  } catch (error) {
    return json({ error: error.message || "Yêu cầu không hợp lệ." }, 400);
  }

  let newSlug;
  try {
    newSlug = validateSlug(payload.newSlug);
  } catch (error) {
    return json({ error: error.message }, 400);
  }

  if (typeof payload.oldSlug !== "string" || !SLUG_PATTERN.test(payload.oldSlug)) {
    return json({ error: "Link cũ không còn tồn tại." }, 404);
  }
  const record = await env.DB.prepare(
    "SELECT target_url, owner_token FROM short_links WHERE slug = ?"
  ).bind(payload.oldSlug).first();
  if (!record) return json({ error: "Link cũ không còn tồn tại." }, 404);
  if (typeof payload.ownerToken !== "string" || payload.ownerToken !== record.owner_token) {
    return json({ error: "Không có quyền chỉnh sửa link này trên trình duyệt hiện tại." }, 403);
  }

  try {
    await env.DB.prepare(
      "UPDATE short_links SET slug = ? WHERE slug = ?"
    ).bind(newSlug, payload.oldSlug).run();
  } catch {
    return json({ error: "Tên link này đã được sử dụng." }, 409);
  }
  return json({ shorturl: `${new URL(request.url).origin}/${newSlug}` });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/api/shorten" && request.method === "POST") {
      return shorten(request, env);
    }
    if (url.pathname === "/api/rename" && request.method === "POST") {
      return rename(request, env);
    }
    if (request.method === "GET" && (url.pathname === "/" || url.pathname === "/index.html" || url.pathname === "/favicon.svg")) {
      return env.ASSETS.fetch(request);
    }

    const match = url.pathname.match(/^\/([A-Za-z0-9][A-Za-z0-9-]{2,31})$/);
    if (request.method === "GET" && match) {
      const record = await env.DB.prepare(
        "SELECT target_url FROM short_links WHERE slug = ?"
      ).bind(match[1]).first();
      if (!record) return new Response("Not found", { status: 404 });
      return new Response(null, {
        status: 302,
        headers: { Location: record.target_url, "Cache-Control": "no-store" }
      });
    }

    return new Response("Not found", { status: 404 });
  }
};
