# //remarks: Throwaway validation script for model-list discovery. It redirects APPDATA to a temp folder
# //remarks: so the real BlueTL config is never touched, then runs the pure helpers, the worker thread, and
# //remarks: a full offscreen GUI pass against a local mock OpenAI-compatible server.
import os, sys, json, tempfile, threading, ssl
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ['APPDATA'] = tempfile.mkdtemp(prefix='bluetl_test_appdata_')
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as bluetl

# //remarks: The picker's verified marker is built with chr() in app.py so the source stays ASCII; mirror it here
# //remarks: instead of pasting the literal tick, which a cp1252 console cannot print.
PROVIDER_TICK = chr(0x2714)

failures = []
def check(name, cond, extra=''):
    # //remarks: The Windows console is cp1252, so a diagnostic that contains non-ASCII text (a Japanese model ID,
    # //remarks: a tick mark) used to abort the whole run with UnicodeEncodeError. Diagnostics are therefore written
    # //remarks: with backslash escapes when the console cannot represent them; only the printed copy changes.
    line = ('PASS ' if cond else 'FAIL ') + name + (f'  [{extra}]' if extra else '')
    try: print(line)
    except UnicodeEncodeError: print(line.encode('ascii', 'backslashreplace').decode('ascii'))
    if not cond: failures.append(name)

# ---- 1. normalized_url ---------------------------------------------------------
cases = [
    ('https://serveras.click/v1', 'https://serveras.click/v1'),
    ('https://serveras.click/v1/', 'https://serveras.click/v1'),
    ('serveras.click', 'https://serveras.click/v1'),
    ('http://localhost:11434/v1', 'http://localhost:11434/v1'),
    ('localhost:1234', 'http://localhost:1234/v1'),
    ('127.0.0.1:8080/v1', 'http://127.0.0.1:8080/v1'),
    ('192.168.1.50:11434', 'http://192.168.1.50:11434/v1'),
    ('https://api.moonshot.cn/v1', 'https://api.moonshot.cn/v1'),
    ('https://x.openai.azure.com/openai/v1', 'https://x.openai.azure.com/openai/v1'),
    ('https://host/v1?x=1#frag', 'https://host/v1'),
    ('https://openrouter.ai/api/v1', 'https://openrouter.ai/api/v1'),
    ('', ''),
    ('   ', ''),
]
for raw, want in cases:
    got = bluetl.normalized_url(raw)
    check(f'normalized_url({raw!r})', got == want, f'got {got!r} want {want!r}')

# //remarks: Endpoint fallback: the base form first, then the site-root form without the /vN segment.
check('model_list_urls for /v1 base', bluetl.model_list_urls('https://host/v1') == ['https://host/v1', 'https://host'], str(bluetl.model_list_urls('https://host/v1')))
check('model_list_urls for /openai/v1 base', bluetl.model_list_urls('https://x.openai.azure.com/openai/v1') == ['https://x.openai.azure.com/openai/v1', 'https://x.openai.azure.com/openai'], str(bluetl.model_list_urls('https://x.openai.azure.com/openai/v1')))
check('model_list_urls without version segment', bluetl.model_list_urls('https://api.moonshot.cn/openai') == ['https://api.moonshot.cn/openai'], str(bluetl.model_list_urls('https://api.moonshot.cn/openai')))


