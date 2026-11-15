"use strict";
(function () {
  const goods = document.getElementById("goods-output");
  const deposits = document.getElementById("deposits-output");
  const render = (node, value) => { node.textContent = JSON.stringify(value, null, 2); };
  document.getElementById("goods-refresh").addEventListener("click", async () => {
    try { render(goods, await api("/api/catalog/goods")); }
    catch (error) { goods.textContent = "Ошибка: " + error.message; }
  });
  document.getElementById("deposits-filter").addEventListener("submit", async event => {
    event.preventDefault();
    const params = new URLSearchParams(new FormData(event.currentTarget));
    try { render(deposits, await api("/api/deposits?" + params.toString())); }
    catch (error) { deposits.textContent = "Ошибка: " + error.message; }
  });
})();