"use strict";
(() => {
  const form = document.getElementById("models-upload");
  const status = document.getElementById("models-status");
  const listing = document.getElementById("models-list");
  const toBase64 = (bytes) => {
    let text = "";
    for (let i = 0; i < bytes.length; i += 8192) {
      text += String.fromCharCode(...bytes.subarray(i, i + 8192));
    }
    return btoa(text);
  };
  async function refreshModels() {
    if (!token) return;
    const data = await api("/api/models");
    listing.replaceChildren();
    for (const model of data.files) {
      const row = document.createElement("p");
      row.textContent = model.kind + " · " + model.name + " · " +
        model.triangles + " треугольников · " + model.bytes + " байт · SHA-256 " +
        model.sha256.slice(0, 16) + "…";
      listing.append(row);
    }
  }
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!token) { status.textContent = "Сначала войдите в студию"; return; }
    const file = document.getElementById("models-file").files[0];
    const name = document.getElementById("models-name").value;
    if (!file || file.size > 8 * 1024 * 1024 || !file.name.toLowerCase().endsWith(".glb")) {
      status.textContent = "Выберите .glb размером до 8 МБ"; return;
    }
    if (!confirm("Сохранить эту модель в частный каталог студии? В клиент автоматически не публикуется.")) return;
    const button = event.submitter;
    if (button) button.disabled = true;
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      const result = await api("/api/models", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name, data_base64: toBase64(bytes)})
      });
      status.textContent = "Сохранено: " + result.name + ", " + result.triangles + " треугольников";
      await refreshModels();
    } catch (error) { status.textContent = "Ошибка: " + error.message; }
    finally { if (button) button.disabled = false; }
  });
  document.getElementById("connect").addEventListener("click", () => {
    setTimeout(() => refreshModels().catch(() => {}), 300);
  });
})();