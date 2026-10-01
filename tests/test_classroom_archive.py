
"""Пости Classroom: тільки читання, правильна пагінація та стани."""
import unittest
from unittest.mock import Mock,patch
from classroom_assistant.classroom_archive import (
 fetch_paged_items,normalize_item,normalize_attachment,
 compatible_classroom_title,safe_url,
)
from classroom_assistant.google_client import list_classroom_posts,SCOPES,ANNOUNCEMENT_SCOPES
from classroom_assistant.engine import day_lessons


class ArchiveTests(unittest.TestCase):
    def test_both_published_and_draft_requested_on_every_page(self):
        client=Mock()
        client.list.return_value.execute.side_effect=[
            {"courseWorkMaterial":[{"state":"PUBLISHED","id":"1"}],"nextPageToken":"MORE"},
            {"courseWorkMaterial":[{"state":"DRAFT","id":"2"}]},
        ]
        rows,truncated=fetch_paged_items(client,"COURSE","courseWorkMaterial",
                                             "courseWorkMaterialStates")
        self.assertEqual(len(rows),2)
        self.assertFalse(truncated)
        first=client.list.call_args_list[0].kwargs
        second=client.list.call_args_list[1].kwargs
        self.assertEqual(first["courseWorkMaterialStates"],["PUBLISHED","DRAFT"])
        self.assertEqual(second["pageToken"],"MORE")

    def test_normalize_material_with_attachments(self):
        post={"id":"abc","courseId":"123","title":"Урок 01.10 — Тема",
              "description":"Повний опис","state":"PUBLISHED",
              "materials":[{"driveFile":{"driveFile":{"id":"sAfE_AbCd123","title":"Конспект.docx"}}},
                           {"link":{"title":"Енциклопедія","url":"https://example.org/p"}},
                           {"youtubeVideo":{"id":"abcdefghijk","title":"Відео"}},
                           {"form":{"title":"Тест","formUrl":"https://docs.google.com/forms/d/a"}}]}
        n=normalize_item(post,"Матеріал","123")
        self.assertEqual(n["course_id"],"123")
        self.assertEqual(n["state_ua"],"Опубліковано")
        self.assertEqual(len(n["attachments"]),4)
        self.assertEqual(n["attachments"][0]["kind"],"Google Drive")
        self.assertTrue(n["attachments"][0]["url"].startswith("https://drive.google.com/"))

    def test_draft_announcement_text(self):
        post={"id":"42","state":"DRAFT","text":"Повторіть § 3",
              "creationTime":"2026-10-01T11:00:00Z","materials":[]}
        n=normalize_item(post,"Оголошення","999")
        self.assertEqual(n["state_ua"],"Чернетка")
        self.assertEqual(n["description"],"Повторіть § 3")

    def test_unsafe_urls_not_passed_to_open(self):
        self.assertEqual(safe_url("javascript:alert(1)"),"")
        self.assertEqual(safe_url("file:///c:/secrets.txt"),"")
        self.assertEqual(normalize_attachment({"link":{"url":"javascript:evil"}})["url"],"")
        self.assertEqual(safe_url("https://drive.google.com/x"),"https://drive.google.com/x")

    def test_remote_status_only_exact_title(self):
        lesson=day_lessons("2026-10-01")[2]
        good={"course_id":"123","title":f"Урок 01.10 — {lesson.topic}."}
        bad={"course_id":"123","title":f"Урок 02.10 — {lesson.topic}."}
        self.assertTrue(compatible_classroom_title(lesson,good))
        self.assertFalse(compatible_classroom_title(lesson,bad))

    def test_basic_google_scopes_remain_unchanged(self):
        self.assertNotIn("https://www.googleapis.com/auth/classroom.announcements.readonly",SCOPES)
        self.assertIn("https://www.googleapis.com/auth/classroom.announcements.readonly",
                      ANNOUNCEMENT_SCOPES)

    def test_list_both_kinds_and_optional_announcements(self):
        client=Mock()
        endpoint_material=client.courses.return_value.courseWorkMaterials.return_value
        endpoint_work=client.courses.return_value.courseWork.return_value
        endpoint_ann=client.courses.return_value.announcements.return_value
        endpoint_material.list.return_value.execute.return_value={
            "courseWorkMaterial":[{"id":"m","state":"PUBLISHED","title":"Конспект"}]}
        endpoint_work.list.return_value.execute.return_value={
            "courseWork":[{"id":"w","state":"DRAFT","title":"Практична"}]}
        endpoint_ann.list.return_value.execute.return_value={
            "announcements":[{"id":"a","state":"PUBLISHED","text":"Привіт"}]}
        with patch("classroom_assistant.google_client.services",return_value=(client,Mock())) as services:
            only_two=list_classroom_posts("X")
            self.assertEqual({p["type"] for p in only_two["items"]},{"Матеріал","Завдання"})
            services.assert_called_with(with_announcements=False)
            all_three=list_classroom_posts("X",include_announcements=True)
            self.assertEqual({p["type"] for p in all_three["items"]},
                             {"Матеріал","Завдання","Оголошення"})
            services.assert_called_with(with_announcements=True)
