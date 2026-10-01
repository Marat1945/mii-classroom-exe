"""3.2: вибір семестру й чернетки без обов'язкового Word."""
import sys
import types
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from classroom_assistant.engine import read_json, day_lessons, week_phase
from classroom_assistant.draft_batch import plan_day_drafts
from classroom_assistant import google_client


class Update32Tests(unittest.TestCase):
    def setUp(self):
        self.cfg=read_json("Налаштування.json")
        self.lesson=day_lessons("2026-10-01")[0]
        self.key=self.lesson.unique_key
        self.course=self.lesson.course_title
        self.basestate={"course_ids":{self.course:"course-123"},
                        "files":{},"drafts":{},"attachments":{}}

    def plan(self, description, state=None):
        return plan_day_drafts([self.lesson],state or self.basestate,lambda _:description)

    def test_without_word_text_only_is_valid(self):
        ready,skipped=self.plan("Підручник, вправа 5.")
        self.assertEqual(len(ready),1)
        self.assertIsNone(ready[0]["docx_path"])
        self.assertEqual(ready[0]["description"],"Підручник, вправа 5.")
        self.assertFalse(skipped)

    def test_without_word_picture_only_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            image=Path(directory)/"малюнок.jpg"
            image.write_bytes(b"jpeg placeholder")
            state=dict(self.basestate)
            state["attachments"]={self.key:[{"path":str(image),"name":"малюнок.jpg"}]}
            ready,skipped=self.plan("",state)
            self.assertFalse(skipped)
            self.assertEqual(ready[0]["attachments"],[str(image)])
            self.assertIsNone(ready[0]["docx_path"])

    def test_without_any_content_skip(self):
        ready,skipped=self.plan("  ")
        self.assertEqual(ready,[])
        self.assertIn("немає тексту",skipped[0][1])

    def test_unverified_word_does_not_block_text(self):
        state=dict(self.basestate)
        state["files"]={self.key:{"path":"/no/such/file.docx","validated":False}}
        ready,skipped=self.plan("Пояснення без Word",state)
        self.assertEqual(len(ready),1)
        self.assertIsNone(ready[0]["docx_path"])
        self.assertFalse(skipped)

    def test_existing_draft_and_missing_course_skip(self):
        state=dict(self.basestate)
        state["drafts"]={self.key:{"id":"already-created"}}
        ready,skipped=self.plan("Текст",state)
        self.assertFalse(ready)
        self.assertIn("вже створено",skipped[0][1])
        state=dict(self.basestate)
        state["course_ids"]={}
        ready,skipped=self.plan("Текст",state)
        self.assertFalse(ready)
        self.assertIn("не зіставлено",skipped[0][1])

    def test_second_semester_override_only_when_enabled(self):
        jan_04=date(2027,1,4)
        jan_11=date(2027,1,11)
        self.assertEqual(week_phase(jan_11,self.cfg),"знаменник")
        self.cfg.update({"semester2_override":False,"semester2_start":"2027-01-11",
                         "semester2_anchor_monday":"2027-01-11",
                         "semester2_anchor_phase":"чисельник"})
        self.assertEqual(week_phase(jan_11,self.cfg),"знаменник")
        self.cfg["semester2_override"]=True
        self.assertEqual(week_phase(jan_11,self.cfg),"чисельник")
        self.assertEqual(week_phase(jan_04,self.cfg),"чисельник")

    def test_google_api_text_only_omits_materials(self):
        fake_http=types.ModuleType("googleapiclient.http")
        fake_http.MediaFileUpload=Mock()
        fake_package=types.ModuleType("googleapiclient")
        fake_package.http=fake_http
        classroom=Mock()
        classroom.courses.return_value.courseWorkMaterials.return_value.create.return_value.execute.return_value={"id":"draft-one"}
        with patch.dict(sys.modules,{"googleapiclient":fake_package,
                                     "googleapiclient.http":fake_http}),\
             patch.object(google_client,"services",return_value=(classroom,Mock())):
            result=google_client.create_draft("course-123","Завдання","Тільки текст")
        self.assertEqual(result["state"],"DRAFT")
        self.assertIsNone(result["drive_id"])
        kwargs=classroom.courses.return_value.courseWorkMaterials.return_value.create.call_args.kwargs
        self.assertEqual(kwargs["body"]["state"],"DRAFT")
        self.assertNotIn("materials",kwargs["body"])

    def test_google_api_picture_only_uploads_one_file(self):
        with tempfile.TemporaryDirectory() as directory:
            picture=Path(directory)/"photo.jpg"
            picture.write_bytes(b"sample")
            fake_http=types.ModuleType("googleapiclient.http")
            fake_http.MediaFileUpload=lambda *a,**k:"media"
            fake_package=types.ModuleType("googleapiclient")
            fake_package.http=fake_http
            classroom=Mock()
            drive=Mock()
            drive.files.return_value.create.return_value.execute.return_value={"id":"image-drive"}
            classroom.courses.return_value.courseWorkMaterials.return_value.create.return_value.execute.return_value={"id":"draft-2"}
            with patch.dict(sys.modules,{"googleapiclient":fake_package,
                                         "googleapiclient.http":fake_http}),\
                 patch.object(google_client,"services",return_value=(classroom,drive)):
                result=google_client.create_draft("course-123","Зображення","",
                                                  None,False,[str(picture)])
            self.assertEqual(result["drive_id"],"image-drive")
            self.assertEqual(result["attachment_drive_ids"],["image-drive"])
            self.assertEqual(result["state"],"DRAFT")

    def test_google_api_rejects_empty_draft(self):
        fake_http=types.ModuleType("googleapiclient.http")
        fake_http.MediaFileUpload=Mock()
        fake_package=types.ModuleType("googleapiclient")
        fake_package.http=fake_http
        with patch.dict(sys.modules,{"googleapiclient":fake_package,
                                     "googleapiclient.http":fake_http}),\
             patch.object(google_client,"services",return_value=(Mock(),Mock())):
            with self.assertRaises(ValueError):
                google_client.create_draft("course-123","Назва","  ",None)
