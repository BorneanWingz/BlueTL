import os
import importlib.util
import queue
import threading
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import app
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox


@pytest.fixture
def window(monkeypatch, tmp_path):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(app, "CFG", tmp_path / "config.json")
    monkeypatch.setattr(app.Window, "start_update_check", lambda self: None)
    window = app.Window()
    window.show()
    yield window
    window.close()
    application.processEvents()


class FakeProcess:
    def __init__(self, target, args):
        self.args = args
        self.alive = True
        self.exitcode = 0

    def start(self):
        pass

    def is_alive(self):
        return self.alive

    def join(self):
        pass


class FakeQueue(queue.Queue):
    def close(self):
        pass


class FakeContext:
    Queue = FakeQueue
    Event = threading.Event
    Process = FakeProcess


def start_fake_ocr(window, monkeypatch):
    monkeypatch.setattr(app.multiprocessing, "get_context", lambda _: FakeContext())
    window.paths = ["page1.png"]
    window.ocr()
    return window.ocr_process, window.ocr_events


def test_ocr_updates_table_and_scrolls_while_running(window, monkeypatch):
    process, events = start_fake_ocr(window, monkeypatch)
    for i in range(80):
        events.put(("row", 1, i + 1, f"line {i}", "", ""))
    window.poll_ocr()
    QApplication.processEvents()
    assert window.busy
    assert window.table.rowCount() == 80
    scrollbar = window.table.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum())
    assert scrollbar.maximum() > 0
    assert scrollbar.value() == scrollbar.maximum()
    events.put(("finished", "completed", []))
    process.alive = False
    window.poll_ocr()
    assert not window.busy
    assert window.recognized


def test_stop_keeps_rows_and_does_not_continue(window, monkeypatch):
    process, events = start_fake_ocr(window, monkeypatch)
    called = []
    window.ocr_continuation = lambda: called.append(True)
    events.put(("row", 1, 1, "text", "", ""))
    window.stop()
    assert window.ocr_cancel.is_set()
    events.put(("finished", "stopped", []))
    process.alive = False
    window.poll_ocr()
    QApplication.processEvents()
    assert len(window.rows) == 1
    assert not called
    assert "stopped" in window.status.text().lower()


def test_close_requests_cancellation_and_waits_for_worker(window, monkeypatch):
    process, events = start_fake_ocr(window, monkeypatch)
    window.close()
    assert window.isVisible()
    assert window.ocr_cancel.is_set()
    events.put(("finished", "stopped", []))
    process.alive = False
    window.poll_ocr()
    assert not window.isVisible()


def test_worker_failure_is_reported_and_not_marked_recognized(window, monkeypatch):
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: errors.append(args))
    process, events = start_fake_ocr(window, monkeypatch)
    events.put(("error", "ImportError", "missing dependency"))
    process.alive = False
    window.poll_ocr()
    assert not window.recognized
    assert "missing dependency" in errors[0][2]


def test_failed_rerecognition_preserves_existing_edits(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)
    window.rows = [app.Row(1, 1, "original")]
    window.recognized = True
    window.refresh()
    window.table.item(0, 2).setText("edited")
    process, events = start_fake_ocr(window, monkeypatch)
    events.put(("error", "ImportError", "missing dependency"))
    process.alive = False
    window.poll_ocr()
    assert window.recognized
    assert window.rows[0].jp == "edited"
    assert window.table.item(0, 2).text() == "edited"


def test_completed_ocr_continues_translation(window, monkeypatch):
    process, events = start_fake_ocr(window, monkeypatch)
    called = []
    window.ocr_continuation = lambda: called.append(True)
    events.put(("finished", "completed", []))
    process.alive = False
    window.poll_ocr()
    loop = QEventLoop()
    QTimer.singleShot(10, loop.quit)
    loop.exec()
    assert called == [True]


