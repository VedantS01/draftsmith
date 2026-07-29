/* draftsmith demo proxy — Cloudflare Worker (free plan).
 *
 * Keeps the project's LLM API key server-side so the static GitHub
 * Pages demo can offer live chat without visitors bringing a key.
 * The page POSTs {messages} here; the Worker forwards them to an
 * OpenAI-compatible endpoint with the secret key and a server-pinned
 * model, and streams the JSON back with CORS headers.
 *
 * Abuse posture for an MVP: origin allowlist, model pinned server-side
 * (visitors can't pick an expensive one), only `messages` forwarded
 * (no max_tokens or other params pass through), request size capped.
 * The free-tier provider's own rate limits are the spend ceiling —
 * the key has no billing attached. Optionally add one WAF
 * rate-limiting rule (included in Cloudflare's free plan) in front.
 *
 * Deploy:  npx wrangler deploy
 * Secret:  npx wrangler secret put API_KEY
 * Config:  wrangler.toml (API_BASE, MODEL, ALLOWED_ORIGINS)
 */

const MAX_BODY_BYTES = 80_000; // system prompt + plan + history fits well under this

const cors = (origin) => ({
  "Access-Control-Allow-Origin": origin,
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
});

const jsonError = (message, status, headers = {}) =>
  new Response(JSON.stringify({ error: { message } }), {
    status,
    headers: { ...headers, "Content-Type": "application/json" },
  });

export default {
  async fetch(request, env) {
    const allowed = (env.ALLOWED_ORIGINS || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const origin = request.headers.get("Origin") || "";
    const originOk = allowed.length === 0 || allowed.includes(origin);
    const corsHeaders = originOk ? cors(origin) : {};

    if (request.method === "OPTIONS")
      return new Response(null, { status: originOk ? 204 : 403, headers: corsHeaders });
    if (!originOk) return jsonError("origin not allowed", 403);
    if (request.method !== "POST") return jsonError("POST only", 405, corsHeaders);

    const raw = await request.text();
    if (raw.length > MAX_BODY_BYTES)
      return jsonError("request too large", 413, corsHeaders);
    let messages;
    try {
      messages = JSON.parse(raw).messages;
    } catch {
      return jsonError("invalid JSON", 400, corsHeaders);
    }
    if (!Array.isArray(messages) || !messages.length)
      return jsonError("messages[] required", 400, corsHeaders);

    const upstream = await fetch(`${env.API_BASE}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${env.API_KEY}`,
      },
      body: JSON.stringify({ model: env.MODEL, messages }),
    });
    const headers = new Headers(corsHeaders);
    headers.set(
      "Content-Type",
      upstream.headers.get("Content-Type") || "application/json"
    );
    return new Response(upstream.body, { status: upstream.status, headers });
  },
};
