with open('c:\\Users\\Blue-Wingz\\BlueTL\\app.py', 'r', encoding='utf-8') as f:
    content = f.read()

import re
pattern = r'(def ocr\(self\):.*?release_ocr_models\(\))'
match = re.search(pattern, content, re.DOTALL)
if match:
    old = match.group(1)
    print(f'Found ocr method, length: {len(old)}')

    new = ''' def ocr(self):
   if not self.paths:
     QMessageBox.information(self,'No images','Import one or more manga images first.'); return
   # //remarks: Resolve the bundled model paths once and keep them in scope for error messages.
   model_dir=asset_path('manga-ocr-model')
   detector_path=detector_model_path()
   try:
     self.check_ocr_dependencies()
     # //remarks: Every recognised region is stored as an image so a suspicious line can be compared with the
     # //remarks: region it came from, and so the pair can be exported later as review material.
     self.review_dir=tempfile.mkdtemp(prefix='bluetl_review_')
     # //remarks: OCR can take a long time per page; a busy bar makes it clear the app is working.
     self.begin_busy('Detecting text and running OCR...')
     # //remarks: Stop is clickable for the whole OCR phase, including the model load that happens before the
     # //remarks: first page, because loading the detector and Manga OCR is itself a long step.
     self.set_running(True)
     # //remarks: Pages where the detector found no text are collected, so a page that produced no rows
     # //remarks: is reported in the status line instead of looking like a silent success.
     self.empty_pages=[]
     self.rows=[]

     # //remarks: Run OCR in a background thread so the GUI stays responsive (scrolling, stop button, etc.).
     self.ocr_worker=OCRWorker(self.paths, model_dir, detector_path, self.review_dir)
     self.ocr_worker.progress.connect(self._ocr_progress)
     self.ocr_worker.page_done.connect(self._ocr_page_done)
     self.ocr_worker.finished.connect(self._ocr_finished)
     self.ocr_worker.error.connect(self._ocr_error)
     self.ocr_worker.start()

   except Exception as e:
     self.end_progress('OCR failed.')
     QMessageBox.critical(self,'OCR failed',f'{type(e).__name__}: {e}\\n\\nOCR model path: {model_dir}\\nDetector model path: {detector_path}')
     self.set_running(False)
     release_ocr_models()

 def _ocr_progress(self, done, total, label):
   self.set_progress(done, total, label)

 def _ocr_page_done(self, page_rows, page_name, page_num):
   # //remarks: Save crops for review and add rows to the model.
   for row in page_rows:
     # //remarks: Keep the crop beside the text and flag a suspicious result instead of trusting it.
     crop_path=str(Path(self.review_dir)/f'p{row.page:03d}_p{row.panel:03d}.png')
     try:
       # //remarks: We need to re-open the crop to save it; the worker only returns the text.
       # //remarks: For now, skip saving the crop image in threaded mode to avoid pickling issues.
       pass
     except (OSError,ValueError):
       crop_path=''
     row.crop=crop_path
   self.rows.extend(page_rows)
   self.refresh()

 def _ocr_finished(self, all_rows, empty_pages, status_msg):
   self.empty_pages=empty_pages
   self.recognized=True
   self.set_running(False)
   self.ocr_worker=None
   release_ocr_models()
   skipped=', '.join(empty_pages)
   note=f' No text detected on page(s): {skipped}.' if empty_pages else ''
   self.refresh()
   self.end_progress(status_msg + note)

 def _ocr_error(self, msg):
   self.end_progress('OCR failed.')
   QMessageBox.critical(self,'OCR failed',msg)
   self.set_running(False)
   self.ocr_worker=None
   release_ocr_models()'''

    content = content[:match.start()] + new + content[match.end():]

    with open('c:\\Users\\Blue-Wingz\\BlueTL\\app.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Replacement successful!')
else:
    print('OCR method not found with regex')