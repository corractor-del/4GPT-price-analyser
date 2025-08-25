
# Avito Price Analyzer (Compliant GUI)

**Важно:** приложение НЕ обходит защиту сайта и НЕ предназначено для обхода ограничений. Оно уважительно работает с публичными страницами, ставит паузы, логирует и позволяет безопасно останавливать процесс.

## Возможности
- Окно с кнопками **Старт/Стоп** и прогресс‑баром
- Drag & Drop Excel-файла
- Поддержка `cookies.txt` (формат Netscape) — опционально
- Настраиваемый rate-limit (запросов в минуту) и burst
- Чекпоинт `checkpoint.csv` и возобновление
- Автоматическая замена имени выходных файлов, если такие уже существуют (`file (1).xlsx`, `file (2).csv`)

## Требования
Python 3.9+

```
pip install -r requirements.txt
```

## Запуск
```
python -m app.main
```

## Формат Excel
- Колонка A: бренд
- Колонка B: модель/характеристики
- Колонка C: закупка (опционально)

## Примечания
- Вставьте свою законную логику парсинга в `app/analyzer.py -> parse_listing`.
- Иконка находится в `assets/icon.ico`.


## Сборка .exe
1) Установи зависимости:
```
pip install -r requirements.txt
pip install pyinstaller
```
2) Запусти сборку (Windows):
```
build.bat
```
или универсально:
```
pyinstaller build.spec
```
Готовый файл появится в `dist/AvitoPriceAnalyzer.exe` (или в папке `dist/AvitoPriceAnalyzer/`).