def test_translation_runs_in_background_and_stop_keeps_finished_row(window, monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def create(**kwargs):
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="translated"))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(window, "client", lambda: client)
    window.model.addItem("example-model")
    window.rows = [app.Row(1, i + 1, f"line {i}", tr="done" if i else "") for i in range(80)]
    window.recognized = True
    window.refresh()
    window.all()
    try:
        assert entered.wait(5)
        QApplication.processEvents()
        scrollbar = window.table.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        assert scrollbar.maximum() > 0
        assert scrollbar.value() == scrollbar.maximum()
        window.stop()
        release.set()
        deadline = time.monotonic() + 5
        while window.translation_thread is not None and time.monotonic() < deadline:
            window.poll_translation()
            QApplication.processEvents()
            time.sleep(0.01)
        assert window.translation_thread is None
        assert window.rows[0].tr == "translated"
        assert "stopped" in window.status.text().lower()
    finally:
        release.set()


def test_translation_worker_falls_back_and_reports_quota():
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("insufficient_quota")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    events = queue.Queue()
    app.translation_worker([(0, "text", 1, 1)], client, "English", ["first", "second"], events, threading.Event())
    results = list(events.queue)
    assert ("quota", "first", "insufficient_quota") in results
    assert ("row", 0, "answer", "second") in results
    assert results[-1] == ("finished", "completed")
    assert "\n\nJapanese:\ntext" in calls[-1]["messages"][1]["content"]


def test_second_provider_updates_only_comparison_column(window):
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="comparison"))])
    )))
    window.model2.addItem("example-model")
    window.rows = [app.Row(1, 1, "source", tr="primary")]
    window.refresh()
    window.start_translation(window.rows, client, True, 0)
    deadline = time.monotonic() + 5
    while window.translation_thread is not None and time.monotonic() < deadline:
        window.poll_translation()
        QApplication.processEvents()
        time.sleep(0.01)
    assert window.translation_thread is None
    assert window.rows[0].tr == "primary"
    assert window.rows[0].tr2 == "comparison"
    assert window.table.item(0, 4).text() == "comparison"


def test_optional_second_model_and_exports(window, tmp_path):
    window.rows = [app.Row(1, 1, "source", tr="primary", tr2="comparison")]
    window.refresh()
    assert window.model2.itemText(0) == "---"
    assert window.table.isColumnHidden(4)
    window.write_txt(tmp_path / "one.txt")
    window.write_docx(tmp_path / "one.docx")
    assert (tmp_path / "one.txt").read_text(encoding="utf-8").splitlines() == [
        "Page\tPanel\tRecognised text\tTranslation", "1\t1\tsource\tprimary"
    ]
    assert len(app.Document(tmp_path / "one.docx").tables[0].columns) == 4
    window.set_models2(["model-a", "free-model"])
    window.model2.setCurrentText("model-a")
    assert not window.table.isColumnHidden(4)
    assert "---" not in window.ranked("model-a", window.model2)
    window.write_txt(tmp_path / "two.txt")
    window.write_docx(tmp_path / "two.docx")
    assert (tmp_path / "two.txt").read_text(encoding="utf-8").splitlines()[-1].endswith("\tcomparison")
    assert len(app.Document(tmp_path / "two.docx").tables[0].columns) == 5
    window.free_only2.setChecked(True)
    assert window.second_model_value() == "model-a"
    window.model2.setCurrentText("---")
    assert window.rows[0].tr2 == "comparison"
    assert window.table.isColumnHidden(4)


def test_translate_all_runs_both_selected_models(window, monkeypatch):
    calls = []

    def create(**kwargs):
        calls.append(kwargs["model"])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=kwargs["model"] + " result"))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(window, "client", lambda: client)
    monkeypatch.setattr(window, "client2", lambda: client)
    window.model.addItem("primary")
    window.set_models2(["secondary"])
    window.model2.setCurrentText("secondary")
    window.rows = [app.Row(1, 1, "source")]
    window.recognized = True
    window.refresh()
    window.all()
    deadline = time.monotonic() + 5
    while window.translation_thread is not None and time.monotonic() < deadline:
        window.poll_translation()
        QApplication.processEvents()
        time.sleep(0.01)
    assert window.translation_thread is None
    assert calls == ["primary", "secondary"]
    assert (window.rows[0].tr, window.rows[0].tr2) == ("primary result", "secondary result")


