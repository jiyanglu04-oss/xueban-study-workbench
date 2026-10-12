"""Local Windows OCR -> editable timetable draft. Never writes the user's state."""
from __future__ import annotations

import base64
import binascii
import io
import json
import re
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path


class TimetableImageError(ValueError):
    pass


def decode_image(data_url: str) -> bytes:
    if not isinstance(data_url, str) or len(data_url) > 7_000_000:
        raise TimetableImageError("图片过大，请上传小于 4 MB 的课表截图。")
    match = re.fullmatch(r"data:image/(?:png|jpeg|webp);base64,([A-Za-z0-9+/=\r\n]+)", data_url)
    if not match:
        raise TimetableImageError("请上传 PNG、JPG 或 WebP 图片。")
    try:
        raw = base64.b64decode(match[1], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise TimetableImageError("图片数据无效，请重新选择图片。") from exc
    if len(raw) > 4 * 1024 * 1024:
        raise TimetableImageError("图片过大，请上传小于 4 MB 的课表截图。")
    return raw


def parse_words(words: list[dict], total_weeks: int = 20, max_sections: int = 13) -> dict:
    """Infer a grid from weekday/section headers; uncertain values stay editable."""
    total_weeks = max(1, min(40, int(total_weeks)))
    max_sections = max(1, min(30, int(max_sections)))
    items = []
    for word in words:
        text = str(word.get("text", "")).strip()
        if text:
            x, y = float(word["x"]), float(word["y"])
            w, h = float(word["width"]), float(word["height"])
            items.append(dict(text=text, x=x, y=y, w=w, h=h, cx=x+w/2, cy=y+h/2))
    items.sort(key=lambda t: (t["cy"], t["x"]))
    # Windows OCR treats Chinese characters as individual words. Join adjacent
    # characters on a baseline, but retain gaps between different table cells.
    baselines = []
    for item in items:
        if baselines and abs(item["cy"]-statistics.median(t["cy"] for t in baselines[-1])) < max(5, item["h"]*.7):
            baselines[-1].append(item)
        else:
            baselines.append([item])
    merged = []
    for line in baselines:
        line.sort(key=lambda t: t["x"])
        parts = []
        for item in line:
            if parts and item["x"]-(parts[-1]["x"]+parts[-1]["w"]) < max(item["h"], parts[-1]["h"])*1.1:
                previous = parts[-1]
                previous["text"] += item["text"]
                right = max(previous["x"]+previous["w"], item["x"]+item["w"])
                bottom_y = max(previous["y"]+previous["h"], item["y"]+item["h"])
                previous["y"] = min(previous["y"], item["y"])
                previous["w"], previous["h"] = right-previous["x"], bottom_y-previous["y"]
                previous["cx"], previous["cy"] = previous["x"]+previous["w"]/2, previous["y"]+previous["h"]/2
            else:
                parts.append(dict(item))
        merged.extend(parts)
    items = sorted(merged, key=lambda t: (t["cy"], t["x"]))
    raw_text = "\n".join(t["text"] for t in items)
    day_map = {c: i + 1 for i, c in enumerate("一二三四五六日")}
    day_map["天"] = 7
    headers = []
    for t in items:
        m = re.fullmatch(r"(?:星期|周|礼拜)([一二三四五六日天1-7])", t["text"])
        if m:
            day = int(m[1]) if m[1].isdigit() else day_map[m[1]]
            headers.append(dict(t, day=day))
    # OCR may split '星期' and '一'. Pair only adjacent words on the same baseline.
    for t in items:
        if t["text"] in ("星期", "周", "礼拜"):
            following = [q for q in items if q["text"] in day_map
                         and abs(q["cy"]-t["cy"]) < max(t["h"], q["h"])
                         and 0 <= q["x"]-(t["x"]+t["w"]) < t["h"]*2]
            if following:
                q = min(following, key=lambda a: a["x"])
                headers.append(dict(t, cx=(t["x"]+q["x"]+q["w"])/2, day=day_map[q["text"]]))
    best = []
    for h in headers:
        row = [q for q in headers if abs(q["cy"]-h["cy"]) < max(18, h["h"]*1.5)]
        unique = {q["day"]: q for q in row}
        if len(unique) > len(best):
            best = sorted(unique.values(), key=lambda q: q["cx"])
    warnings = ["OCR 结果需要校对；未写明的节数默认按 2 节、周次按教学周填写。"]
    if len(best) < 3:
        return {"courses": [], "warnings": ["没有识别到至少三个星期列。请上传清晰的整周课表，或手动补录。"], "rawText": raw_text}
    # A partially missed weekday heading must not shift all following columns.
    if all(b["day"] > a["day"] for a, b in zip(best, best[1:])):
        spacing = statistics.median((b["cx"]-a["cx"])/(b["day"]-a["day"]) for a, b in zip(best, best[1:]))
        first_x = statistics.median(h["cx"]-(h["day"]-1)*spacing for h in best)
        known = {h["day"]: h for h in best}
        best = [known.get(day, dict(day=day, cx=first_x+(day-1)*spacing, cy=best[0]["cy"]))
                for day in range(1, max(known)+1)]
    centers = [h["cx"] for h in best]
    gap = statistics.median(b-a for a, b in zip(centers, centers[1:]))
    bounds = [centers[0]-gap/2] + [(a+b)/2 for a, b in zip(centers, centers[1:])] + [centers[-1]+gap/2]
    header_y = statistics.median(h["cy"] for h in best)
    candidates = []
    for t in items:
        if t["cx"] < bounds[0] and t["cy"] > header_y:
            m = re.fullmatch(r"(?:第)?(\d{1,2})(?:节)?", t["text"])
            if m and 1 <= int(m[1]) <= max_sections:
                candidates.append(dict(t, number=int(m[1])))
    # Section numbers share a narrow x-axis. Times and sidebar badges do not.
    aligned = []
    for candidate in candidates:
        group = [t for t in candidates if abs(t["cx"]-candidate["cx"]) <= max(3, candidate["h"]*.4)]
        if len({t["number"] for t in group}) > len({t["number"] for t in aligned}):
            aligned = group
    anchors = {}
    for t in sorted(aligned, key=lambda q: q["cy"]):
        anchors.setdefault(t["number"], t["cy"])
    ordered = sorted(anchors.items())
    if len(ordered) < 3 or any(b[1] <= a[1] for a, b in zip(ordered, ordered[1:])):
        return {"courses": [], "warnings": ["识别到星期列，但没有识别到左侧节次。请保留节次栏重新截图，或手动补录。"], "rawText": raw_text}
    step = statistics.median((b[1]-a[1])/(b[0]-a[0]) for a, b in zip(ordered, ordered[1:]))
    origin = statistics.median(y-(n-1)*step for n, y in ordered)
    bottom = origin+(max_sections-.5)*step
    courses = []
    for i, header in enumerate(best):
        column = [t for t in items if bounds[i] <= t["cx"] < bounds[i+1]
                  and max(header_y+step*.5, origin-step*.4) < t["cy"] < bottom
                  and not re.fullmatch(r"\d{1,2}[/月.-]\d{1,2}|\d{1,2}:\d{2}", t["text"])]
        lines = []
        for t in column:
            if lines and abs(t["cy"]-lines[-1]["cy"]) < max(5, t["h"]*.6):
                lines[-1]["parts"].append(t)
            else:
                lines.append({"cy": t["cy"], "parts": [t]})
        for line in lines:
            line["text"] = "".join(p["text"] for p in sorted(line["parts"], key=lambda p: p["x"]))
        groups = []
        for line in lines:
            if groups and line["cy"]-groups[-1][-1]["cy"] < step*.65:
                groups[-1].append(line)
            else:
                groups.append([line])
        for group in groups:
            texts = [g["text"] for g in group]
            if not texts or all(re.fullmatch(r"[\d\s:/.\-]+", t) for t in texts):
                continue
            name = texts[0]
            if re.search(r"课时|在修课程|考试周|点空白|教学周|上课时间|第\s*\d+\s*周", name):
                continue
            start = max(1, min(max_sections, round((group[0]["cy"]-origin)/step)+1))
            joined = re.sub(r"(?<=\d)[一—–－](?=\d)", "-", " ".join(texts))
            sections = re.search(r"(?:第|[（(])?(\d{1,2})\s*[-~至]\s*(\d{1,2})\s*节", joined)
            length = min(2, max_sections-start+1)
            if sections:
                start, end = int(sections[1]), int(sections[2])
                if not 1 <= start <= end <= max_sections:
                    continue
                length = end-start+1
            # A section range like 第1-4节 is not a week range.
            weeks = re.search(r"(\d{1,2})\s*[-~至]\s*(\d{1,2})\s*(?:周\s*[（(]?([单双])?|[（(]?([单双])\s*周?)", joined)
            if not weeks:
                weeks = next((m for text in texts if (m := re.fullmatch(r"(\d{1,2})\s*[-~至一]\s*(\d{1,2})([单双])?", text))), None)
            weeks_text = f"1-{max(1, total_weeks-2)}"
            if weeks:
                a, b = int(weeks[1]), int(weeks[2])
                if 1 <= a <= b <= total_weeks:
                    parity = next((p for p in weeks.groups()[2:] if p in ("单", "双")), "")
                    weeks_text = f"{a}-{b}" + parity
            if "单周" in joined and "单" not in weeks_text:
                weeks_text += "单"
            elif "双周" in joined and "双" not in weeks_text:
                weeks_text += "双"
            teacher, room = "", ""
            for text in texts[1:]:
                if re.search(r"老师|教师|授课", text):
                    teacher = re.sub(r"^(?:教师|授课教师|老师)[:：]?", "", text)
                elif re.search(r"教室|教学楼|实验|机房|[A-Z]\d{2,4}|[教实]\d{2,4}", text):
                    room = re.sub(r"^教室[:：]?", "", text)
            name = re.sub(r"[（(]?\d{1,2}[-~至]\d{1,2}周[单双]?[）)]?", "", name).strip()
            if len(name) < 2:
                continue
            session = {"day": header["day"], "start": start, "len": length, "weeks": weeks_text, "room": room}
            existing = next((c for c in courses if c["name"] == name and c["teacher"] == teacher), None)
            if existing:
                existing["sessions"].append(session)
            else:
                courses.append({"name": name, "teacher": teacher, "platform": "", "note": "图片识别原文："+" / ".join(texts), "sessions": [session]})
    return {"courses": courses, "warnings": warnings if courses else ["识别到了课表结构，但没有提取到课程。请换一张更清晰的截图，或手动补录。"], "rawText": raw_text}


def recognize_image(data_url: str, python: Path, root: Path, total_weeks=20, max_sections=13) -> dict:
    raw = decode_image(data_url)
    with tempfile.TemporaryDirectory(prefix="xueban-timetable-") as temp:
        image_path = Path(temp)/"timetable.png"
        try:
            from PIL import Image, ImageOps
            with Image.open(io.BytesIO(raw)) as image:
                if image.width*image.height > 16_000_000 or image.width < 100 or image.height < 100:
                    raise TimetableImageError("图片尺寸不合适，请上传清晰的课表截图。")
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((2600, 2600))
                if max(image.size) < 2200:
                    factor = 2200 / max(image.size)
                    image = image.resize((round(image.width*factor), round(image.height*factor)), Image.Resampling.LANCZOS)
                image = ImageOps.autocontrast(ImageOps.grayscale(image))
                image.save(image_path)
        except ImportError as exc:
            raise TimetableImageError("图片识别组件未安装，请重新运行「安装环境.bat」。") from exc
        except TimetableImageError:
            raise
        except Exception as exc:
            raise TimetableImageError("无法读取图片，请改用 PNG 或 JPG 截图。") from exc
        try:
            result = subprocess.run([str(python), "-m", "backend.timetable_image", "--ocr", str(image_path)],
                                    cwd=str(root), capture_output=True, timeout=60,
                                    encoding="utf-8", errors="replace",
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            data = json.loads(result.stdout.strip())
        except subprocess.TimeoutExpired as exc:
            raise TimetableImageError("识别超时，请上传裁掉无关内容的课表截图。") from exc
        except (OSError, ValueError) as exc:
            raise TimetableImageError("本机 OCR 启动失败，请检查 Windows 中文 OCR 语言包并重新安装运行环境。") from exc
        if not data.get("ok"):
            raise TimetableImageError(data.get("error") or "本机 OCR 识别失败。")
        return parse_words(data.get("words", []), total_weeks, max_sections)


async def _ocr(path: str) -> list[dict]:
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.storage import StorageFile, FileAccessMode
    languages = [l for l in OcrEngine.available_recognizer_languages if l.language_tag.startswith('zh')]
    engine = OcrEngine.try_create_from_language(languages[0]) if languages else None
    if engine is None:
        raise TimetableImageError("请在 Windows 语言设置中安装简体中文的「光学字符识别」功能。")
    file = await StorageFile.get_file_from_path_async(str(Path(path).resolve()))
    stream = await file.open_async(FileAccessMode.READ)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    result = await engine.recognize_async(bitmap)
    return [{"text": word.text, "x": word.bounding_rect.x, "y": word.bounding_rect.y,
             "width": word.bounding_rect.width, "height": word.bounding_rect.height}
            for line in result.lines for word in line.words]


if __name__ == "__main__":
    import asyncio
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        if len(sys.argv) != 3 or sys.argv[1] != "--ocr":
            raise TimetableImageError("无效识别参数")
        print(json.dumps({"ok": True, "words": asyncio.run(_ocr(sys.argv[2]))}, ensure_ascii=False))
    except Exception as exc:
        message = str(exc) if isinstance(exc, TimetableImageError) else "本机 OCR 组件不可用，请重新运行安装环境并检查中文 OCR 语言包。"
        print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
