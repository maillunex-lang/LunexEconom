"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const select = $("art-catalog-id");
  const mode = $("art-catalog-mode");
  const file = $("art-catalog-file");
  const preview = $("art-catalog-preview");
  const status = $("art-catalog-status");
  let items = new Map();
  let previewUrl = null;

  async function refresh() {
    if (!token) return;
    const result = await api("/api/art-catalog");
    const previous = select.value;
    items = new Map(result.items.map(item => [item.id, item]));
    select.replaceChildren();
    for (const item of result.items) {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.id;
      select.append(option);
    }
    if (items.has(previous)) select.value = previous;
    showMode();
  }
  function showMode() {
    const item = items.get(select.value);
    mode.value = item?.mode || "default";
    const base = "/lunexeconom/assets/art-catalog/";
    for (const [elementId, folder, sha] of [["art-default-preview", "defaults", item?.default_sha256], ["art-custom-preview", "custom", item?.custom_sha256]]) {
      const img = $(elementId);
      img.style.display = sha ? "block" : "none";
      if (sha) img.src = base + folder + "/" + sha + ".png";
      else img.removeAttribute("src");
    }
    $("art-catalog-source").textContent = item?.source || "Стандартный спрайт ещё не назначен";
    status.textContent = item?.custom_sha256
      ? "Своя версия: " + item.custom_sha256.slice(0, 16) + "…"
      : "Своя версия ещё не загружена";
  }
  select.addEventListener("change", showMode);
  file.addEventListener("change", () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    preview.style.display = "none";
    if (file.files.length) {
      previewUrl = URL.createObjectURL(file.files[0]);
      preview.src = previewUrl;
      preview.style.display = "block";
    }
  });
  async function post(path, payload) {
    return api(path, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload)
    });
  }
  $("art-catalog-mode-save").addEventListener("click", async () => {
    if (!token) { status.textContent = "Сначала авторизуйся"; return; }
    if (!confirm("Переключить графику для " + select.value + "?")) return;
    try {
      await post("/api/art-catalog/mode", {id: select.value, mode: mode.value});
      await refresh();
      status.textContent = "Режим сохранён";
    } catch (e) { status.textContent = "Ошибка: " + e.message; }
  });
  $("art-catalog-form").addEventListener("submit", async event => {
    event.preventDefault();
    const chosen = file.files[0];
    if (!token || !chosen || chosen.size > 8 * 1024 * 1024 || chosen.type !== "image/png") {
      status.textContent = "Нужен токен и PNG до 8 МБ"; return;
    }
    if (!confirm("Сохранить новую версию для " + select.value + "?")) return;
    status.textContent = "Загрузка...";
    try {
      const bytes = new Uint8Array(await chosen.arrayBuffer());
      let binary = "";
      for (let i = 0; i < bytes.length; i += 8192)
        binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
      await post("/api/art-catalog/upload", {id: select.value, data_base64: btoa(binary)});
      await refresh();
      status.textContent = "PNG сохранён, выбран режим «Своя»";
    } catch (e) { status.textContent = "Ошибка: " + e.message; }
  });
  $("connect").addEventListener("click", () => {
    setTimeout(() => refresh().catch(e => {status.textContent = e.message;}), 350);
  });
})();