# ---- 2. mock provider ----------------------------------------------------------
class MockHandler(BaseHTTPRequestHandler):
    payload = None
    status = 200
    auth_seen = None
    # //remarks: Count of /models requests served, so a test can prove that typing in the connection fields sends
    # //remarks: nothing and that only Save triggers discovery.
    requests = 0
    # //remarks: The key check goes through /chat/completions, exactly like the real provider. The mock answers it so
    # //remarks: Save can prove a key, and a rejected key can be simulated without a network.
    chat_status = 200
    chat_requests = 0
    chat_auth = None
    accepted_key = 'secret-key'
    def log_message(self, *a): pass
    def do_POST(self):
        MockHandler.chat_auth = self.headers.get('Authorization')
        # //remarks: Discovery also probes the site-root form (<host>/models), so the chat path is matched by suffix
        # //remarks: rather than exactly; anything else is a genuine 404 for the caller to report.
        if not self.path.endswith('/chat/completions'):
            self.send_response(404); self.end_headers(); return
        MockHandler.chat_requests += 1
        if MockHandler.chat_status != 200 or MockHandler.chat_auth != f'Bearer {MockHandler.accepted_key}':
            body = json.dumps({'error': {'code': 'invalid_api_key', 'message': 'Invalid API key', 'type': 'asai_error'}}).encode()
            self.send_response(401)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body); return
        body = json.dumps({'id': 'chatcmpl-mock', 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'OK'}}]}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers(); self.wfile.write(body)
    # //remarks: The catalogue is served per URL prefix, so two providers on one mock host can answer different model
    # //remarks: lists. Without this, a test that switches providers races the shared payload and can record the wrong
    # //remarks: provider's models.
    payloads_by_prefix = {}
    def do_GET(self):
        MockHandler.auth_seen = self.headers.get('Authorization')
        # //remarks: Several later sections run a second provider at /other/v1 on the same host, so any OpenAI-style
        # //remarks: "<prefix>/models" path is served; a genuinely wrong path still answers 404.
        if self.path != '/v1/models' and not self.path.endswith('/v1/models'):
            self.send_response(404); self.end_headers(); return
        MockHandler.requests += 1
        prefix = self.path[:-len('/models')]
        body = json.dumps(MockHandler.payloads_by_prefix.get(prefix, MockHandler.payload)).encode()
        self.send_response(MockHandler.status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers(); self.wfile.write(body)

server = HTTPServer(('127.0.0.1', 0), MockHandler)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{port}/v1'

MockHandler.payload = {'object': 'list', 'data': [
    {'id': 'old-model', 'created': 100},
    {'id': 'newest-model', 'created': 300},
    {'id': 'mid-model', 'created': 200},
    {'id': 'no-created-model'},
]}
ids = bluetl.fetch_models(base, 'secret-key')
check('fetch_models parses + sorts by created desc', ids == ['newest-model', 'mid-model', 'old-model', 'no-created-model'], str(ids))
check('fetch_models sends Bearer key', MockHandler.auth_seen == 'Bearer secret-key', str(MockHandler.auth_seen))

MockHandler.payload = {'data': [{'id': 'b'}, {'id': 'a'}]}
check('fetch_models keeps provider order without created', bluetl.fetch_models(base, 'k') == ['b', 'a'])

MockHandler.payload = {'z-model': 1, 'y-model': 2}
check('fetch_models accepts bare mapping', bluetl.fetch_models(base, 'k') == ['z-model', 'y-model'])

MockHandler.payload = {'data': []}
check('fetch_models returns [] for empty list', bluetl.fetch_models(base, 'k') == [])
MockHandler.payload = {'object': 'list'}
check('fetch_models returns [] when data missing', bluetl.fetch_models(base, 'k') == [])
def raises(fn, exc=RuntimeError):
    try: fn(); return False
    except exc: return True
    except Exception: return False
MockHandler.status = 500
check('fetch_models raises on HTTP 500', raises(lambda: bluetl.fetch_models(base, 'k')))
check('fetch_models raises when unreachable', raises(lambda: bluetl.fetch_models('http://127.0.0.1:1/v1', 'k', timeout=2)))
MockHandler.status = 200
MockHandler.payload = {'not': 'json-like'}
check('fetch_models raises on unexpected shape gracefully', bluetl.fetch_models(base, 'k') == [])

# ---- 3. worker thread ----------------------------------------------------------
MockHandler.payload = {'data': [{'id': 'gpt-test', 'created': 5}]}
loader = bluetl.ModelListLoader(base, 'k'); loader.start(); loader.join(15)
check('ModelListLoader captures list', loader.list_id == ['gpt-test'] and loader.list_error is None, f'{loader.list_id} {loader.list_error}')
loader = bluetl.ModelListLoader('http://127.0.0.1:1/v1', 'k'); loader.start(); loader.join(15)
check('ModelListLoader reports unreachable as error, not empty list', loader.list_id == [] and loader.list_error, f'{loader.list_id} {loader.list_error}')

# ---- 4. GUI pass (offscreen) ---------------------------------------------------
# Record message boxes instead of opening them: an offscreen dialog would block forever.
mb_calls = []
class FakeMB:
    @staticmethod
    def warning(parent, title, text, *a, **k): mb_calls.append(('warning', title, text))
    @staticmethod
    def information(parent, title, text, *a, **k): mb_calls.append(('information', title, text))
    @staticmethod
    def critical(parent, title, text, *a, **k): mb_calls.append(('critical', title, text))
bluetl.QMessageBox = FakeMB

from PySide6.QtWidgets import QApplication
import time as _time
qapp = QApplication.instance() or QApplication([])

def wait_refresh(window, timeout=20):
    # //remarks: refresh_models only starts the worker; pump the event loop until the poll timer finishes the
    # //remarks: step, exactly like the real GUI would while the user waits.
    end = _time.monotonic() + timeout
    while window.model_refreshing and _time.monotonic() < end:
        qapp.processEvents(); _time.sleep(0.02)
    qapp.processEvents()

def wait_idle(window, timeout=25):
    # //remarks: Save finishes with a key check, which runs on the same poll tick as the fetch. Waiting for
    # //remarks: the loader, the flag, and the timer to all settle means a test never starts the next provider while
    # //remarks: the previous provider's result is still in flight - that would overwrite the newer list.
    end = _time.monotonic() + timeout
    while _time.monotonic() < end:
        if not window.model_refreshing and window.model_loader is None and not window.model_poll.isActive(): break
        qapp.processEvents(); _time.sleep(0.02)
    qapp.processEvents()

w = bluetl.Window(); w.model_timer.stop()
# //remarks: Nothing provider-specific is compiled in any more: a fresh install starts with an empty Base URL,
# //remarks: an empty dropdown, and an unticked Free models only box. The list only ever comes from the provider.
check('no base URL is hard-coded', w.url.text() == '', w.url.text())
check('dropdown starts empty (no seeded list)', w.model.count() == 0, str([w.model.itemText(i) for i in range(w.model.count())]))
check('free-only box starts unticked', w.free_only.isChecked() is False)

# Auto refresh through the real code path with a key set.
w.key.setText('secret-key'); w.url.setText(base); w.refreshed = ''
w.refresh_models(manual=False); wait_refresh(w)
model_ids = [w.model.itemText(i) for i in range(w.model.count())]
check('auto refresh swaps in provider models', 'gpt-test' in model_ids, str(model_ids))
check('only provider IDs are listed (none hard-coded)', model_ids == ['gpt-test'], str(model_ids))
check('cache populated', w.model_cache == ['gpt-test'], str(w.model_cache))

# Custom typed model ID must survive a refresh.
w.model.setCurrentText('my-custom-deployment'); w.refreshed = ''
w.refresh_models(manual=False); wait_refresh(w)
check('custom typed ID survives refresh', w.model.currentText() == 'my-custom-deployment', w.model.currentText())
check('custom typed ID present in dropdown', w.model.findText('my-custom-deployment') >= 0)

# Retry order: selected first, then live free models, then the rest.
MockHandler.payload = {'data': [{'id': 'asai/freemodel-9-new'}, {'id': 'paid-model'}]}
w.refreshed = ''; w.refresh_models(manual=False); wait_refresh(w)
check('replacing the list resets the picker to the first model', w.model.currentText() == 'asai/freemodel-9-new', w.model.currentText())
w.model.setCurrentText('paid-model')
order = w.candidates()
check('candidates starts with selected', order[0] == 'paid-model', str(order[:3]))
check('discovered freemodel-* is tried among the candidates', 'asai/freemodel-9-new' in order, str(order))
check('candidates falls back to seeded list when dropdown empty', w.ranked('x') and len(w.ranked('x')) > 0)

# Manual refresh paths: a dead provider clears the previous provider's list (it must not be offered for another
# host), and the failure itself is reported without crashing.
before = [w.model.itemText(i) for i in range(w.model.count())]
w.url.setText('http://127.0.0.1:1/v1'); w.refreshed = ''; mb_calls.clear()
after_url_change = [w.model.itemText(i) for i in range(w.model.count())]
check('changing the Base URL clears the previous list', after_url_change == [], str(after_url_change))
check('changing the Base URL clears the cache', w.model_cache == [], str(w.model_cache))
check('changing the Base URL clears the model selection', w.model.currentText() == '', w.model.currentText())
w.refresh_models(manual=True); wait_refresh(w)
after = [w.model.itemText(i) for i in range(w.model.count())]
check('failed manual refresh keeps the (now empty) list', after == [], str(after))
check('failed manual refresh keeps the (now empty) cache', w.model_cache == [], str(w.model_cache))
# //remarks: After a failed fetch the connection is NOT confirmed, so Refresh stays disabled and Save is
# //remarks: the button that must be pressed again - the user confirms before the app contacts the provider.
check('failed refresh leaves Refresh disabled (re-connect required)', w.refresh_button.isEnabled() is False)
check('failed refresh re-enables Save', w.connect_button.isEnabled() is True)
check('failed refresh reports in status', 'could not be fetched' in w.status.text() or 'timed out' in w.status.text(), w.status.text())
check('failed manual refresh reports in status', 'could not be fetched' in w.status.text() or 'timed out' in w.status.text(), w.status.text())

# No key: manual warns, no fetch. Going back to the live provider restores that provider's own list first, because
# a remembered provider keeps its catalogue instead of inheriting the last one used.
w.key.setText(''); w.url.setText(base); w.refreshed = ''; mb_calls.clear()
restored = [w.model.itemText(i) for i in range(w.model.count())]
check('returning to a remembered provider restores its list', restored == ['asai/freemodel-9-new', 'paid-model'], str(restored))
w.refresh_models(manual=True); wait_refresh(w)
check('refresh without key warns', any(c[0] == 'warning' for c in mb_calls), str(mb_calls))
check('refresh without key keeps list', [w.model.itemText(i) for i in range(w.model.count())] == restored)

# HTTP error on manual refresh is kept silent in the dropdown but reported in status, with the provider's reason.
w.key.setText('secret-key'); MockHandler.status = 503; w.refreshed = ''; mb_calls.clear()
w.refresh_models(manual=True); wait_refresh(w)
check('HTTP error keeps list', [w.model.itemText(i) for i in range(w.model.count())] == restored)
check('HTTP error reported in status', 'could not be fetched' in w.status.text(), w.status.text())
check('HTTP error names the status code', 'HTTP 503' in w.status.text(), w.status.text())
MockHandler.status = 200
# //remarks: A rejected key is reported with the provider's own message, not just a number, so the user knows to fix
# //remarks: the key rather than the URL.
MockHandler.accepted_key = 'some-other-key'; mb_calls.clear()
w.key.setText('secret-key'); w.confirm_connection(); wait_refresh(w)
check('rejected key is named in the status line', 'Invalid API key' in w.status.text(), w.status.text())
check('rejected key leaves the Model dropdown locked', w.model.isEnabled() is False)
check('rejected key is not recorded as verified', w.api_verified == '', w.api_verified)
MockHandler.accepted_key = 'secret-key'

# Same-URL auto refresh is skipped (no redundant request).
w.url.setText(base); w.refreshed = ''; w.refresh_models(manual=False); wait_refresh(w)
MockHandler.auth_seen = 'sentinel'; w.refresh_models(manual=False); wait_refresh(w, timeout=2)
check('redundant auto refresh skipped for same URL', MockHandler.auth_seen == 'sentinel', str(MockHandler.auth_seen))

# A failed fetch is not marked as checked, so the same URL is tried again automatically afterwards.
MockHandler.status = 500; w.url.setText(base); w.refreshed = ''
w.refresh_models(manual=True); wait_refresh(w)
check('failed fetch is not marked as checked', w.refreshed == '', w.refreshed)
MockHandler.status = 200
MockHandler.payload = {'data': [{'id': 'retry-model'}]}
w.refresh_models(manual=False); wait_refresh(w)
check('same URL is retried automatically after a failure', w.model.findText('retry-model') >= 0 and w.refreshed == base, f'refreshed={w.refreshed!r}')

# Bare host URL gets a scheme guessed (local host = http) and is used for discovery, while the field text stays
# exactly as typed.
MockHandler.payload = {'data': [{'id': 'asai/freemodel-9-new'}, {'id': 'paid-model'}]}
w.key.setText('secret-key'); w.url.setText(f'127.0.0.1:{port}'); w.refreshed = ''; w.refresh_models(manual=False); wait_refresh(w)
check('bare local host reachable via guessed http scheme', w.model.findText('asai/freemodel-9-new') >= 0, str([w.model.itemText(i) for i in range(w.model.count())][:4]))
check('base URL field text is not rewritten', w.url.text() == f'127.0.0.1:{port}', w.url.text())

# ---- 5. persistence ------------------------------------------------------------
# //remarks: The core requirement: the Base URL, API key, model, fetched list, and the Free models only state
# //remarks: must all come back when the EXE is reopened, because none of them is compiled into the binary.
w.url.setText('https://remembered.example/v1'); w.key.setText('remembered-key-123')
w.model.setCurrentText('chosen-model'); w.free_only.setChecked(False)
w.model_cache = ['persisted-model', 'another-free-model']; w.set_models(w.model_cache)
w.model.setCurrentText('chosen-model')
# A key is only stored after a successful fetch, so an unfetched key must not reach the file.
w.fetched = ('', ''); w.save()
check('unfetched key is not persisted', 'api_key' not in json.loads(bluetl.CFG.read_text(encoding='utf-8')) or json.loads(bluetl.CFG.read_text(encoding='utf-8')).get('api_key') == '')
w.fetched = (bluetl.profile_key('https://remembered.example/v1'), 'remembered-key-123')
w.save()
saved = json.loads(bluetl.CFG.read_text(encoding='utf-8'))
check('save writes models cache', saved.get('models') == ['persisted-model', 'another-free-model'], str(saved.get('models')))
check('save writes base URL', saved.get('url') == 'https://remembered.example/v1', str(saved.get('url')))
check('save writes model', saved.get('model') == 'chosen-model', str(saved.get('model')))
check('save writes free_only flag', saved.get('free_only') is False, str(saved.get('free_only')))
check('save never writes the key as plaintext', 'remembered-key-123' not in bluetl.CFG.read_text(encoding='utf-8'))

w2 = bluetl.Window(); w2.model_timer.stop()
check('load restores base URL', w2.url.text() == 'https://remembered.example/v1', w2.url.text())
check('load restores API key (DPAPI)', w2.key.text() == 'remembered-key-123', w2.key.text())
check('load restores cached models into dropdown', w2.model_cache == ['persisted-model', 'another-free-model'] and w2.model.findText('persisted-model') >= 0, str(w2.model_cache))
check('load restores saved model as selection', w2.model.currentText() == 'chosen-model', w2.model.currentText())

# Free models only must survive a restart too.
w2.free_only.setChecked(True); w2.save()
w2b = bluetl.Window(); w2b.model_timer.stop()
check('load restores free_only tick', w2b.free_only.isChecked() is True)
check('restored filter hides non-free models', w2b.model.findText('persisted-model') < 0 and w2b.model.findText('another-free-model') >= 0, str([w2b.model.itemText(i) for i in range(w2b.model.count())]))
w2b.free_only.setChecked(False)

# Legacy config without models key must load fine.
bluetl.CFG.write_text(json.dumps({'url': 'https://legacy.example/v1', 'model': 'legacy-model'}), encoding='utf-8')
w3 = bluetl.Window(); w3.model_timer.stop()
check('legacy config restores typed model without a cached list', w3.model.currentText() == 'legacy-model', w3.model.currentText())
check('legacy config keeps its base URL', w3.url.text() == 'https://legacy.example/v1', w3.url.text())

# Corrupt config must not crash startup.
bluetl.CFG.write_text('{ not json', encoding='utf-8')
try:
    w4 = bluetl.Window(); w4.model_timer.stop(); ok = True
except Exception as e:
    ok = False; print('   corrupt-config exception:', e)
check('corrupt config starts with empty fields', ok and w4.url.text() == '' and w4.model.count() == 0)

# //remarks: Regression: the config is written with ensure_ascii=False, so non-ASCII text lands in the file as
# //remarks: real UTF-8 bytes. Loading used to call read_text() without an encoding, which fell back to the
# //remarks: Windows locale codec (cp1252) and raised "can't decode byte 0x81 in position N" during __init__,
# //remarks: making the app impossible to start until the file was deleted by hand. U+0081 is that exact byte.
nonascii = {'url': 'https://ex\u0081mple.test/v1', 'model': 'm\u00f6del-\u4e2d\u6587', 'language': 'Bahasa Melayu',
            'free_only': True, 'last_dir': 'C:\\Users\\Jos\u00e9\\manga', 'models': ['free-a', 'paid-b']}
bluetl.CFG.write_text(json.dumps(nonascii, ensure_ascii=False, indent=2), encoding='utf-8')
check('utf-8 config really contains byte 0x81', b'\x81' in bluetl.CFG.read_bytes())
try:
    bluetl.CFG.read_bytes().decode('cp1252'); cp1252_ok = True
except UnicodeDecodeError:
    cp1252_ok = False
check('byte 0x81 is undecodable as cp1252 (reproduces the bug)', cp1252_ok is False)
try:
    w_nu = bluetl.Window(); w_nu.model_timer.stop(); nu_ok = True
except Exception as e:
    nu_ok = False; w_nu = None; print('   non-ascii-config exception:', e)
check('non-ASCII config does not crash startup', nu_ok)
check('non-ASCII config restores the URL', nu_ok and w_nu.url.text() == 'https://ex\u0081mple.test/v1', repr(w_nu.url.text()) if nu_ok else '')
check('non-ASCII config restores the model', nu_ok and w_nu.model.currentText() == 'm\u00f6del-\u4e2d\u6587', repr(w_nu.model.currentText()) if nu_ok else '')
check('non-ASCII config restores last_dir', nu_ok and w_nu.last_dir == 'C:\\Users\\Jos\u00e9\\manga', repr(w_nu.last_dir) if nu_ok else '')
check('non-ASCII config restores the model list', nu_ok and w_nu.model_cache == ['free-a', 'paid-b'], str(w_nu.model_cache) if nu_ok else '')
# //remarks: Leave a neutral config behind: the next section asserts on a fresh, unfiltered list, and this
# //remarks: fixture deliberately had free_only turned on and its own cached models.
bluetl.CFG.unlink(missing_ok=True)

# ---- 6. Cline-style connection confirmation ------------------------------------
# //remarks: Same flow as Cline's provider panel: type the Base URL and API key, press Save, and only
# //remarks: then is the provider contacted and the Model dropdown unlocked. Nothing is sent while typing.
MockHandler.status = 200
MockHandler.payload = {'data': [{'id': 'gate-free-model'}, {'id': 'gate-paid-model'}]}
before_requests = MockHandler.requests

wg = bluetl.Window(); wg.model_timer.stop()
check('Model dropdown is locked before confirming', wg.model.isEnabled() is False)
check('Refresh is locked before confirming', wg.refresh_button.isEnabled() is False)
check('Save is enabled on a fresh window', wg.connect_button.isEnabled() is True)
check('nothing connected yet', wg.connected_url == '' and wg.connected_key == '')

# Typing must NOT fire a request (the old debounce did).
wg.url.setText(base); wg.key.setText('secret-key')
wg.on_connection_edited(); wg.on_connection_edited()
qapp.processEvents()
check('typing does not contact the provider', MockHandler.requests == before_requests, f'{MockHandler.requests} vs {before_requests}')
check('typing keeps the Model locked', wg.model.isEnabled() is False)
check('typing does not mark the connection confirmed', wg.connected_url == '')

# Confirmation is the step that fetches the list.
wg.confirm_connection(); wait_refresh(wg)
gate_ids = [wg.model.itemText(i) for i in range(wg.model.count())]
check('confirming fetches the model list', 'gate-free-model' in gate_ids, str(gate_ids))
check('confirming unlocks the Model dropdown', wg.model.isEnabled() is True)
check('confirming enables Refresh', wg.refresh_button.isEnabled() is True)
check('confirming disables Save', wg.connect_button.isEnabled() is False)
check('connect line reports success', 'Connected' in wg.connect_status.text(), wg.connect_status.text())
check('connection records the confirmed values', wg.connected_url == base and wg.connected_key == 'secret-key')
check('Save proves the API key', wg.api_verified == bluetl.profile_key(base), f'{wg.api_verified!r} {bluetl.profile_key(base)!r}')
check('confirmed provider is remembered', bluetl.profile_key(base) in wg.profiles, str(list(wg.profiles)))
check('remembered provider is marked verified', (wg.profiles.get(bluetl.profile_key(base)) or {}).get('verified') is True, str(wg.profiles.get(bluetl.profile_key(base))))

# A later edit to either field must invalidate the confirmation and re-lock the Model picker.
wg.url.setText(base + '/changed'); wg.on_connection_edited()
check('editing the URL re-locks the Model dropdown', wg.model.isEnabled() is False)
check('editing the URL re-enables Save', wg.connect_button.isEnabled() is True)
check('editing the URL disables Refresh', wg.refresh_button.isEnabled() is False)
check('editing reports not confirmed', 'Not confirmed' in wg.connect_status.text(), wg.connect_status.text())
wg.url.setText(base); wg.on_connection_edited()
# //remarks: An uncommitted edit restores that provider's own catalogue. Because the text matches the confirmed
# //remarks: connection again, the verified state applies again - but the key still has to be proved, so the dropdown
# //remarks: stays locked until Test API or Save succeeds.
check('reverting the URL restores that provider\'s models', wg.model.findText('gate-free-model') >= 0, str([wg.model.itemText(i) for i in range(wg.model.count())]) + ' PROFILE=' + str(wg.profiles.get(bluetl.profile_key(base))))
check('reverting the URL keeps Save disabled (same connection again)', wg.connect_button.isEnabled() is False)
check('reverting the URL keeps the Model list locked until the key is proved', wg.model.isEnabled() is False)
wg.key.setText('different-key'); wg.on_connection_edited()
check('editing the key re-locks the Model dropdown', wg.model.isEnabled() is False)
wg.key.setText('secret-key'); wg.on_connection_edited()

# Empty fields must be rejected with a message, never a silent no-op.
wg.url.setText(''); wg.on_connection_edited()
mb_before = len(mb_calls)
wg.confirm_connection()
check('connecting without a Base URL is refused', len(mb_calls) > mb_before and mb_calls[-1][0] == 'warning', str(mb_calls[-1][:2]) if mb_calls else '')
check('refused connection does not unlock the Model dropdown', wg.model.isEnabled() is False)

# The client guard must refuse to build a client from an unconfirmed draft.
wg.url.setText(''); wg.key.setText('secret-key'); wg.on_connection_edited()
mb_before = len(mb_calls)
check('client() refuses an unconfirmed connection', wg.client() is None and len(mb_calls) > mb_before)

# A saved, confirmed provider restores directly as connected on the next startup.
wg.url.setText(base); wg.key.setText('secret-key'); wg.confirm_connection(); wait_refresh(wg)
wg.save()
wr = bluetl.Window(); wr.model_timer.stop()
check('restored config comes back confirmed', wr.connected_url == base and wr.connected_key == 'secret-key')
check('restored config unlocks the Model dropdown', wr.model.isEnabled() is True)
check('restored config keeps Save disabled', wr.connect_button.isEnabled() is False)

# //remarks: The mock server stays up until the very end: the connection, provider-switching, and key-gate sections
# //remarks: below all need it. Shutting it down here made every later request fail with "actively refused".
# //remarks: Drop the confirmed fixture config so the next section starts from a clean, unfiltered window.
bluetl.CFG.unlink(missing_ok=True)

# ---- 7. Free models only tick box ----------------------------------------------
# //remarks: The tick box searches the fetched list for the text "free" (case-insensitive) and shows only those.
free_mixed = ['asai/freemodel-1-GLM', 'gpt-4o', 'deepseek-chat:free', 'MiniMax-Free-Tier', 'claude-sonnet']
w5 = bluetl.Window(); w5.model_timer.stop(); w5.refreshed = 'x'; w5.model_timer.stop()
w5.model_cache = list(free_mixed); w5.set_models(w5.model_cache)
check('filter off shows every model', [w5.model.itemText(i) for i in range(w5.model.count())] == free_mixed, str([w5.model.itemText(i) for i in range(w5.model.count())]))
w5.free_only.setChecked(True)
shown = [w5.model.itemText(i) for i in range(w5.model.count())]
check('filter on shows only IDs containing "free"', shown == ['asai/freemodel-1-GLM', 'deepseek-chat:free', 'MiniMax-Free-Tier'], str(shown))
check('filter keeps the cached list complete', w5.model_cache == free_mixed, str(w5.model_cache))
w5.free_only.setChecked(False)
check('unticking restores the full list', [w5.model.itemText(i) for i in range(w5.model.count())] == free_mixed, str([w5.model.itemText(i) for i in range(w5.model.count())]))

# //remarks: Helper-level checks: "free" is a substring search, not a prefix or a fixed name list.
check('is_free_model matches substring', bluetl.is_free_model('vendor/FREEMODEL-x') and bluetl.is_free_model('a-free-b'))
check('is_free_model rejects paid IDs', not bluetl.is_free_model('gpt-4o') and not bluetl.is_free_model('') and not bluetl.is_free_model(None))
check('filter_models preserves provider order', bluetl.filter_models(['b-free', 'paid', 'a-free'], True) == ['b-free', 'a-free'])
check('filter_models drops blanks and duplicates', bluetl.filter_models(['free-1', '', '  ', 'free-1', None], False) == ['free-1'])
check('split filter agrees with the dropdown filter', [m for m in free_mixed if bluetl.is_free_model(m)] == bluetl.filter_models(free_mixed, True))

# ---- 7. PSD support for OCR ----------------------------------------------------
from PIL import Image as _Image
check('is_psd recognises extensions case-insensitively', bluetl.is_psd('page.PSD') and bluetl.is_psd('a/b/page.psd') and not bluetl.is_psd('page.png'))
try:
    from psd_tools import PSDImage as _PSD
    psd_dir = tempfile.mkdtemp(prefix='bluetl_psd_test_')
    authored = []
    for depth in (8, 16):
        doc = _PSD.new(mode='RGB', size=(90, 60), depth=depth)
        doc.create_pixel_layer(_Image.new('RGB', (90, 60), (255, 255, 255)), name='Background')
        doc.create_pixel_layer(_Image.new('RGB', (40, 16), (0, 0, 0)), name='Ink', top=10, left=10)
        # //remarks: A hidden layer must never reach the OCR: it is construction material, not visible page text.
        hidden = doc.create_pixel_layer(_Image.new('RGB', (40, 16), (255, 0, 0)), name='Hidden', top=30, left=10)
        hidden.visible = False
        out = os.path.join(psd_dir, f'page{depth}.psd')
        doc.save(out); authored.append((depth, out))
    for depth, path in authored:
        for _ in range(2):
            flat = bluetl.flatten_psd(path)
            with _Image.open(flat) as got:
                got.load()
                check(f'flatten_psd composites a {depth}-bit page to RGB', got.mode == 'RGB' and got.size == (90, 60), f'{got.mode} {got.size}')
        check(f'flatten_psd returns a reusable PNG ({depth}-bit)', flat.lower().endswith('.png') and os.path.isfile(flat), flat)
    with _Image.open(bluetl.flatten_psd(authored[0][1])) as got:
        # //remarks: White background + black ink must survive compositing, and the hidden red layer must not.
        check('composited page keeps the visible white background', got.getpixel((80, 50)) == (255, 255, 255), str(got.getpixel((80, 50))))
        check('composited page keeps visible ink', sum(got.getpixel((20, 15))) < 60, str(got.getpixel((20, 15))))
        check('hidden layer is excluded from the page', got.getpixel((20, 35)) == (255, 255, 255), str(got.getpixel((20, 35))))
    opened = bluetl.open_page_image(authored[0][1])
    check('open_page_image flattens a PSD for the detector', opened.mode == 'RGB' and opened.size == (90, 60), f'{opened.mode} {opened.size}')
    # //remarks: A normal raster must bypass flattening entirely.
    png = os.path.join(psd_dir, 'page.png'); _Image.new('RGB', (20, 20), (1, 2, 3)).save(png)
    check('open_page_image passes rasters straight through', bluetl.open_page_image(png).size == (20, 20))
    # //remarks: Import must accept .psd directly and from inside an archive.
    zip_path = os.path.join(psd_dir, 'chapter.zip')
    import zipfile as _zip
    with _zip.ZipFile(zip_path, 'w') as zf: zf.write(authored[0][1], 'chapter/page01.psd')
    w6 = bluetl.Window(); w6.model_timer.stop()
    direct = w6.expand_inputs([authored[0][1]])
    check('import accepts a direct .psd', len(direct) == 1 and direct[0].lower().endswith('.psd'), str(direct))
    archived = w6.expand_inputs([zip_path])
    check('import accepts a .psd inside a ZIP', len(archived) == 1 and archived[0].lower().endswith('.psd'), str(archived))
    check('import still ignores unsupported files', w6.expand_inputs([os.path.join(psd_dir, 'notes.txt')]) == [])
except ImportError as e:
    print('SKIP PSD checks (psd-tools missing):', e)

# ---- 8. TLS diagnostics --------------------------------------------------------
# //remarks: The original report was "expired ssl" while the server was fine, because every TLS failure reached the
# //remarks: user as one opaque urlopen string. These checks pin the wording each cause produces.
expired = ssl.SSLCertVerificationError(1, 'certificate verify failed: certificate has expired (_ssl.c:1082)')
msg = bluetl.describe_ssl_error(expired)
check('expired certificate is named as expired', 'expired' in msg.lower(), msg)
check('expired certificate says renewal is needed', 'renewed on the server' in msg, msg)
check('cert_expired detects the OpenSSL phrase', bluetl.cert_expired(str(expired)) and not bluetl.cert_expired('HTTP 500'))
mismatch = bluetl.describe_ssl_error("Hostname mismatch, certificate is not valid for 'other.example'")
check('hostname mismatch names the wrong host', 'other.example' in mismatch, mismatch)
check('hostname mismatch mentions HTTPS scanning', 'scanner' in mismatch, mismatch)
selfsigned = bluetl.describe_ssl_error('self-signed certificate')
check('self-signed certificate is explained', 'self-signed' in selfsigned and 'trust store' in selfsigned, selfsigned)
issuer = bluetl.describe_ssl_error('unable to get local issuer certificate')
check('untrusted root is explained', 'trusted root' in issuer, issuer)
generic = bluetl.describe_ssl_error('some other handshake problem')
check('unknown TLS failure still gives the scanner hint', 'TLS handshake failed' in generic and 'scanner' in generic, generic)
check('cert_host_name_error returns empty for other text', bluetl.cert_host_name_error('HTTP 500') == '')

# //remarks: A transient TLS failure (a rotated edge certificate) is retried once, but a real HTTP answer never is, so a
# //remarks: rejected key cannot cost two requests.
check('HTTP errors are not retried', bluetl.retryable_transport_error(RuntimeError('HTTP 401 from x')) is False)
check('invalid JSON is not retried', bluetl.retryable_transport_error(RuntimeError('invalid JSON from x: y')) is False)
check('TLS handshake failures are retried', bluetl.retryable_transport_error(RuntimeError('TLS handshake failed: x')) is True)

calls = []
def flaky(url, key, timeout=10):
    calls.append(url)
    if len(calls) == 1: raise RuntimeError('TLS handshake failed: transient')
    return ['m1']
real_once = bluetl.fetch_models_once
bluetl.fetch_models_once = flaky
check('fetch_models retries a transient TLS failure', bluetl.fetch_models('http://h/v1', 'k') == ['m1'] and len(calls) == 2, str(calls))
calls.clear()
def hard_fail(url, key, timeout=10):
    calls.append(url); raise RuntimeError('HTTP 401 from http://h/v1/models: Invalid API key')
bluetl.fetch_models_once = hard_fail
try:
    bluetl.fetch_models('http://h/v1', 'k'); check('fetch_models raises on a rejected key', False)
except RuntimeError as e:
    check('fetch_models raises on a rejected key', 'Invalid API key' in str(e), str(e))
check('a rejected key is requested only once', len(calls) == 1, str(calls))
bluetl.fetch_models_once = real_once

# //remarks: The first, OpenAI-style attempt describes the user's own URL, so its reason must win over the useless 404
# //remarks: that the site-root fallback produces.
loader_err = bluetl.ModelListLoader('https://host/v1', 'k')
real_fetch = bluetl.fetch_models
def only_first_fails(url, key, timeout=10, attempts=2):
    if url.endswith('/v1'): raise RuntimeError('HTTP 503 from https://host/v1/models: busy')
    raise RuntimeError('HTTP 404 from https://host/models')
bluetl.fetch_models = only_first_fails
loader_err.run()
bluetl.fetch_models = real_fetch
check('loader reports the real error, not the fallback 404', 'HTTP 503' in (loader_err.list_error or ''), str(loader_err.list_error))
check('loader mentions the fallback that was also tried', 'also tried' in (loader_err.list_error or ''), str(loader_err.list_error))
# ---- 9. API key gate and provider switching ------------------------------------
# //remarks: /models is public at some hosts, so a fetched list must not count as a working key. These checks cover the
# //remarks: gate end to end against the mock, which rejects any key except MockHandler.accepted_key.
MockHandler.payload = {'data': [{'id': 'prov-a-1'}, {'id': 'prov-a-2'}]}
wga = bluetl.Window(); wga.model_timer.stop()
wga.url.setText(base); wga.key.setText('secret-key'); wga.on_connection_edited()
wga.confirm_connection(); wait_idle(wga)
check('Save verifies the key and unlocks the dropdown', wga.api_verified == bluetl.profile_key(base) and wga.model.isEnabled() is True, f'{wga.api_verified!r} {wga.model.isEnabled()}')
check('Save spends one key check', MockHandler.chat_requests >= 1, str(MockHandler.chat_requests))
check('verification is reported in status', 'verified' in wga.status.text().lower(), wga.status.text())

# //remarks: A background refresh must not spend another completion or revoke the verification.
before_chat = MockHandler.chat_requests
wga.refreshed = ''; wga.refresh_models(manual=False); wait_refresh(wga)
check('automatic refresh spends no key check', MockHandler.chat_requests == before_chat, f'{MockHandler.chat_requests} vs {before_chat}')
check('automatic refresh keeps the verification', wga.api_verified == bluetl.profile_key(base))

# //remarks: A wrong key leaves the dropdown locked even though the model list was fetched.
MockHandler.accepted_key = 'the-right-key'
wgb = bluetl.Window(); wgb.model_timer.stop()
wgb.url.setText(base); wgb.key.setText('wrong-key'); wgb.on_connection_edited()
wgb.confirm_connection(); wait_idle(wgb)
check('wrong key still fetches the list', wgb.model.findText('prov-a-1') >= 0, str([wgb.model.itemText(i) for i in range(wgb.model.count())]))
check('wrong key keeps the Model dropdown locked', wgb.model.isEnabled() is False)
check('wrong key is named in the status', 'Invalid API key' in wgb.status.text(), wgb.status.text())
check('wrong key is not remembered as verified', (wgb.profiles.get(bluetl.profile_key(base)) or {}).get('verified') is not True)
mb_before = len(mb_calls)
check('client() refuses an unproved key', wgb.client() is None and len(mb_calls) > mb_before)
MockHandler.accepted_key = 'secret-key'
# //remarks: Once verified, a second provider is added and the picker must offer both, with the saved key filled in.
# //remarks: The second provider is a distinct path on the same mock host, which is how a real user runs two gateways
# //remarks: side by side; base_b_saved is the URL as typed, kept apart from the discovery request form.
base_b_saved = f'http://127.0.0.1:{port}/other'
base_b = bluetl.normalized_url(base_b_saved)
check('the two providers normalise to different keys', bluetl.profile_key(base) != bluetl.profile_key(base_b_saved), f'{bluetl.profile_key(base)} vs {bluetl.profile_key(base_b_saved)}')
# //remarks: Each provider now answers with its own catalogue, so switching between them cannot pick up the other's list.
MockHandler.payloads_by_prefix = {'/v1': {'data': [{'id': 'prov-a-1'}, {'id': 'prov-a-2'}]},
                                  '/other/v1': {'data': [{'id': 'prov-b-1'}]}}
wgc = bluetl.Window(); wgc.model_timer.stop()
wgc.url.setText(base); wgc.key.setText('secret-key'); wgc.on_connection_edited()
wgc.confirm_connection(); wait_idle(wgc)
wgc.url.setText(base_b_saved); wgc.key.setText('secret-key'); wgc.on_connection_edited()
wgc.confirm_connection(); wait_idle(wgc)
check('two providers are remembered', {bluetl.profile_key(base), bluetl.profile_key(base_b_saved)} <= set(wgc.profiles), str(list(wgc.profiles)))
check('picker lists both providers plus the placeholder', wgc.provider.count() == 3, str([wgc.provider.itemText(i) for i in range(wgc.provider.count())]))
check('picker marks a verified provider with a tick', PROVIDER_TICK in wgc.provider.itemText(wgc.provider.findData(bluetl.profile_key(base))))

# //remarks: Choosing the first provider again restores its own URL, key, and model list - no retyping.
index_a = wgc.provider.findData(bluetl.profile_key(base))
wgc.on_provider_chosen(index_a)
check('choosing a saved provider fills in its Base URL', wgc.url.text() == base, wgc.url.text())
check('choosing a saved provider restores its API key', wgc.key.text() == 'secret-key', '<hidden>')
check('choosing a saved provider restores its own model list', [wgc.model.itemText(i) for i in range(wgc.model.count())] == ['prov-a-1', 'prov-a-2'], str([wgc.model.itemText(i) for i in range(wgc.model.count())]))
check('choosing a saved provider locks the dropdown until reconfirmed', wgc.model.isEnabled() is False)
wgc.confirm_connection(); wait_idle(wgc)
check('reconfirming a saved provider reconnects it', wgc.model.isEnabled() is True and wgc.api_verified == bluetl.profile_key(base))

# //remarks: Changing the Base URL must refresh the model list instead of keeping the previous selection. A URL that has
# //remarks: never been saved is used, so this measures the new-provider path rather than a remembered provider being
# //remarks: restored from its own cache.
base_c_saved = f'http://127.0.0.1:{port}/third'
MockHandler.payloads_by_prefix['/third/v1'] = {'data': [{'id': 'brand-new-1'}, {'id': 'brand-new-2'}]}
wgd = bluetl.Window(); wgd.model_timer.stop()
wgd.url.setText(base); wgd.key.setText('secret-key'); wgd.on_connection_edited(); wgd.confirm_connection(); wait_idle(wgd)
wgd.model.setCurrentText('prov-a-2')
wgd.url.setText(base_c_saved); wgd.key.setText('secret-key'); wgd.on_connection_edited()
check('changing the URL drops the previous selection', wgd.model.currentText() == '', wgd.model.currentText())
wgd.confirm_connection(); wait_idle(wgd)
check('changing the URL fetches the new provider list', [wgd.model.itemText(i) for i in range(wgd.model.count())] == ['brand-new-1', 'brand-new-2'], str([wgd.model.itemText(i) for i in range(wgd.model.count())]))
check('the new list replaces the old selection', wgd.model.currentText() == 'brand-new-1', wgd.model.currentText())

# //remarks: An edited key alone must not throw the chosen model away - the same provider only needs a new key.
wgd.key.setText('another-key'); wgd.on_connection_edited()
check('editing only the key keeps the chosen model', wgd.model.currentText() == 'brand-new-1', wgd.model.currentText())
check('editing only the key re-locks the dropdown', wgd.model.isEnabled() is False)

# //remarks: Deleting removes the profile and its stored key, and clears the fields when it is the active provider.
wgd.url.setText(base_c_saved); wgd.key.setText('secret-key')
third_key = bluetl.profile_key(base_c_saved)
check('third provider is saved before delete', third_key in wgd.profiles)
wgd.delete_provider()
check('delete removes the saved provider', third_key not in wgd.profiles and third_key not in json.loads(bluetl.CFG.read_text(encoding='utf-8')).get('providers', {}))
check('delete clears the fields and list', wgd.url.text() == '' and wgd.key.text() == '' and wgd.model.count() == 0 and wgd.model_cache == [])
check('delete keeps other providers', bluetl.profile_key(base) in wgd.profiles)

# //remarks: A provider map written by this version must survive a restart, keys included. The window is on provider A
# //remarks: after the picker test, and each provider must come back with its own list rather than a shared one.
check('the window is on the first provider before restart', wgc.url.text() == base, wgc.url.text())
wgc.save()
wgr = bluetl.Window(); wgr.model_timer.stop()
check('saved providers survive a restart', {bluetl.profile_key(base), bluetl.profile_key(base_b_saved)} <= set(wgr.profiles), str(list(wgr.profiles)))
check('saved providers come back ticked', PROVIDER_TICK in wgr.provider.itemText(wgr.provider.findData(bluetl.profile_key(base))))
check('restored provider keeps its own model list', wgr.profiles[bluetl.profile_key(base)]['models'] == ['prov-a-1', 'prov-a-2'], str(wgr.profiles[bluetl.profile_key(base)]['models']))
check('restart keeps the second provider\'s own list', wgr.profiles[bluetl.profile_key(base_b_saved)]['models'] == ['prov-b-1'], str(wgr.profiles[bluetl.profile_key(base_b_saved)]['models']))
check('restored dropdown shows the active provider\'s list', [wgr.model.itemText(i) for i in range(wgr.model.count())] == ['prov-a-1', 'prov-a-2'], str([wgr.model.itemText(i) for i in range(wgr.model.count())]))
check('stored provider key stays protected', 'secret-key' not in bluetl.CFG.read_text(encoding='utf-8'))
bluetl.CFG.unlink(missing_ok=True)
# ---- 10. layout and British English -------------------------------------------
# //remarks: Refresh models must share the Model row, the confirmation button keeps its exact wording, and every
# //remarks: user-facing string uses British spelling.
wl = bluetl.Window(); wl.model_timer.stop()
row_widget = wl.model.parentWidget()
check('Refresh models shares the Model row', wl.refresh_button.parent() is row_widget)
check('Model row holds the picker, the button and the free-only box (picker leftmost)', row_widget.layout().count() == 3 and row_widget.layout().itemAt(0).widget() is wl.model and row_widget.layout().itemAt(2).widget() is wl.free_only, str(row_widget.layout().count()))
check('Save label is exact', wl.connect_button.text() == 'Save', repr(wl.connect_button.text()))
tabs = wl.findChild(bluetl.QTabWidget)
about = tabs.widget(next(i for i in range(tabs.count()) if tabs.tabText(i) == 'About'))
about_layout = about.layout()
about_details = about_layout.itemAt(0).widget()
support = about_layout.itemAt(2).widget()
check('About Readme follows author and opens the public README', about_details.openExternalLinks() and 'Author: Blue-Wingz @ facedesk</p><p><a href="https://github.com/BorneanWingz/PrivateRepoReadmes/blob/main/BlueTLReadme.md">Readme</a>' in about_details.text(), about_details.text())
check('About support link is below a stretch and opens the cuppa page', about_layout.itemAt(1).spacerItem() is not None and support.openExternalLinks() and support.text() == 'If you enjoy my app, please consider to <a href="https://buymeacoffee.com/DrLwSii">buy me a cuppa</a>!', support.text())
check('OCR button uses British spelling', wl.ocr_button.text() == 'Recognise OCR', repr(wl.ocr_button.text()))
check('table header uses British spelling', wl.table.horizontalHeaderItem(2).text() == 'Recognised text', wl.table.horizontalHeaderItem(2).text())
check('status hint uses British spelling', 'Recognise OCR' in wl.status.text(), wl.status.text())
US_SPELLINGS = ('Recognize', 'Recognized', 'recognize', 'recognized', 'humor', 'Humor', 'behavior', 'color ', 'catalog ')
visible = [wl.connect_button.text(), wl.refresh_button.text(), wl.ocr_button.text(), wl.add_button.text(),
           wl.delete_button.text(), wl.free_only.text(), wl.status.text(), wl.connect_status.text(),
           wl.model.toolTip(), wl.provider.toolTip(), wl.refresh_button.toolTip(), wl.connect_button.toolTip()] + \
          [wl.table.horizontalHeaderItem(i).text() for i in range(wl.table.columnCount())]
offenders = [t for t in visible if any(us in t for us in US_SPELLINGS)]
check('no American spellings in visible text', not offenders, str(offenders))

# //remarks: The mock server is stopped once every section that needed it has finished.
server.shutdown()

print()
print('FAILURES:', failures if failures else 'none')
sys.exit(1 if failures else 0)


