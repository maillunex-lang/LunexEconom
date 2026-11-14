"use strict";
(() => {
  const file = document.getElementById("game-art-file");
  const preview = document.getElementById("game-art-preview");
  const status = document.getElementById("game-art-status");
  const listing = document.getElementById("game-art-list");
  let objectUrl = null;
  file.addEventListener("change", () => {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    preview.style.display = "none";
    if (!file.files.length) return;
    objectUrl = URL.createObjectURL(file.files[0]);
    preview.src = objectUrl;
    preview.style.display = "block";
  });
  async function refresh() {
    if (!token) return;
    const response = await api("/api/game-art");
    listing.replaceChildren();
    for (const item of response.files) {
      const row = document.createElement("p");
      const link = document.createElement("a");
      link.href = "/lunexeconom/assets/" + encodeURIComponent(item.name);
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = item.name;
      row.append(link, document.createTextNode(" · SHA-256 " + item.sha256.slice(0, 12) + "…"));
      listing.append(row);
    }
  }
  document.getElementById("game-art-upload").addEventListener("submit", async (event) => {
    event.preventDefault();
    const selected = file.files[0];
    if (!selected || !selected.name.toLowerCase().endsWith(".png") || selected.size > 8 * 1024 * 1024) {
      status.textContent = "Выбери PNG до 8 МБ";
      return;
    }
    if (!token) {
      status.textContent = "Сначала подключись с токеном администратора";
      return;
    }
    if (!confirm("Опубликовать выбранный PNG для всех игроков?")) return;
    const button = event.submitter;
    if (button) button.disabled = true;
    status.textContent = "Загрузка...";
    try {
      const bytes = new Uint8Array(await selected.arrayBuffer());
      let binary = "";
      for (let i = 0; i < bytes.length; i += 8192) {
        binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
      }
      const result = await api("/api/game-art", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name: document.getElementById("game-art-name").value, data_base64: btoa(binary)})
      });
      status.textContent = "Опубликовано: " + result.name + " · " + result.width + "×" + result.height + " · " + result.sha256.slice(0, 12);
      await refresh();
    } catch (error) {
      status.textContent = "Ошибка: " + error.message;
    } finally {
      if (button) button.disabled = false;
    }
  });
  document.getElementById("connect").addEventListener("click", () => {
    setTimeout(() => { refresh().catch(() => {}); }, 300);
  });
})();