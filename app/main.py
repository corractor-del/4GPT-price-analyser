
import os, logging, threading
import PySimpleGUI as sg
import sys

def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(__file__))
    return os.path.join(base, rel)

from analyzer import ClientConfig, AvitoClient, load_items_from_excel, process_items, save_output

# ---- logging ----
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[logging.StreamHandler()])
log = logging.getLogger("GUI")

sg.theme("SystemDefault")

def create_layout(icon_path):
    left = [
        [sg.Text("Excel файл:"), sg.Input(key="-EXCEL-", expand_x=True, enable_events=True), sg.FileBrowse(file_types=(("Excel", "*.xlsx;*.xls"),))],
        [sg.Text("Cookies (txt):"), sg.Input(key="-COOK-", expand_x=True), sg.FileBrowse(file_types=(("Cookies", "*.txt"),))],
        [sg.Text("Запросов в минуту:"), sg.Spin(values=list(range(4,61)), initial_value=12, key="-RATE-", size=(5,1)),
         sg.Text("Burst:"), sg.Spin(values=list(range(1,11)), initial_value=3, key="-BURST-", size=(5,1))],
        [sg.ProgressBar(100, orientation="h", size=(40, 20), key="-PROG-")],
        [sg.Multiline(size=(80,12), key="-LOG-", autoscroll=True, write_only=True, disabled=True)],
        [sg.Button("Старт", key="-START-", button_color=("white","#2e7d32")),
         sg.Button("Стоп", key="-STOP-", button_color=("white","#c62828")),
         sg.Button("Выход", key="-EXIT-")],
        [sg.Text("Перетащи файл Excel сюда:"), sg.FileDrop(key="-DROP-", enable_events=True, drag_and_drop=True, tooltip="Перетащи .xlsx файл сюда")],
        [sg.Text("Результаты будут сохранены рядом с исходным Excel.")]
    ]
    col = [[sg.Column(left, expand_x=True)]]
    return col

def main():
    icon_path = resource_path(os.path.join("assets", "icon.ico"))
    layout = create_layout(icon_path)
    window = sg.Window("Avito Price Analyzer (Compliant)", layout, icon=icon_path, finalize=True)

    worker_thread = None
    stop_event = threading.Event()

    def ui_log(msg):
        window["-LOG-"].update(msg + "\n", append=True)

    def on_progress(done, total, note):
        pct = int((done/total)*100) if total else 0
        window["-PROG-"].update(pct)
        ui_log(f"[{done}/{total}] {note}")

    def run_worker(excel, cookies, rate, burst):
        try:
            cfg = ClientConfig(rate_per_min=rate, burst=burst)
            client = AvitoClient(cookies, cfg)
            items = load_items_from_excel(excel)
            ui_log(f"Загружено позиций: {len(items)}")
            results = process_items(items, client, checkpoint="checkpoint.csv", stop_event=stop_event, progress_cb=on_progress)
            csv_path, xlsx_path = save_output(results, excel)
            ui_log(f"Готово. CSV: {csv_path} | XLSX: {xlsx_path}")
        except Exception as e:
            ui_log(f"Ошибка: {e}")
        finally:
            window["-START-"].update(disabled=False)
            window["-STOP-"].update(disabled=True)

    while True:
        event, values = window.read(timeout=100)
        if event in (sg.WIN_CLOSED, "-EXIT-"):
            if worker_thread and worker_thread.is_alive():
                stop_event.set()
                worker_thread.join(timeout=2)
            break

        if event == "-DROP-":
            # FileDrop returns a string path; set it to input
            window["-EXCEL-"].update(values["-DROP-"])

        if event == "-START-":
            excel = values["-EXCEL-"]
            cookies = values["-COOK-"] or None
            rate = int(values["-RATE-"])
            burst = int(values["-BURST-"])
            if not excel or not os.path.exists(excel):
                sg.popup_error("Укажи корректный Excel файл")
                continue
            stop_event.clear()
            window["-START-"].update(disabled=True)
            window["-STOP-"].update(disabled=False)
            window["-LOG-"].update("")
            window["-PROG-"].update(0)
            worker_thread = threading.Thread(target=run_worker, args=(excel, cookies, rate, burst), daemon=True)
            worker_thread.start()

        if event == "-STOP-":
            if worker_thread and worker_thread.is_alive():
                stop_event.set()
                ui_log("Остановка...")
            window["-STOP-"].update(disabled=True)

    window.close()

if __name__ == "__main__":
    main()
