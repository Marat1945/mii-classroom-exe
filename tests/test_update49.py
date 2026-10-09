"""5.2: логотип програми як іконка .exe (Провідник), вікна й панелі завдань."""
import io
import struct
import sys
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from test_update36 import TkCase
from test_update44 import TempProgram

from classroom_assistant import app_icon, gui, icon_builder
from classroom_assistant.app_icon_data import png_bytes

ROOT = Path(__file__).resolve().parents[1]
ICO = ROOT / "app_icon.ico"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def parse_ico(data: bytes):
    """Суворий розбір каталогу .ico: повертає [(розмір, ширина, висота, bpp, зсув, довжина)]."""
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1), "це не ico"
    entries = []
    for k in range(count):
        w, h, colors, zero, planes, bpp, length, offset = struct.unpack("<BBBBHHII", data[6 + 16 * k:22 + 16 * k])
        entries.append((w or 256, h or 256, colors, zero, planes, bpp, offset, length))
    return entries


class IcoFileTests(unittest.TestCase):
    def setUp(self):
        self.data = ICO.read_bytes()
        self.entries = parse_ico(self.data)

    def test_the_icon_has_every_size_windows_asks_for(self):
        self.assertEqual([e[0] for e in self.entries], list(icon_builder.SIZES))
        self.assertTrue(all(e[0] == e[1] for e in self.entries))                       # квадратні кадри
        self.assertEqual({e[5] for e in self.entries}, {32})                           # 32 біти з прозорістю
        self.assertTrue(all(e[4] == 1 and e[2] == 0 and e[3] == 0 for e in self.entries))
        self.assertEqual(self.entries[-1][0], 256)

    def test_directory_offsets_are_consistent_and_frames_do_not_overlap(self):
        position = 6 + 16 * len(self.entries)
        for _, _, _, _, _, _, offset, length in self.entries:
            self.assertEqual(offset, position)                                         # кадри йдуть упритул
            position += length
        self.assertEqual(position, len(self.data))                                     # і закінчуються рівно на кінці файла

    def test_small_frames_are_classic_bmp_and_large_ones_png(self):
        for size, _, _, _, _, _, offset, length in self.entries:
            frame = self.data[offset:offset + length]
            if size < icon_builder.PNG_LIMIT:
                header = struct.unpack("<IiiHHIIiiII", frame[:40])
                self.assertEqual(header[0], 40, size)                                  # BITMAPINFOHEADER
                self.assertEqual((header[1], header[2]), (size, size * 2), size)      # висота подвоєна (піксели + маска)
                self.assertEqual((header[3], header[4], header[5]), (1, 32, 0), size)
                pixels, mask = size * size * 4, ((size + 31) // 32) * 4 * size
                self.assertEqual(length, 40 + pixels + mask, size)
                self.assertEqual(header[6], pixels + mask, size)
            else:
                self.assertEqual(frame[:8], PNG_SIGNATURE, size)
                self.assertEqual(Image.open(io.BytesIO(frame)).size, (size, size))

    def test_every_frame_decodes_is_transparent_in_the_corners_and_solid_in_the_middle(self):
        icon = Image.open(ICO)
        self.assertEqual(sorted(icon.ico.sizes()), [(s, s) for s in icon_builder.SIZES])
        for size in icon_builder.SIZES:
            frame = icon.ico.getimage((size, size)).convert("RGBA")
            self.assertEqual(frame.getpixel((0, 0))[3], 0, size)                       # заокруглений кут прозорий
            self.assertEqual(frame.getpixel((size - 1, size - 1))[3], 0, size)
            self.assertGreater(frame.getpixel((size // 2, size // 2))[3], 240, size)

    def test_it_is_really_the_logo_with_its_green_light_and_brass_frame(self):
        frame = Image.open(ICO).ico.getimage((256, 256)).convert("RGBA")
        green = [p for p in frame.getdata() if p[3] > 200 and p[1] > 180 and p[0] < 140 and p[2] < 140]
        self.assertGreater(len(green), 40)                                             # зелена лампочка
        brass = [p for p in frame.getdata() if p[3] > 200 and p[0] > 150 and 90 < p[1] < 170 and p[2] < 90]
        self.assertGreater(len(brass), 1000)                                           # мідна окантовка

    def test_the_logo_fills_the_icon_instead_of_floating_in_empty_space(self):
        frame = Image.open(ICO).ico.getimage((256, 256)).convert("RGBA")
        box = frame.getchannel("A").point(lambda v: 255 if v > 64 else 0).getbbox()
        self.assertLessEqual(box[0], 8)
        self.assertGreaterEqual(box[2], 248)
        self.assertLessEqual(box[1], 8)
        self.assertGreaterEqual(box[3], 248)

    def test_the_window_icon_is_the_same_logo(self):
        window = Image.open(io.BytesIO(png_bytes())).convert("RGBA")
        self.assertEqual(window.size, (256, 256))
        reference = Image.open(ICO).ico.getimage((256, 256)).convert("RGBA")
        mean = lambda im: [sum(c) / (256 * 256) for c in zip(*im.getdata())]
        for a, b in zip(mean(window), mean(reference)):
            self.assertAlmostEqual(a, b, delta=3)


class BuilderTests(unittest.TestCase):
    def source(self):
        image = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
        image.paste(Image.new("RGBA", (200, 100), (200, 40, 40, 255)), (100, 100))      # логотип із великими порожніми полями
        return image

    def test_empty_margins_are_cropped_and_the_result_is_square(self):
        square = icon_builder.tight_square(self.source())
        self.assertEqual(square.width, square.height)
        box = square.getchannel("A").getbbox()
        self.assertLess(box[0], 8)
        self.assertGreater(box[2], square.width - 8)

    def test_a_built_icon_is_valid_for_any_logo(self):
        data = icon_builder.build_ico(self.source())
        entries = parse_ico(data)
        self.assertEqual([e[0] for e in entries], list(icon_builder.SIZES))
        position = 6 + 16 * len(entries)
        for entry in entries:
            self.assertEqual(entry[6], position)
            position += entry[7]
        self.assertEqual(position, len(data))
        self.assertEqual(Image.open(io.BytesIO(data)).ico.getimage((32, 32)).size, (32, 32))

    def test_small_sizes_are_sharpened_but_never_lose_transparency(self):
        square = icon_builder.tight_square(self.source())
        small = icon_builder.render(square, 16)
        self.assertEqual(small.size, (16, 16))
        self.assertEqual(small.getpixel((8, 8))[3], 255)
        corner = icon_builder.tight_square(self.source(), margin=0.2)
        self.assertEqual(icon_builder.render(corner, 16).getpixel((0, 0))[3], 0)

    def test_faint_glow_around_the_logo_does_not_leave_dots_in_the_corners(self):
        image = Image.new("RGBA", (200, 200), (0, 0, 0, 1))                              # майже невидиме сяйво по всьому полю
        image.paste(Image.new("RGBA", (100, 100), (200, 40, 40, 255)), (50, 50))
        for size in (16, 24, 32, 256):
            frame = icon_builder.render(icon_builder.tight_square(image, margin=0.3), size)
            self.assertEqual(frame.getpixel((0, 0))[3], 0, size)

    def test_png_for_the_window_has_the_asked_size(self):
        self.assertEqual(Image.open(io.BytesIO(icon_builder.build_png(self.source(), 128))).size, (128, 128))


class WindowIconTests(TkCase):
    def test_the_logo_becomes_the_window_icon_in_several_sizes(self):
        self.assertTrue(app_icon.apply(self.root))
        self.assertEqual(len(self.root._icon_images), len(app_icon.WINDOW_SIZES))
        self.assertEqual([img.width() for img in self.root._icon_images], list(app_icon.WINDOW_SIZES))

    def test_a_failure_never_breaks_the_program(self):
        with mock.patch.object(self.root, "iconphoto", side_effect=__import__("tkinter").TclError("x")):
            self.assertFalse(app_icon.apply(self.root))
        with mock.patch.object(app_icon, "photos", side_effect=ImportError("PIL")):
            self.assertFalse(app_icon.apply(self.root))

    def test_taskbar_identity_is_set_only_on_windows(self):
        self.assertFalse(app_icon.set_app_id())                                         # у Linux нічого не робить
        fake = mock.Mock()
        with mock.patch.object(sys, "platform", "win32"), mock.patch("ctypes.windll", fake, create=True):
            self.assertTrue(app_icon.set_app_id())
        fake.shell32.SetCurrentProcessExplicitAppUserModelID.assert_called_once_with(app_icon.APP_ID)
        broken = mock.Mock()
        broken.shell32.SetCurrentProcessExplicitAppUserModelID.side_effect = OSError("немає")
        with mock.patch.object(sys, "platform", "win32"), mock.patch("ctypes.windll", broken, create=True):
            self.assertFalse(app_icon.set_app_id())


class MainWindowIconTests(TempProgram):
    def test_the_main_window_wears_the_logo(self):
        self.assertTrue(hasattr(self.app, "_icon_images"))
        self.assertEqual(len(self.app._icon_images), len(app_icon.WINDOW_SIZES))

    def test_launch_sets_the_taskbar_identity_before_the_window_opens(self):
        order = []
        with mock.patch.object(app_icon, "set_app_id", side_effect=lambda: order.append("id")), \
                mock.patch.object(gui, "MainApp") as app:
            app.side_effect = lambda **kw: order.append("window") or mock.Mock()
            gui.launch()
        self.assertEqual(order, ["id", "window"])


class BuildConfigTests(unittest.TestCase):
    def test_the_windows_build_embeds_the_icon_into_the_exe(self):
        workflow = (ROOT / ".github" / "workflows" / "Windows_EXE.yml").read_text(encoding="utf-8")
        self.assertIn('--icon "app_icon.ico"', workflow)
        for needle in ("--onefile", "--windowed", "--name Pomichnyk_Uchytelia", '--add-data "data;data"',
                       'Запустити Windows EXE.py', "dist/Pomichnyk_Uchytelia.exe"):
            self.assertIn(needle, workflow, needle)                                   # решта команди не зачеплена
        self.assertTrue((ROOT / "app_icon.ico").is_file())                            # файл лежить там, куди вказує команда


if __name__ == "__main__":
    unittest.main()
