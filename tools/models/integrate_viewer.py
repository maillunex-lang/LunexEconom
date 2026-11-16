"""One-time additive integration of the optional model preview screen."""
from pathlib import Path

def replace_file(name, pairs):
    p=Path(name)
    data=p.read_text(encoding="utf-8")
    for before, after in pairs:
        if before not in data:
            raise RuntimeError(f"missing integration anchor {name}: {before!r}")
        data=data.replace(before,after,1)
    p.write_text(data,encoding="utf-8")

replace_file("client/screens/more.gd",[
 ('["nav.more.updates", "updates"],','["nav.more.updates", "updates"],\n        ["model.viewer.title", "model_viewer"],')])
replace_file("client/screens/settings.gd",[
 ('signal reset_tutorial_requested','signal reset_tutorial_requested\nsignal model_viewer_requested'),
 ('    for key in ["settings.language"',
  '    var viewer := Button.new()\n    viewer.name = "OpenModelViewer"\n    viewer.text = Strings.get_text("model.viewer.title")\n    viewer.custom_minimum_size = Vector2(220,48)\n    viewer.pressed.connect(func(): model_viewer_requested.emit())\n    stack.add_child(viewer)\n    for key in ["settings.language"')])
replace_file("client/main.gd",[
 ('const MoreScreen = preload("res://screens/more.tscn")',
  'const MoreScreen = preload("res://screens/more.tscn")\nconst ModelViewerScreen = preload("res://screens/model_viewer.tscn")'),
 ('var more_screen: Control','var more_screen: Control\nvar model_viewer_screen: Control'),
 ('    more_screen = MoreScreen.instantiate()',
  '    more_screen = MoreScreen.instantiate()\n    model_viewer_screen = ModelViewerScreen.instantiate()'),
 ('    router.register_screen("more",more_screen)',
  '    router.register_screen("more",more_screen)\n    router.register_screen("model_viewer",model_viewer_screen)'),
 ('    settings_screen.back_requested.connect(func(): router.back())',
  '    settings_screen.back_requested.connect(func(): router.back())\n    settings_screen.model_viewer_requested.connect(_navigate.bind("model_viewer"))\n    model_viewer_screen.back_requested.connect(func(): router.back())')])
replace_file("client/screens/router.gd",[
 ('"more", "finance"]','"more", "finance", "model_viewer"]')])
p=Path("docs/content/ui_strings.ru.md")
p.write_text(p.read_text(encoding="utf-8")+"""
model.viewer.title | Просмотр 3D-моделей
model.viewer.back | Назад
model.viewer.filter | Категория объектов
model.viewer.all | Все модели
model.viewer.buildings | Предприятия и здания
model.viewer.city | Городские объекты
model.viewer.stage | Стадия {stage} из 4
model.viewer.statistics | Треугольников: {triangles} · Размер: {kib} КиБ
model.viewer.failed | Не удалось загрузить модель. Показана запасная коробка.
model.viewer.gestures | Поверните одним пальцем, измените масштаб двумя пальцами.
""",encoding="utf-8")
print("Integration complete")
