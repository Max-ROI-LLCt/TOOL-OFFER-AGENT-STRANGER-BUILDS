import { DurableObject } from "cloudflare:workers";

const AGENT_ADDRESS = "agent1qg0p9zy9rxqz83l5p8tr7vevguk3hny963luv4pd8nu8hp87qc0syk3c88a";

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]));
  }
  return value;
}

function json(data, status = 200) {
  return Response.json(data, { status, headers: { "Cache-Control": "no-store" } });
}

function authorized(header, token) {
  if (typeof token !== "string" || !token || !header?.startsWith("Bearer ")) return false;
  const actual = new TextEncoder().encode(header.slice(7));
  const expected = new TextEncoder().encode(token);
  let difference = actual.length ^ expected.length;
  for (let index = 0; index < Math.max(actual.length, expected.length); index++) {
    difference |= (actual[index] ?? 0) ^ (expected[index] ?? 0);
  }
  return difference === 0;
}

export class CommercialCustody extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    this.storage = ctx.storage;
    this.sql.exec("CREATE TABLE IF NOT EXISTS commercial_records (id TEXT PRIMARY KEY, state TEXT NOT NULL)");
  }

  load(key) {
    const row = this.sql.exec("SELECT state FROM commercial_records WHERE id = ?", key).toArray()[0];
    return row ? JSON.parse(row.state) : null;
  }

  compareAndSwap(key, before, after) {
    return this.storage.transactionSync(() => {
      const existing = this.sql.exec("SELECT state FROM commercial_records WHERE id = ?", key).toArray()[0];
      if ((existing ? existing.state : null) !== (before === null ? null : JSON.stringify(canonical(before)))) return false;
      if (existing) this.sql.exec("UPDATE commercial_records SET state = ? WHERE id = ?", JSON.stringify(canonical(after)), key);
      else this.sql.exec("INSERT INTO commercial_records (id, state) VALUES (?, ?)", key, JSON.stringify(canonical(after)));
      return true;
    });
  }
}

export default {
  async fetch(request, env) {
    if (new URL(request.url).pathname !== "/v1/state" || request.method !== "POST") return json({ error: "not_found" }, 404);
    if (!authorized(request.headers.get("Authorization"), env.TOOL_OFFER_CUSTODY_TOKEN)) return json({ error: "unauthorized" }, 401);
    if (Number(request.headers.get("Content-Length")) > 262144) return json({ error: "too_large" }, 413);
    let body;
    try {
      const text = await request.text();
      if (new TextEncoder().encode(text).length > 262144) return json({ error: "too_large" }, 413);
      body = JSON.parse(text);
    } catch {
      return json({ error: "invalid_json" }, 400);
    }
    if (!body || !/^[0-9a-f]{64}$/.test(body.key ?? "")) return json({ error: "invalid_key" }, 400);
    const custody = env.COMMERCIAL_CUSTODY.getByName(AGENT_ADDRESS);
    if (body.operation === "load") return json({ state: await custody.load(body.key) });
    if (body.operation === "compare_and_swap" && (body.before === null || typeof body.before === "object")
        && body.after !== null && typeof body.after === "object" && !Array.isArray(body.after)
        && (body.before === null || !Array.isArray(body.before))) {
      return json({ swapped: await custody.compareAndSwap(body.key, body.before, body.after) });
    }
    return json({ error: "invalid_operation" }, 400);
  },
};
