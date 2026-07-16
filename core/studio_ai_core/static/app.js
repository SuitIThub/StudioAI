(() => {
  const statusEl = document.getElementById("status");
  const personaEl = document.getElementById("persona");
  const personaHint = document.getElementById("personaHint");
  const messagesEl = document.getElementById("messages");
  const form = document.getElementById("form");
  const input = document.getElementById("input");
  const sendBtn = document.getElementById("send");
  const btnClear = document.getElementById("btnClear");
  const btnStructured = document.getElementById("btnStructured");
  const structuredOut = document.getElementById("structuredOut");

  /** @type {{role: string, content: string}[]} */
  let history = [];
  let personas = [];

  function setStatus(text, cls) {
    statusEl.textContent = text;
    statusEl.className = "status" + (cls ? " " + cls : "");
  }

  function addBubble(role, content, meta) {
    const div = document.createElement("div");
    div.className = "bubble " + role;
    if (meta) {
      const m = document.createElement("span");
      m.className = "meta";
      m.textContent = meta;
      div.appendChild(m);
    }
    const body = document.createElement("span");
    body.className = "answer";
    body.textContent = content;
    div.appendChild(body);
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return body;
  }

  function addAssistantShell(meta) {
    const div = document.createElement("div");
    div.className = "bubble assistant";
    const metaEl = document.createElement("span");
    metaEl.className = "meta";
    metaEl.textContent = meta || "";
    div.appendChild(metaEl);

    const think = document.createElement("details");
    think.className = "thinking";
    think.hidden = true;
    const summary = document.createElement("summary");
    summary.textContent = "Thinking";
    const thinkBody = document.createElement("pre");
    thinkBody.className = "think-body";
    think.appendChild(summary);
    think.appendChild(thinkBody);
    div.appendChild(think);

    const answer = document.createElement("span");
    answer.className = "answer";
    div.appendChild(answer);

    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return { root: div, metaEl, think, thinkBody, answer };
  }

  async function refreshHealth() {
    try {
      const res = await fetch("/health");
      const data = await res.json();
      const online = data.worker && data.worker.online;
      if (online) {
        setStatus("Worker online · " + (data.worker.url || ""), "ok");
      } else {
        setStatus("Worker OFFLINE – Chat nicht verfügbar", "bad");
      }
      return online;
    } catch (err) {
      setStatus("Core nicht erreichbar", "bad");
      return false;
    }
  }

  async function loadPersonas() {
    const res = await fetch("/v1/personas");
    const data = await res.json();
    personas = data.personas || [];
    personaEl.innerHTML = "";
    for (const p of personas) {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.name + " (" + p.model_id + ")";
      personaEl.appendChild(opt);
    }
    if (data.default_persona) {
      personaEl.value = data.default_persona;
    }
    updatePersonaHint();
  }

  function updatePersonaHint() {
    const p = personas.find((x) => x.id === personaEl.value);
    if (!p) {
      personaHint.textContent = "";
      return;
    }
    const budget = p.default_max_tokens ? " · max_tokens " + p.default_max_tokens : "";
    personaHint.textContent = p.description + budget;
  }

  function personaMaxTokens() {
    const p = personas.find((x) => x.id === personaEl.value);
    return (p && p.default_max_tokens) || 8192;
  }

  personaEl.addEventListener("change", () => {
    history = [];
    messagesEl.innerHTML = "";
    updatePersonaHint();
    addBubble("system", "Persona gewechselt – Verlauf geleert.");
  });

  btnClear.addEventListener("click", () => {
    history = [];
    messagesEl.innerHTML = "";
    structuredOut.hidden = true;
  });

  btnStructured.addEventListener("click", async () => {
    structuredOut.hidden = false;
    structuredOut.textContent = "Läuft… (Qwen + GBNF)";
    try {
      const res = await fetch("/v1/structured", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: 'Return JSON only for {"ok": true, "message": "stage2"}\n',
          grammar_file: "smoke_json.gbnf",
          max_tokens: 64,
          temperature: 0.1,
        }),
      });
      const data = await res.json();
      structuredOut.textContent = JSON.stringify(data, null, 2);
      if (res.status === 503) {
        setStatus("Worker OFFLINE", "bad");
      }
    } catch (err) {
      structuredOut.textContent = String(err);
    }
  });

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const text = input.value.trim();
    if (!text) return;

    input.value = "";
    addBubble("user", text);
    history.push({ role: "user", content: text });

    const shell = addAssistantShell(personaEl.value + " …");
    sendBtn.disabled = true;

    try {
      const res = await fetch("/v1/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: history,
          persona: personaEl.value,
          stream: true,
          // Always send explicitly – omitted values may hit an old Core default (512).
          max_tokens: personaMaxTokens(),
        }),
      });

      if (res.status === 503) {
        const err = await res.json();
        shell.answer.textContent =
          "Worker offline: " +
          ((err.detail && err.detail.message) || JSON.stringify(err));
        history.pop();
        setStatus("Worker OFFLINE", "bad");
        return;
      }

      if (!res.ok || !res.body) {
        const errText = await res.text();
        shell.answer.textContent = "Fehler: " + errText;
        history.pop();
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let full = "";
      let reasoning = "";
      let finishReason = null;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const part of parts) {
          const lines = part.split("\n");
          for (const line of lines) {
            if (!line.startsWith("data:")) continue;
            const raw = line.slice(5).trim();
            if (raw === "[DONE]") continue;
            let obj;
            try {
              obj = JSON.parse(raw);
            } catch {
              continue;
            }
            if (obj.type === "error") {
              shell.answer.textContent =
                "Fehler [" + (obj.code || "?") + "]: " + (obj.message || "");
              full = "";
              if (obj.code === "worker_offline") setStatus("Worker OFFLINE", "bad");
              continue;
            }
            if (obj.type === "meta") {
              const mt = obj.max_tokens ? " · " + obj.max_tokens + " tok" : "";
              shell.metaEl.textContent =
                (obj.persona || "") + " · " + (obj.model || "") + mt;
              continue;
            }
            const choices = obj.choices || [];
            if (!choices.length) continue;
            if (choices[0].finish_reason) {
              finishReason = choices[0].finish_reason;
            }
            const delta = choices[0].delta || {};
            const reasonPiece = delta.reasoning_content || delta.reasoning || "";
            if (reasonPiece) {
              reasoning += reasonPiece;
              shell.think.hidden = false;
              shell.thinkBody.textContent = reasoning;
              if (!shell.think.open && !full) shell.think.open = true;
              messagesEl.scrollTop = messagesEl.scrollHeight;
            }
            const piece = delta.content || "";
            if (piece) {
              full += piece;
              shell.answer.textContent = full;
              if (shell.think.open && full) shell.think.open = false;
              messagesEl.scrollTop = messagesEl.scrollHeight;
            }
          }
        }
      }

      if (full) {
        history.push({ role: "assistant", content: full });
        if (finishReason === "length") {
          const note = document.createElement("div");
          note.className = "truncate-note";
          note.textContent =
            "Abgeschnitten (Token-Limit). Thinking verbraucht mit max_tokens dasselbe Budget — ggf. kürzer denken lassen oder max_tokens erhöhen.";
          shell.root.appendChild(note);
        }
      } else if (reasoning) {
        shell.answer.textContent =
          "(noch keine Antwort – Thinking hat das Token-Budget verbraucht)";
        history.pop();
      } else {
        shell.answer.textContent = "(leere Antwort)";
        history.pop();
      }
      await refreshHealth();
    } catch (err) {
      shell.answer.textContent = "Request fehlgeschlagen: " + err;
      history.pop();
    } finally {
      sendBtn.disabled = false;
      input.focus();
    }
  });

  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      form.requestSubmit();
    }
  });

  (async () => {
    await refreshHealth();
    try {
      await loadPersonas();
      addBubble("system", "Mehrturn-Chat bereit. Persona wählen und losschreiben.");
    } catch (err) {
      addBubble("system", "Personas konnten nicht geladen werden: " + err);
    }
    setInterval(refreshHealth, 15000);
  })();
})();
