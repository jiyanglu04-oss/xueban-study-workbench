from __future__ import annotations

import unittest
from backend.timetable_image import decode_image, parse_words, TimetableImageError


def word(text, x, y, width=80, height=16):
    return {"text": text, "x": x, "y": y, "width": width, "height": height}


def grid_words():
    values = [word('星期'+day, 160+i*160, 40, 60) for i, day in enumerate('一二三四五')]
    values += [word(str(i), 60, 110+(i-1)*80, 15) for i in range(1, 9)]
    return values


class TimetableImageTests(unittest.TestCase):
    def test_rejects_non_image_and_invalid_base64(self):
        for value in ('hello', 'data:text/plain;base64,YQ==', 'data:image/png;base64,not=base64'):
            with self.assertRaises(TimetableImageError):
                decode_image(value)

    def test_no_grid_returns_manual_review_not_invented_courses(self):
        result = parse_words([word('大学生活', 200, 200)])
        self.assertEqual(result['courses'], [])
        self.assertTrue(result['warnings'])

    def test_course_rows_parity_range_and_merge(self):
        values = grid_words() + [word('高等数学', 170, 110), word('陈老师', 170, 128),
                                word('教学楼A301', 170, 146), word('1-16周(单)', 170, 164),
                                word('高等数学', 490, 270), word('陈老师', 490, 288)]
        result = parse_words(values)
        course = result['courses'][0]
        self.assertEqual(course['name'], '高等数学')
        self.assertEqual(course['teacher'], '陈老师')
        self.assertEqual(course['sessions'][0]['weeks'], '1-16单')
        self.assertEqual(course['sessions'][0]['day'], 1)
        self.assertEqual(course['sessions'][0]['start'], 1)
        self.assertEqual(course['sessions'][0]['room'], '教学楼A301')
        self.assertEqual(course['sessions'][1]['day'], 3)
        self.assertEqual(course['sessions'][1]['start'], 3)

    def test_split_chinese_weekday_and_missing_heading(self):
        values = grid_words()
        values = [v for v in values if v['text'] not in ('星期一', '星期二')]
        values += [word('星', 160, 40, 16), word('期', 178, 40, 16), word('一', 196, 40, 16),
                   word('程序设计', 330, 110)]
        result = parse_words(values)
        self.assertEqual(result['courses'][0]['sessions'][0]['day'], 2)

    def test_section_count_at_end_is_not_out_of_bounds(self):
        result = parse_words(grid_words()+[word('大学英语', 170, 670)], max_sections=8)
        self.assertEqual(result['courses'][0]['sessions'][0]['start'], 8)
        self.assertEqual(result['courses'][0]['sessions'][0]['len'], 1)

    def test_aligned_section_numbers_ignore_time_fragments(self):
        values = grid_words()+[word('5', 95, 140, 8), word('大学英语', 170, 110)]
        result = parse_words(values)
        self.assertEqual(result['courses'][0]['sessions'][0]['start'], 1)

    def test_ocr_chinese_dash_in_week_range(self):
        result = parse_words(grid_words()+[word('大学英语',170,110),word('2一16周（双）',170,130)])
        self.assertEqual(result['courses'][0]['sessions'][0]['weeks'],'2-16双')

    def test_section_range_does_not_become_week_range(self):
        result = parse_words(grid_words()+[word('程序设计',170,110),word('第1-4节',170,128),word('2-18周',170,146)])
        session = result['courses'][0]['sessions'][0]
        self.assertEqual(session['len'],4)
        self.assertEqual(session['weeks'],'2-18')


if __name__ == '__main__':
    unittest.main()