def test_blank_second_model_is_not_called(window, monkeypatch):
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))])
    )))
    monkeypatch.setattr(window, "client", lambda: client)
    monkeypatch.setattr(window, "client2", lambda: pytest.fail("disabled translator was called"))
    window.model.addItem("primary")
    window.rows = [app.Row(1, 1, "source")]
    window.recognized = True
    window.refresh()
    window.all()
    deadline = time.monotonic() + 5
    while window.translation_thread is not None and time.monotonic() < deadline:
        window.poll_translation()
        QApplication.processEvents()
        time.sleep(0.01)
    assert window.rows[0].tr == "answer"
    assert window.rows[0].tr2 == ""


def test_translate_all_retries_missing_second_result_only(window, monkeypatch):
    calls = []

    def create(**kwargs):
        calls.append(kwargs["model"])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="comparison"))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(window, "client", lambda: pytest.fail("completed primary result was retried"))
    monkeypatch.setattr(window, "client2", lambda: client)
    window.model.addItem("primary")
    window.set_models2(["secondary"])
    window.model2.setCurrentText("secondary")
    window.rows = [app.Row(1, 1, "source", tr="already done"), app.Row(1, 2, "held", review="CHECK")]
    window.recognized = True
    window.refresh()
    window.all()
    deadline = time.monotonic() + 5
    while window.translation_thread is not None and time.monotonic() < deadline:
        window.poll_translation()
        QApplication.processEvents()
        time.sleep(0.01)
    assert calls == ["secondary"]
    assert window.rows[0].tr2 == "comparison"
    assert window.rows[1].tr2 == ""


def test_second_model_persists_and_blank_survives_reload(window, monkeypatch):
    monkeypatch.setattr(app, "unprotect", lambda value: value)
    key = app.profile_key("https://example.test/v1")
    window.profiles[key] = {"url": "https://example.test/v1", "api_key": "test-key", "verified": True, "models": ["first", "second"], "model": "first"}
    window.refresh_provider_list()
    window.provider2.setCurrentIndex(window.provider2.findData(key))
    window.on_provider_chosen2(window.provider2.currentIndex())
    assert window.model2.currentText() == "---"
    window.model2.setCurrentText("second")
    window.save()
    other = app.Window()
    try:
        assert other.second_provider_key == key
        assert other.second_model_value() == "second"
        other.model2.setCurrentText("---")
        other.save()
    finally:
        other.close()
    restored = app.Window()
    try:
        assert restored.second_provider_key == key
        assert restored.model2.currentText() == "---"
    finally:
        restored.close()


def test_current_verified_provider_defaults_to_optional_second(window, monkeypatch):
    monkeypatch.setattr(app, "unprotect", lambda value: value)
    url = "https://example.test/v1"
    key = app.profile_key(url)
    window.url.setText(url)
    window.profiles[key] = {"url": url, "api_key": "test-key", "verified": True, "models": ["first", "second"], "model": "first"}
    window.refresh_provider_list()
    assert window.second_provider_key == key
    assert window.model2.currentText() == "---"
    assert window.model2.findText("second") >= 0
    assert window.model2.isEnabled()


