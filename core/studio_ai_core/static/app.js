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
    body.textContent = content;
    div.appendChild(body);
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return body;
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
    personaHint.textContent = p ? p.description : "";
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

    const assistantBody = addBubble(
      "assistant",
      "",
      personaEl.value + " …"
    );
    sendBtn.disabled = true;

    try {
      const res = await fetch("/v1/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: history,
          persona: personaEl.value,
          stream: true,
        }),
      });

      if (res.status === 503) {
        const err = await res.json();
        assistantBody.textContent =
          "Worker offline: " +
          ((err.detail && err.detail.message) || JSON.stringify(err));
        history.pop();
        setStatus("Worker OFFLINE", "bad");
        return;
      }

      if (!res.ok || !res.body) {
        const errText = await res.text();
        assistantBody.textContent = "Fehler: " + errText;
        history.pop();
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let full = "";
      let modelMeta = personaEl.value;

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
              assistantBody.textContent =
                "Fehler [" + (obj.code || "?") + "]: " + (obj.message || "");
              full = "";
              if (obj.code === "worker_offline") setStatus("Worker OFFLINE", "bad");
              continue;
            }
            if (obj.type === "meta") {
              modelMeta = (obj.persona || "") + " · " + (obj.model || "");
              const metaEl = assistantBody.parentElement.querySelector(".meta");
              if (metaEl) metaEl.textContent = modelMeta;
              continue;
            }
            const choices = obj.choices || [];
            if (choices.length) {
              const delta = choices[0].delta || {};
              const piece = delta.content || "";
              if (piece) {
                full += piece;
                assistantBody.textContent = full;
                messagesEl.scrollTop = messagesEl.scrollHeight;
              }
            }
          }
        }
      }

      if (full) {
        history.push({ role: "assistant", content: full });
      } else if (!assistantBody.textContent) {
        assistantBody.textContent = "(leere Antwort)";
        history.pop();
      }
      await refreshHealth();
    } catch (err) {
      assistantBody.textContent = "Request fehlgeschlagen: " + err;
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
