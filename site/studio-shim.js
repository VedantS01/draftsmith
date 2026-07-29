/* draftsmith studio — static-host shim.
 *
 * Loaded in <head> of the published studio page, before the app script.
 * Replaces the Python http.server backend with an in-browser one:
 *
 *   - engine routes (/api/state, /api/op, /api/undo, /api/redo, /api/fp)
 *     run the real draftsmith package inside Pyodide (studio_backend.py);
 *   - exports render in-browser and download as Blobs;
 *   - chat calls OpenRouter directly from the browser with a
 *     visitor-supplied key (stored in localStorage only), or falls back
 *     to a canned exchange in demo mode so key-less visitors still see
 *     the loop work.
 *
 * The app's own fetch("/api/...") calls are intercepted, so the studio
 * frontend ships unmodified.
 */
(() => {
  "use strict";

  const PYODIDE_VERSION = window.DRAFTSMITH_PYODIDE_VERSION || "0.26.4";
  const WHEEL = window.DRAFTSMITH_WHEEL; // injected at site build time
  const OPENROUTER = "https://openrouter.ai/api/v1";
  const KEY_STORAGE = "draftsmith_openrouter_key";
  const MODEL_STORAGE = "draftsmith_model";
  const DEMO_MODEL = "demo (canned reply — add a key)";

  const realFetch = window.fetch.bind(window);

  // ------------------------------------------------------------ boot overlay
  let overlay, overlayText;
  function status(text) {
    if (overlayText) overlayText.textContent = text;
  }
  function makeOverlay() {
    overlay = document.createElement("div");
    overlay.style.cssText =
      "position:fixed;inset:0;z-index:9999;background:rgba(250,250,249,.94);" +
      "display:flex;flex-direction:column;align-items:center;justify-content:center;" +
      "gap:10px;font:14px/1.6 system-ui,sans-serif;color:#57534e;text-align:center;padding:24px;";
    const title = document.createElement("div");
    title.textContent = "draftsmith studio — in-browser demo";
    title.style.cssText = "font-weight:700;font-size:17px;color:#292524;";
    overlayText = document.createElement("div");
    overlayText.textContent = "loading…";
    const note = document.createElement("div");
    note.style.cssText = "font-size:12px;max-width:420px;color:#78716c;";
    note.textContent =
      "The full engine (Python + Shapely + matplotlib) is booting in your " +
      "browser via Pyodide — first load fetches ~30 MB, then it's instant. " +
      "Nothing runs on a server.";
    overlay.append(title, overlayText, note);
    document.body.appendChild(overlay);
  }

  // ------------------------------------------------------------ pyodide boot
  const pyReady = (async () => {
    await new Promise((r) =>
      document.readyState === "loading"
        ? document.addEventListener("DOMContentLoaded", r, { once: true })
        : r()
    );
    makeOverlay();
    try {
      status("loading Python runtime…");
      const base = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
      const { loadPyodide } = await import(`${base}pyodide.mjs`);
      const py = await loadPyodide({ indexURL: base });
      status("loading geometry + rendering (shapely, matplotlib)…");
      await py.loadPackage(["shapely", "matplotlib", "micropip"]);
      status("installing draftsmith + ezdxf…");
      const wheelUrl = new URL(WHEEL, location.href).href;
      await py.runPythonAsync(
        "import os, micropip\n" +
        "os.environ['MPLBACKEND'] = 'Agg'\n" +
        "await micropip.install('ezdxf')\n" +
        `await micropip.install('${wheelUrl}', deps=False)\n`
      );
      status("starting the engine…");
      const src = await (await realFetch(new URL("./studio_backend.py", location.href))).text();
      py.FS.writeFile("/home/pyodide/studio_backend.py", src);
      const backend = py.pyimport("studio_backend");
      overlay.remove();
      return { py, backend };
    } catch (err) {
      status(`failed to start: ${err}`);
      throw err;
    }
  })();

  // ------------------------------------------------------------ chat state
  const chatState = {
    model: localStorage.getItem(MODEL_STORAGE) || "",
    served: "",
    modelsPromise: null,
  };
  const getKey = () => localStorage.getItem(KEY_STORAGE) || "";

  function freeModels() {
    chatState.modelsPromise ||= (async () => {
      try {
        const res = await realFetch(`${OPENROUTER}/models`);
        const data = await res.json();
        const ids = (data.data || [])
          .map((m) => m.id)
          .filter((id) => typeof id === "string" && id.endsWith(":free"))
          .sort();
        return ids;
      } catch {
        return [];
      }
    })();
    return chatState.modelsPromise;
  }

  async function chatInfo() {
    const models = await freeModels();
    if (!chatState.model || (!models.includes(chatState.model) && chatState.model !== DEMO_MODEL)) {
      chatState.model =
        models.find((m) => /deepseek|qwen/.test(m)) || models[0] || DEMO_MODEL;
    }
    return {
      backend: "api",
      model: getKey() ? chatState.model : DEMO_MODEL,
      served_model: chatState.served,
      models: [DEMO_MODEL, ...models],
    };
  }

  // Known-good starter plan (the README example) for key-less demo mode.
  const CANNED_FP = [
    "FP1 mm",
    "W1 0,115 8000,115 t230",
    "W2 0,4885 8000,4885 t230",
    "W3 115,230 115,4770 t230",
    "W4 7885,230 7885,4770 t230",
    "W5 5000,230 5000,4770 t120",
    "D1 W5@0 w900 hinge=far",
    "N1 W1@1500 w1200",
    "N2 W1@5800 w1200",
    'L1 2500,2500 "LIVING ROOM"',
    'L2 6450,2500 "BEDROOM"',
    "M1 0,0 8000,0 d-700",
  ].join("\n");
  const CANNED_NOTE =
    "Demo mode: no API key is set, so here is a canned example plan. " +
    "Click the 🔑 button and paste a free OpenRouter key to draft live.";

  async function callOpenRouter(system, prompt) {
    const res = await realFetch(`${OPENROUTER}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${getKey()}`,
      },
      body: JSON.stringify({
        model: chatState.model,
        messages: [
          { role: "system", content: system },
          { role: "user", content: prompt },
        ],
      }),
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      throw new Error(
        data.error?.message || `OpenRouter returned ${res.status}`
      );
    }
    const message = data.choices?.[0]?.message || {};
    chatState.served = data.model || "";
    let content = (message.content || "").trim();
    let reasoning = message.reasoning_content || message.reasoning || "";
    const think = content.match(/<think>([\s\S]*?)<\/think>/);
    if (think) {
      reasoning = reasoning || think[1].trim();
      content = content.replace(/<think>[\s\S]*?<\/think>/g, "").trim();
    }
    return { content, reasoning };
  }

  async function chatTurn(message) {
    const { backend } = await pyReady;
    const live = Boolean(getKey());
    const system = live ? backend.system_prompt() : "";
    let prompt = backend.build_prompt(message);
    const turns = [];
    let applied = false;
    let lastReply = "";
    for (let round = 0; round < 3; round++) {
      let reply, reasoning = "";
      if (live) {
        ({ content: reply, reasoning } = await callOpenRouter(system, prompt));
      } else {
        reply = `${CANNED_NOTE}\n\`\`\`fp\n${CANNED_FP}\n\`\`\``;
      }
      lastReply = reply;
      const result = JSON.parse(backend.chat_reply(reply, reasoning || ""));
      turns.push(...result.turns);
      if (result.applied) {
        applied = true;
        break;
      }
      if (!live) break; // canned reply should never fail; don't loop on it
      prompt =
        `${prompt}\n\nASSISTANT: ${reply}\n\nENGINE: ${result.report}\n` +
        "Fix exactly this error and resend the FULL corrected fp block.";
    }
    backend.chat_record(message, lastReply);
    const state = JSON.parse(backend.handle("state", ""));
    return { turns, applied, chat_info: await chatInfo(), state };
  }

  // ------------------------------------------------------------ fetch shim
  const json = (obj, code = 200) =>
    new Response(JSON.stringify(obj), {
      status: code,
      headers: { "Content-Type": "application/json" },
    });

  async function engineRoute(route, init) {
    const { backend } = await pyReady;
    const body = init && init.body ? String(init.body) : "";
    const out = JSON.parse(backend.handle(route, body));
    if (out && out.__error__) return json({ error: out.__error__ }, out.__code__);
    return json(out);
  }

  window.fetch = async (input, init) => {
    const url = typeof input === "string" ? input : input.url;
    const path = url.startsWith("/") ? url : null;
    if (!path || !path.startsWith("/api/")) return realFetch(input, init);
    try {
      switch (path) {
        case "/api/state":
        case "/api/op":
        case "/api/undo":
        case "/api/redo":
        case "/api/fp":
          return await engineRoute(path.slice(5), init);
        case "/api/chat/info":
          return json(await chatInfo());
        case "/api/chat/model": {
          const { model } = JSON.parse(init.body);
          if (model !== DEMO_MODEL) {
            chatState.model = model;
            localStorage.setItem(MODEL_STORAGE, model);
          }
          return json(await chatInfo());
        }
        case "/api/chat": {
          const { message } = JSON.parse(init.body);
          return json(await chatTurn(message));
        }
        default:
          return json({ error: `no route ${path}` }, 404);
      }
    } catch (err) {
      return json({ error: String(err && err.message ? err.message : err) }, 500);
    }
  };

  // ------------------------------------------- exports + key button (post-app)
  const MIME = {
    dxf: "application/dxf",
    png: "image/png",
    svg: "image/svg+xml",
  };
  function download(fmt, bytes) {
    const blob = new Blob([bytes], { type: MIME[fmt] });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `plan.${fmt}`;
    a.click();
    URL.revokeObjectURL(a.href);
  }
  window.addEventListener("load", () => {
    for (const fmt of ["dxf", "png", "svg"]) {
      const btn = document.getElementById(`${fmt}Btn`);
      if (!btn) continue;
      btn.onclick = async () => {
        const { backend } = await pyReady;
        const bytes = backend.export(fmt);
        const data = bytes.toJs ? bytes.toJs() : bytes;
        if (bytes.destroy) bytes.destroy();
        download(fmt, data);
      };
    }
    const bar = document.getElementById("chatBar");
    if (bar) {
      const keyBtn = document.createElement("button");
      keyBtn.textContent = "🔑";
      keyBtn.title = getKey()
        ? "OpenRouter key set (stored in this browser only) — click to change"
        : "Add a free OpenRouter API key for live LLM drafting";
      keyBtn.style.cssText =
        "border:1px solid #e7e5e4;background:#fff;border-radius:8px;cursor:pointer;padding:0 8px;";
      keyBtn.onclick = () => {
        const key = window.prompt(
          "Paste an OpenRouter API key (sk-or-...).\n\n" +
            "It is stored in this browser's localStorage only and sent " +
            "nowhere except openrouter.ai. Free keys: openrouter.ai/keys " +
            "(free models need no credit).\n\nLeave empty to clear.",
          getKey()
        );
        if (key === null) return;
        if (key.trim()) localStorage.setItem(KEY_STORAGE, key.trim());
        else localStorage.removeItem(KEY_STORAGE);
        location.reload();
      };
      bar.insertBefore(keyBtn, bar.firstChild);
    }
  });
})();
