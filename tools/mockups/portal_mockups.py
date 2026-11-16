"""Макеты экранов портала CreatePortal (GDD портала, docs/portal). Запуск: python tools/mockups/portal_mockups.py"""
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parents[2] / "docs" / "portal" / "mockups"
BG, S, S2, LINE, INK, MUT, ACC = "#EDF1EA", "#FFFFFF", "#F4F7F2", "#D2DBD3", "#13201A", "#566860", "#2B7A52"
OK, WARN, INFO, ERR = "#DAF0E3", "#FBEED2", "#DFEBF9", "#F9DEDC"


class P:
    def __init__(self, title, crumb, w=1440, h=900):
        self.w, self.h = w, h
        self.o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">', f'<rect width="{w}" height="{h}" fill="{BG}"/>']
        self.r(0, 0, w, 64, S, 0, LINE)
        self.t(40, 40, "CreatePortal", 18, INK, w="700")
        self.t(190, 40, "/ " + crumb, 15, MUT)
        self.t(w - 40, 40, "Справка   Тема   Выйти", 14, MUT, "end")
        self.t(40, 110, title, 28, INK, w="700")

    def r(self, x, y, w, h, fill, rx=14, stroke=None):
        s = f' stroke="{stroke}" stroke-width="1.5"' if stroke else ""
        self.o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{s}/>')

    def t(self, x, y, s, size=15, fill=INK, a="start", w=None):
        wt = f' font-weight="{w}"' if w else ""
        self.o.append(f'<text x="{x}" y="{y}" font-family="Inter,sans-serif" font-size="{size}" fill="{fill}" text-anchor="{a}"{wt}>{escape(str(s))}</text>')

    def card(self, x, y, w, h, title=None):
        self.r(x, y, w, h, S, 16, LINE)
        if title:
            self.t(x + 20, y + 30, title, 17, INK, w="600")

    def b(self, x, y, w, label, primary=False, h=40):
        self.r(x, y, w, h, ACC if primary else S, 10, None if primary else LINE)
        self.t(x + w // 2, y + h // 2 + 5, label, 14, "#FFFFFF" if primary else INK, "middle", "600")

    def pill(self, x, y, label, fill, w=None):
        w = w or 12 + len(label) * 7
        self.r(x, y, w, 24, fill, 12)
        self.t(x + w // 2, y + 17, label, 12, INK, "middle", "600")

    def bar(self, x, y, w, pct, color=ACC):
        self.r(x, y, w, 10, LINE, 5)
        self.r(x, y, max(4, w * pct // 100), 10, color, 5)

    def save(self, name):
        (OUT / f"{name}.svg").parent.mkdir(parents=True, exist_ok=True)
        (OUT / f"{name}.svg").write_text("\n".join(self.o + ["</svg>"]) + "\n", encoding="utf-8")


def task_review():
    p = P("A1 Глубокие цепочки: сервер", "Моя игра / Задача A1")
    p.pill(40, 130, "Ждёт приёмки", INFO)
    p.card(40, 170, 860, 320, "Отчёт исполнителя")
    p.t(60, 232, "Вставьте отчёт или ссылку на PR. Портал найдёт PR и покажет проверки.", 14, MUT)
    p.r(60, 245, 820, 90, S2, 10, LINE)
    p.t(76, 272, "PR #104 · ветка v2/a1-deep-chains · SHA 9f3c2a1", 14)
    p.t(76, 298, "Серверные тесты: 331, ошибок 0. Допущения: docs/qa/A1.md", 14, MUT)
    p.b(60, 355, 180, "Открыть PR на GitHub")
    p.b(255, 355, 200, "Обновить статус CI")
    p.t(60, 428, "Проверки CI на PR", 15, INK, w="600")
    p.pill(60, 440, "server test: успех", OK, 160)
    p.pill(236, 440, "client smoke: успех", OK, 170)
    p.pill(422, 440, "website: успех", OK, 140)
    p.card(920, 170, 480, 320, "Приёмка директора")
    for i, (txt, on) in enumerate([("Пробное слияние с main без конфликтов", True), ("Файлы только в зоне линии A", True), ("Серверные тесты у директора: 331 OK", True), ("CI зелёный", True), ("Слито в main (squash)", False)]):
        y = 250 + i * 42
        p.r(940, y - 16, 22, 22, ACC if on else S, 6, LINE)
        p.t(942, y, "✓" if on else "", 14, "#FFFFFF", w="700")
        p.t(974, y, txt, 14.5)
    p.b(940, 452, 200, "Принято, в архив", True)
    p.t(1150, 477, "доступно после всех пунктов", 13, MUT)
    p.card(40, 510, 1360, 150, "Критерии готовности и самопроверка исполнителя")
    for i, t in enumerate(["Полный набор server/tests проходит на PostgreSQL 16", "Новые флаги по умолчанию выключены", "Деньги только через ledger, идемпотентность", "Менялись только файлы зоны линии A"]):
        p.t(60, 570 + i * 22, "✓  " + t, 14, MUT)
    p.card(40, 680, 1360, 190, "Журнал задачи")
    for i, t in enumerate(["16 ноя 11:42  выдано исполнителю", "16 ноя 14:05  сдано, PR #104 открыт", "16 ноя 14:20  CI зелёный, ждёт приёмки директора"]):
        p.t(60, 742 + i * 28, t, 14, MUT)
    p.save("task_review")


def overview():
    p = P("Мои проекты", "Проекты")
    for i, (n, pct, st, vel) in enumerate([("Башкирия: Мёд и Нефть", 14, "в работе", "2,5 задачи в неделю"), ("Новый проект", 0, "нужен GDD", "нет данных"), ("Портал CreatePortal", 100, "готово", "—")]):
        x = 40 + i * 460
        p.card(x, 140, 430, 230)
        p.t(x + 20, 178, n, 18, INK, w="700")
        p.pill(x + 20, 192, st, OK if pct else WARN)
        p.bar(x + 20, 240, 390, pct)
        p.t(x + 20, 275, f"Принято {pct} %", 14, MUT)
        p.t(x + 20, 302, "Скорость: " + vel, 14, MUT)
        p.t(x + 20, 326, "Следующее: A1, B1" if i == 0 else "Следующее: GDD", 14, MUT)
        p.b(x + 20, 336 - 0, 140, "Открыть доску", True)
    p.card(40, 400, 1360, 210, "Требует вашего внимания")
    for i, (t, c) in enumerate([("Башкирия · A1 сдано, ждёт приёмки (2 ч)", INFO), ("Башкирия · B1 можно выдавать исполнителю №2", OK), ("Новый проект · стартовые промпты не выполнены", WARN)]):
        p.pill(60, 440 + i * 50, "●", c, 30)
        p.t(104, 458 + i * 50, t, 15)
        p.b(1230, 436 + i * 50, 130, "Открыть")
    p.card(40, 630, 1360, 240, "Скорость и здоровье (по всем проектам)")
    for i, h in enumerate([30, 45, 40, 62, 55, 70, 64, 80]):
        p.r(70 + i * 70, 840 - h * 2, 44, h * 2, ACC if i == 7 else LINE, 6)
    p.t(660, 700, "Принято задач по неделям", 14, MUT)
    p.t(660, 740, "Среднее время от выдачи до приёмки: 1,8 суток", 15)
    p.t(660, 770, "Доля задач, вернувшихся на доработку: 12 %", 15)
    p.save("overview")


def settings():
    p = P("Настройки", "Настройки")
    p.card(40, 140, 680, 230, "Интеграция с GitHub")
    p.t(60, 195, "Токен только на чтение: подключён", 15)
    p.pill(330, 178, "работает", OK, 90)
    p.t(60, 225, "Последняя синхронизация: сегодня 11:42", 14, MUT)
    p.t(60, 250, "Вебхук GitHub: включён (слияние PR отмечается само)", 14, MUT)
    p.b(60, 280, 200, "Проверить подключение")
    p.b(275, 280, 220, "Показать как подключить")
    p.card(740, 140, 660, 230, "Уведомления")
    for i, (n, on) in enumerate([("Telegram: бот портала", True), ("Почта", False), ("Когда исполнитель сдал", True), ("Когда CI упал", True)]):
        y = 190 + i * 42
        p.r(760, y - 18, 44, 24, ACC if on else LINE, 12)
        p.t(820, y, n, 15)
    p.card(40, 390, 680, 230, "Резервные копии")
    p.t(60, 445, "Ежедневно 03:00, хранится 14 копий", 15)
    p.t(60, 475, "Последняя: сегодня 03:00, 412 КБ, проверка восстановления: успешно", 14, MUT)
    p.b(60, 510, 200, "Создать копию сейчас")
    p.b(275, 510, 240, "Скачать последнюю копию")
    p.card(740, 390, 660, 230, "Исполнители")
    for i, (n, ln, st) in enumerate([("ChatGPT №1", "линия A (сервер)", "занят: A1"), ("ChatGPT №2", "линия B (клиент)", "свободен"), ("Perplexity", "исследования", "нет токенов")]):
        y = 440 + i * 48
        p.t(760, y, n, 15, w="600")
        p.t(900, y, ln, 14, MUT)
        p.pill(1130, y - 18, st, OK if st == "свободен" else (WARN if st.startswith("занят") else ERR), 140)
    p.card(40, 640, 1360, 230, "Доступ и безопасность")
    p.t(60, 695, "Владелец: owner · вход по паролю, сессия 12 часов", 15)
    p.t(60, 725, "Журнал входов и действий: последние 50 записей", 14, MUT)
    p.b(60, 760, 200, "Сменить пароль")
    p.b(275, 760, 220, "Завершить все сеансы")
    p.b(510, 760, 220, "Открыть журнал аудита")
    p.save("settings")


def graph():
    p = P("Граф зависимостей · Моя игра", "Проект / Граф")
    cols = [("Шаг 1", ["A1", "B1"]), ("Шаг 2", ["A2", "B2"]), ("Шаг 3", ["A3", "B3"]), ("Шаг 4", ["A4", "B4"])]
    pos = {}
    for i, (name, ids) in enumerate(cols):
        x = 70 + i * 340
        p.t(x, 150, name, 15, MUT, w="600")
        for j, pid in enumerate(ids):
            y = 180 + j * 190
            st = [OK, INFO, WARN, S2][min(i, 3)] if i else OK
            p.r(x, y, 260, 120, st, 14, LINE)
            p.t(x + 16, y + 34, pid, 17, ACC, w="700")
            p.t(x + 16, y + 62, "Название задачи", 14)
            p.t(x + 16, y + 90, "Линия " + pid[0], 13, MUT)
            pos[pid] = (x, y)
    for a, b in [("A1", "A2"), ("A2", "A3"), ("A3", "A4"), ("B1", "B2"), ("B2", "B3"), ("B3", "B4")]:
        xa, ya = pos[a]
        xb, yb = pos[b]
        p.o.append(f'<path d="M{xa + 260} {ya + 60} L{xb} {yb + 60}" stroke="{MUT}" stroke-width="2" fill="none" marker-end="url(#ar)"/>')
    p.o.insert(2, '<defs><marker id="ar" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="#566860"/></marker></defs>')
    p.t(70, 600, "Зелёное: принято · синее: у исполнителя · жёлтое: можно выдавать · серое: ждёт", 14, MUT)
    p.t(70, 630, "Линии A и B идут параллельно: стрелок между ними нет, зоны файлов не пересекаются.", 14, MUT)
    p.save("graph")


if __name__ == "__main__":
    for f in (task_review, overview, settings, graph):
        f()