def test_same_provider_requires_distinct_models(window, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    window.connected_url = "https://example.test/v1"
    window.second_provider_key = app.profile_key(window.connected_url)
    window.model.addItems(["primary", "secondary", "alternate"])
    window.model_cache2 = ["primary", "secondary", "alternate"]
    window.set_models2(window.model_cache2)
    assert window.model2.findText("primary") == -1
    window.model2.setCurrentText("secondary")
    assert window.ranked("primary", window.model) == ["primary", "alternate"]
    assert window.ranked("secondary", window.model2) == ["secondary", "alternate"]
    window.model.setCurrentText("secondary")
    assert window.duplicate_translator_models()
    window.paths = ["page1.png"]
    monkeypatch.setattr(window, "ocr", lambda *args, **kwargs: pytest.fail("OCR started for duplicate models"))
    window.all()
    assert "different model" in warnings[0][2]
    window.model2.setCurrentText("primary")
    assert not window.duplicate_translator_models()
    window.second_provider_key = app.profile_key("https://other.example/v1")
    window.model2.setCurrentText("secondary")
    assert not window.duplicate_translator_models()


def test_stop_first_translator_does_not_start_second(window, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def create(**kwargs):
        calls.append(kwargs["model"])
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(window, "client", lambda: client)
    monkeypatch.setattr(window, "client2", lambda: client)
    window.model.addItem("primary")
    window.set_models2(["secondary"])
    window.model2.setCurrentText("secondary")
    window.rows = [app.Row(1, 1, "source")]
    window.recognized = True
    window.refresh()
    window.all()
    try:
        assert entered.wait(5)
        window.stop()
        release.set()
        deadline = time.monotonic() + 5
        while window.translation_thread is not None and time.monotonic() < deadline:
            window.poll_translation()
            QApplication.processEvents()
            time.sleep(0.01)
        assert window.translation_thread is None
        assert calls == ["primary"]
        assert window.rows[0].tr == "answer"
        assert window.rows[0].tr2 == ""
    finally:
        release.set()


@pytest.mark.parametrize("enabled", [False, True])
def test_pdf_export_has_correct_columns(window, tmp_path, monkeypatch, enabled):
    from PIL import ImageDraw
    labels = []
    original = ImageDraw.ImageDraw.text

    def capture(self, xy, text, *args, **kwargs):
        labels.append(text)
        return original(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    window.rows = [app.Row(1, 1, "source", tr="primary", tr2="comparison")]
    if enabled:
        window.set_models2(["model"])
        window.model2.setCurrentText("model")
    window.write_pdf(tmp_path / "output.pdf")
    assert (tmp_path / "output.pdf").read_bytes().startswith(b"%PDF")
    assert ("TRANSLATION 2" in labels) == enabled
    assert ("comparison" in labels) == enabled


@pytest.mark.skipif(os.getenv("BLUETL_REAL_OCR") != "1", reason="requires local OCR models")
def test_real_ocr_process_and_gui_event_loop(window, monkeypatch):
    psutil = pytest.importorskip("psutil")
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: errors.append(args))
    sample = app.Path(importlib.util.find_spec("manga_ocr").origin).parent / "assets" / "example.jpg"
    window.paths = [str(sample)]
    parent = psutil.Process()
    before = parent.memory_info().rss
    window.ocr()
    process = window.ocr_process
    child = psutil.Process(process.pid)
    peak = []
    loop = QEventLoop()
    heartbeat = []
    timer = QTimer()
    timer.setInterval(100)
    timer.timeout.connect(lambda: heartbeat.append(1))
    def sample_memory():
        try:
            peak.append(child.memory_info().rss)
        except psutil.NoSuchProcess:
            pass
    timer.timeout.connect(sample_memory)
    timer.start()
    check = QTimer()
    check.setInterval(100)
    check.timeout.connect(lambda: loop.quit() if window.ocr_process is None else None)
    check.start()
    QTimer.singleShot(300000, loop.quit)
    loop.exec()
    if window.ocr_process is not None:
        window.ocr_process.terminate()
        window.ocr_process.join()
        window.poll_ocr()
        pytest.fail("OCR timed out")
    assert not errors, errors
    assert process.exitcode == 0
    assert len(heartbeat) > 5
    assert window.recognized
    assert window.rows
    print(f"OCR memory: parent before={before // 1048576} MiB, parent after={parent.memory_info().rss // 1048576} MiB, child peak={max(peak) // 1048576} MiB")
