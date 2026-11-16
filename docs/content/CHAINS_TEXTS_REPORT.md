# Отчёт: тексты нового каталога

Ветка `v2/chain-texts`. Игровые тексты для предложения цепочек. `server/data` и код клиента не менялись. Единственный файл вне списка содержания — `client/data/strings.json`: его пересобрал `python3 tools/build_strings.py`, иначе `--check` не сходится с новыми ключами интерфейса. Формулировки туда руками не писались.

## Сколько добавлено

| Файл | Что добавлено |
|---|---|
| `docs/content/products.ru.md` | 16 строк товаров |
| `docs/content/buildings.ru.md` | 22 строки зданий |
| `docs/content/glossary.ru.md` | 4 термина: стройматериалы, норма на стадию, топливо рейса, городской газ |
| `docs/content/ui_strings.ru.md` | 9 ключей |
| `client/data/strings.json` | те же 9 ключей, сборка из документации |

Старые строки таблиц не менялись.

## Id без текста

Пусто. В таблицах 41 товар и 42 здания, каждый id предложения ровно один раз. Названия совпадают с `tools/sim/data/chains_proposed` и внутри файла не повторяются.

Новые товары: `sugar_beet`, `feed`, `flax`, `yarn`, `boards`, `furniture`, `iron_ore`, `coal`, `glass`, `appliances`, `car`, `malt`, `kvass`, `kefir`, `mead`, `smoked_fish`.

Новые здания: `logging_camp`, `gas_well`, `mine`, `feed_plant`, `sugar_plant`, `creamery`, `poultry_farm`, `fishery`, `smokehouse`, `spinning_mill`, `malthouse`, `beverage_plant`, `glass_plant`, `polymer_plant`, `furniture_workshop`, `appliance_plant`, `auto_plant`, `furniture_store`, `electronics_store`, `fuel_station`, `car_dealer`, `hardware_store`.

## Сомнения

1. «Специализация магазина» в глоссарии уже была. Второй раз не добавлял.
2. В строке `build.material.stage` единица «шт.», как в задании. В каталоге цемент, лес и камень измеряются килограммами. Для интерфейса оставил формулировку задания.
3. В описании руды стоит «белорецкой стали». Это город из каталога, не название комбината. Названий настоящих компаний в новых текстах нет.
4. Строки продуктового и супермаркета не дополнял: старые строки трогать нельзя. Что туда кладут кефир, квас, медовуху и копчёную рыбу, сказано в фишках этих товаров.
5. Абзацы TBD внизу таблиц не переписывал. Пример «мебель» там остался, хотя строка мебели уже есть.
6. Описания новых товаров короткие и близки к текстам предложения, чтобы таблица и JSON не разошлись. Живой тон сидит в колонке «фишка» и «польза».

## Проверка длин

Лимиты: описание ≤ 90, фишка и польза ≤ 140. Самописная сверка с JSON предложения:

```
products: rows=41 proposal=41 missing=[] extra=[] dup_ids=[]
  dup_names=[]
  over_or_mismatch=[]
  new=16
  len sugar_beet: desc=33 extra=59
  len feed: desc=38 extra=58
  len flax: desc=29 extra=58
  len yarn: desc=32 extra=48
  len boards: desc=39 extra=54
  len furniture: desc=28 extra=60
  len iron_ore: desc=26 extra=63
  len coal: desc=23 extra=48
  len glass: desc=36 extra=66
  len appliances: desc=36 extra=78
  len car: desc=35 extra=79
  len malt: desc=25 extra=45
  len kvass: desc=24 extra=49
  len kefir: desc=23 extra=55
  len mead: desc=28 extra=55
  len smoked_fish: desc=27 extra=54
buildings: rows=42 proposal=42 missing=[] extra=[] dup_ids=[]
  dup_names=[]
  over_or_mismatch=[]
  new=22
  len logging_camp: desc=35 extra=69
  len gas_well: desc=23 extra=64
  len mine: desc=22 extra=62
  len feed_plant: desc=26 extra=55
  len sugar_plant: desc=22 extra=64
  len creamery: desc=26 extra=61
  len poultry_farm: desc=25 extra=50
  len fishery: desc=20 extra=46
  len smokehouse: desc=19 extra=52
  len spinning_mill: desc=19 extra=53
  len malthouse: desc=26 extra=55
  len beverage_plant: desc=22 extra=67
  len glass_plant: desc=29 extra=60
  len polymer_plant: desc=24 extra=53
  len furniture_workshop: desc=33 extra=58
  len appliance_plant: desc=26 extra=65
  len auto_plant: desc=29 extra=64
  len furniture_store: desc=25 extra=65
  len electronics_store: desc=30 extra=62
  len fuel_station: desc=16 extra=63
  len car_dealer: desc=19 extra=58
  len hardware_store: desc=30 extra=67
forbidden none
```

Самая длинная новая фишка — автомобиль, 79 знаков. Самая длинная польза — лесосека, 69. Оба ниже лимита.

## Проверка строк

```
python3 tools/build_strings.py --check
strings OK: 290 keys

python3 -m unittest tools.tests.test_strings
Ran 3 tests
OK
```
