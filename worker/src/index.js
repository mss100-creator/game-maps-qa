// Website quản lý kiểm thử game maps: đăng nhập, cài đặt, kết quả, chạy ngay, lịch tự động.
import APP_HTML from "./app.html";
import LOGIN_HTML from "./login.html";

const DEFAULT_CONFIG = {
  enabled: false,
  urls: [],
  wait_seconds: 4,
  colors: [{ color: "#2E86DE", tolerance: 12, min_area: 30, max: 50 }],
  runs_per_batch: 20,
  run_hours: [8],
};

const json = (d, s = 200) =>
  new Response(JSON.stringify(d), { status: s, headers: { "content-type": "application/json; charset=utf-8" } });
const html = (h) => new Response(h, { headers: { "content-type": "text/html; charset=utf-8" } });

async function hmac(key, msg) {
  const k = await crypto.subtle.importKey("raw", new TextEncoder().encode(key),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", k, new TextEncoder().encode(msg));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
const cookieOf = (req, name) =>
  (req.headers.get("cookie") || "").split(/;\s*/).find((c) => c.startsWith(name + "="))?.slice(name.length + 1);

async function isAdmin(req, env) {
  const c = cookieOf(req, "qa_auth");
  return !!c && c === (await hmac(env.ADMIN_PASS, "admin-v1"));
}
const isRunner = (req, env) => (req.headers.get("authorization") || "") === `Bearer ${env.RUNNER_TOKEN}`;

async function getSetting(env, key, fallback) {
  const row = await env.DB.prepare("SELECT value FROM settings WHERE key = ?").bind(key).first();
  const v = row ? JSON.parse(row.value) : fallback;
  if (key === "config" && v && !Array.isArray(v.urls)) v.urls = v.url ? [v.url] : [];  // cấu hình cũ 1 link
  return v;
}
const putSetting = (env, key, value) =>
  env.DB.prepare("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value")
    .bind(key, JSON.stringify(value)).run();

function cleanConfig(c) {
  const n = (v, lo, hi, d) => (Number.isFinite(+v) ? Math.min(hi, Math.max(lo, Math.round(+v))) : d);
  return {
    enabled: !!c.enabled,
    urls: [...new Set((Array.isArray(c.urls) ? c.urls : String(c.url || "").split(/\s+/))
      .map((u) => String(u).trim()).filter((u) => /^https?:\/\/\S+$/.test(u)).map((u) => u.slice(0, 500)))].slice(0, 20),
    wait_seconds: n(c.wait_seconds, 1, 60, 4),
    colors: (Array.isArray(c.colors) ? c.colors : []).slice(0, 12)
      .filter((x) => /^#[0-9a-fA-F]{6}$/.test(x.color || ""))
      .map((x) => ({ color: x.color.toUpperCase(), tolerance: n(x.tolerance, 0, 80, 12),
        min_area: n(x.min_area, 1, 5000, 30), max: n(x.max, 1, 200, 50) })),
    runs_per_batch: n(c.runs_per_batch, 1, 20, 20),
    run_hours: [...new Set((Array.isArray(c.run_hours) ? c.run_hours : []).map((h) => n(h, 0, 23, 8)))].sort((a, b) => a - b),
  };
}

async function dispatch(env, origin, count, selftest = false) {
  const r = await fetch(
    `https://api.github.com/repos/${env.GH_REPO}/actions/workflows/qa.yml/dispatches`,
    {
      method: "POST",
      headers: { authorization: `Bearer ${env.GH_TOKEN}`, accept: "application/vnd.github+json",
        "user-agent": "game-maps-qa" },
      body: JSON.stringify({ ref: "main",
        inputs: { count: String(count), api: origin, selftest: selftest ? "true" : "false" } }),
    }
  );
  if (r.status !== 204) throw new Error(`GitHub trả ${r.status}: ${(await r.text()).slice(0, 200)}`);
}

async function saveResults(req, env) {
  const body = await req.json();
  const cf = req.cf || {}, w = body.where || {};
  const clicks = Array.isArray(body.clicks) ? body.clicks.slice(0, 2000) : [];
  const ok = clicks.filter((c) => c.ok).length;
  await env.DB.batch([
    env.DB.prepare(`INSERT OR REPLACE INTO runs (id, ip, country, region, city, asn, profile, kind, total, ok, seconds)
      VALUES (?,?,?,?,?,?,?,?,?,?,?)`).bind(
      String(body.run_id), w.ip || req.headers.get("cf-connecting-ip"), w.country || cf.country || null,
      w.region || cf.region || null, w.city || cf.city || null, w.org || cf.asOrganization || null,
      body.profile || null, body.selftest ? "selftest" : "real", clicks.length, ok, body.seconds || null),
    ...clicks.map((c) => env.DB.prepare(
      `INSERT INTO clicks (run_id, site, color, x, y, ok, url, status, reason) VALUES (?,?,?,?,?,?,?,?,?)`
    ).bind(String(body.run_id), c.site || null, c.color || null, c.x ?? null, c.y ?? null,
      c.ok ? 1 : 0, c.url || null, c.status ?? null, c.reason || null)),
  ]);
  return json({ saved: clicks.length });
}

async function listData(env, day) {
  const runs = (await env.DB.prepare(
    `SELECT * FROM runs WHERE date(created_at, '+7 hours') = ? ORDER BY created_at DESC LIMIT 500`
  ).bind(day).all()).results;
  const fails = (await env.DB.prepare(
    `SELECT c.site, c.color, c.x, c.y, c.reason, MAX(c.url) AS url, COUNT(*) AS times,
            GROUP_CONCAT(DISTINCT COALESCE(r.city, '') || ', ' || COALESCE(r.region, '')) AS places,
            MAX(r.kind) AS kind
     FROM clicks c JOIN runs r ON r.id = c.run_id
     WHERE c.ok = 0 AND date(r.created_at, '+7 hours') = ?
     GROUP BY c.site, c.color, c.x, c.y, c.reason ORDER BY times DESC LIMIT 300`
  ).bind(day).all()).results;
  return { day, runs, fails };
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const p = url.pathname;

    if (p === "/api/results" && req.method === "POST")
      return isRunner(req, env) ? saveResults(req, env) : json({ error: "sai token" }, 401);
    if (p === "/api/config" && req.method === "GET" && isRunner(req, env))
      return json(await getSetting(env, "config", DEFAULT_CONFIG));

    if (p === "/login" && req.method === "POST") {
      const form = await req.formData();
      if (String(form.get("password") || "") !== env.ADMIN_PASS)
        return html(LOGIN_HTML.replace("<!--ERR-->", '<p class="err">Sai mật khẩu, thử lại.</p>'));
      const tok = await hmac(env.ADMIN_PASS, "admin-v1");
      return new Response(null, { status: 303, headers: { location: "/",
        "set-cookie": `qa_auth=${tok}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000` } });
    }
    if (p === "/logout")
      return new Response(null, { status: 303, headers: { location: "/",
        "set-cookie": "qa_auth=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0" } });

    if (!(await isAdmin(req, env)))
      return p.startsWith("/api/") ? json({ error: "chưa đăng nhập" }, 401) : html(LOGIN_HTML);

    // Ghi nhớ địa chỉ website để lịch tự động gửi cho GitHub
    if (p === "/") { await putSetting(env, "origin", url.origin); return html(APP_HTML); }
    if (p === "/api/config" && req.method === "GET")
      return json(await getSetting(env, "config", DEFAULT_CONFIG));
    if (p === "/api/config" && req.method === "PUT") {
      const cfg = cleanConfig(await req.json());
      await putSetting(env, "config", cfg);
      return json(cfg);
    }
    if (p === "/api/run" && req.method === "POST") {
      const b = await req.json().catch(() => ({}));
      const cfg = await getSetting(env, "config", DEFAULT_CONFIG);
      if (!b.selftest && !cfg.urls.length) return json({ error: "Chưa nhập địa chỉ trang game trong Cài đặt" }, 400);
      try {
        await dispatch(env, url.origin, Math.min(20, Math.max(1, +b.count || cfg.runs_per_batch)), !!b.selftest);
        return json({ ok: true });
      } catch (e) { return json({ error: e.message }, 502); }
    }
    if (p === "/api/data") {
      const day = url.searchParams.get("day") || new Date(Date.now() + 7 * 3600e3).toISOString().slice(0, 10);
      return json(await listData(env, day));
    }
    return json({ error: "không có" }, 404);
  },

  async scheduled(event, env, ctx) {
    const cfg = await getSetting(env, "config", DEFAULT_CONFIG);
    const origin = await getSetting(env, "origin", null);
    const vnHour = (new Date(event.scheduledTime).getUTCHours() + 7) % 24;
    if (!cfg.enabled || !cfg.urls.length || !origin || !cfg.run_hours.includes(vnHour)) return;
    ctx.waitUntil(dispatch(env, origin, cfg.runs_per_batch));
  },
};
