(() => {
  const statusEl = document.getElementById("status");
  const resultEl = document.getElementById("result");
  const previewEl = document.getElementById("preview");
  const hintEl = document.getElementById("hint");

  function setStatus(text, cls) {
    statusEl.textContent = text;
    statusEl.className = "status" + (cls ? " " + cls : "");
  }

  function bodyFromForm() {
    const instruction = document.getElementById("instruction").value.trim();
    return {
      character_id: Number(document.getElementById("character").value || 0),
      camera_source: document.getElementById("camera").value,
      caption_preset: document.getElementById("preset").value,
      instruction: instruction || null,
      polish_with_chat: document.getElementById("polish").checked,
      size: 768,
      debounce_s: Number(document.getElementById("debounce").value || 12),
    };
  }

  function showResult(data) {
    resultEl.textContent = JSON.stringify(data, null, 2);
    if (data && data.image_path) {
      // Local path can't be served; show caption prominently if present
      hintEl.textContent = data.caption
        ? "Caption ok · Bild liegt unter " + data.image_path
        : hintEl.textContent;
    }
  }

  async function refreshHealth() {
    try {
      const res = await fetch("/health");
      const data = await res.json();
      const bridge = data.bridge && data.bridge.online;
      const worker = data.worker && data.worker.online;
      const vision = data.vision || {};
      setStatus(
        (bridge ? "Bridge ok" : "Bridge offline") +
          " · " +
          (worker ? "Worker ok" : "Worker offline") +
          (vision.indexing ? " · INDEX läuft (Watch pausiert)" : ""),
        bridge ? "ok" : "bad"
      );
    } catch (err) {
      setStatus("Core nicht erreichbar", "bad");
    }
  }

  async function analyze() {
    setStatus("Analysiere…", "");
    const res = await fetch("/v1/scene-feedback/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bodyFromForm()),
    });
    const data = await res.json();
    showResult(data);
    await refreshHealth();
  }

  async function watchStart() {
    const res = await fetch("/v1/scene-feedback/watch/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bodyFromForm()),
    });
    const data = await res.json();
    showResult(data);
    await refreshHealth();
  }

  async function watchStop() {
    const res = await fetch("/v1/scene-feedback/watch/stop", { method: "POST" });
    showResult(await res.json());
    await refreshHealth();
  }

  async function refreshStatus() {
    const res = await fetch("/v1/scene-feedback/status");
    showResult(await res.json());
    await refreshHealth();
  }

  document.getElementById("btnAnalyze").addEventListener("click", () => {
    analyze().catch((e) => {
      resultEl.textContent = String(e);
      setStatus("Fehler", "bad");
    });
  });
  document.getElementById("btnWatch").addEventListener("click", () => {
    watchStart().catch((e) => {
      resultEl.textContent = String(e);
    });
  });
  document.getElementById("btnStop").addEventListener("click", () => {
    watchStop().catch((e) => {
      resultEl.textContent = String(e);
    });
  });
  document.getElementById("btnRefresh").addEventListener("click", () => {
    refreshStatus().catch((e) => {
      resultEl.textContent = String(e);
    });
  });

  refreshHealth();
  setInterval(refreshHealth, 10000);
})();
