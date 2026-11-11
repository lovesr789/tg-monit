import base64
from io import BytesIO
import unittest
from unittest.mock import Mock

from PIL import Image, ImageDraw

from captcha_ocr import CaptchaOcr


class CaptchaOcrTest(unittest.TestCase):
    def setUp(self):
        image = BytesIO()
        Image.new("RGB", (120, 80), "white").save(image, format="PNG")
        self.encoded = base64.b64encode(image.getvalue()).decode()
        self.ocr = CaptchaOcr()
        self.ocr._model = Mock()
        self.ocr._beta_model = Mock()

    def test_accept_four_letters(self):
        self.ocr._model.classification.return_value = "AbCd"
        self.ocr._beta_model.classification.return_value = "AbCd"
        self.assertEqual(self.ocr.recognize(self.encoded), "abcd")

    def test_reject_incomplete_results(self):
        for result in ("", "ab", "abcde", "1234", "中文文字"):
            self.ocr._model.classification.return_value = result
            self.ocr._beta_model.classification.return_value = result
            with self.assertRaises(ValueError):
                self.ocr.recognize(self.encoded)

    def test_reject_invalid_payloads(self):
        for image in (None, "!bad!", "a" * 1_400_001, base64.b64encode(b"not an image").decode()):
            with self.assertRaises((ValueError, OSError)):
                self.ocr.recognize(image)
        self.ocr._model.classification.assert_not_called()
        self.ocr._beta_model.classification.assert_not_called()

    def test_reject_conflicting_models(self):
        self.ocr._model.classification.return_value = "kouu"
        self.ocr._beta_model.classification.return_value = "kovu"
        with self.assertRaisesRegex(ValueError, "不一致"):
            self.ocr.recognize(self.encoded)

    def test_accept_three_matching_predictions(self):
        self.ocr._model.classification.side_effect = ["kovu", "kouu"]
        self.ocr._beta_model.classification.return_value = "kovu"
        self.assertEqual(self.ocr.recognize(self.encoded), "kovu")

    def test_preprocessed_disagreement_overrides_majority(self):
        self.ocr._beta_model.classification.side_effect = ["kovu", "kouu"]
        self.ocr._model.classification.return_value = "kouu"
        with self.assertRaisesRegex(ValueError, "不一致"):
            self.ocr.recognize(self.encoded)
        self.assertEqual(self.ocr._beta_model.classification.call_count, 1)
        self.assertEqual(self.ocr._model.classification.call_count, 1)

    def test_agreement_skips_unneeded_fourth_inference(self):
        self.ocr._beta_model.classification.return_value = "abcd"
        self.ocr._model.classification.return_value = "abcd"
        self.assertEqual(self.ocr.recognize(self.encoded), "abcd")
        self.assertEqual(self.ocr._beta_model.classification.call_count, 2)
        self.assertEqual(self.ocr._model.classification.call_count, 1)

    def test_invalid_predictions_do_not_count_as_votes(self):
        self.ocr._model.classification.side_effect = ["abcd", "abc"]
        self.ocr._beta_model.classification.side_effect = ["abcd", "12"]
        with self.assertRaisesRegex(ValueError, "不一致"):
            self.ocr.recognize(self.encoded)

    def test_blue_background_normalization(self):
        image = Image.new("RGB", (120, 100), (0, 100, 220))
        ImageDraw.Draw(image).rectangle((15, 30, 85, 65), fill="white")
        normalized = CaptchaOcr.normalize_image(image)
        self.assertEqual(normalized.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(normalized.getpixel((8, 8)), (0, 0, 0))
        self.assertEqual(normalized.size, (87, 52))

    def test_other_background_is_unchanged(self):
        image = Image.new("RGB", (120, 80), "white")
        self.assertEqual(CaptchaOcr.normalize_image(image).tobytes(), image.tobytes())

    def test_blank_blue_image_stops_before_inference(self):
        data = BytesIO()
        Image.new("RGB", (120, 100), (0, 100, 220)).save(data, format="PNG")
        with self.assertRaisesRegex(ValueError, "找不到文字"):
            self.ocr.recognize(base64.b64encode(data.getvalue()).decode())
        self.ocr._model.classification.assert_not_called()
