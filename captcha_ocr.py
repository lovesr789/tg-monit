"""Local-only captcha inference; the browser supplies the displayed image bytes."""
import base64
from io import BytesIO
import re
import threading


class CaptchaOcr:
    def __init__(self):
        self._model = None
        self._beta_model = None
        self._lock = threading.Lock()

    def warmup(self):
        with self._lock:
            if self._model is None:
                import ddddocr

                self._model = ddddocr.DdddOcr(show_ad=False)
            if self._beta_model is None:
                import ddddocr

                self._beta_model = ddddocr.DdddOcr(show_ad=False, beta=True)

    @staticmethod
    def normalize_image(image):
        """Convert blue-background/white-letter captchas to black letters on white."""
        import numpy as np
        from PIL import Image, ImageOps

        pixels = np.asarray(image.convert("RGB"), dtype=np.int16)
        red, green, blue = (pixels[:, :, index] for index in range(3))
        blue_background = (blue > 100) & (blue > red + 45) & (blue > green + 25)
        if blue_background.mean() < 0.4:
            return image.convert("RGB")
        letters = (pixels.min(axis=2) > 150) & (pixels.max(axis=2) - pixels.min(axis=2) < 80)
        mask = Image.fromarray((letters * 255).astype("uint8"))
        bounds = mask.getbbox()
        if not bounds:
            raise ValueError("驗證碼圖片中找不到文字，請換圖或手動輸入")
        return ImageOps.expand(ImageOps.invert(mask.crop(bounds)), border=8, fill="white").convert("RGB")

    def recognize(self, encoded: str) -> str:
        if not isinstance(encoded, str) or len(encoded) > 1_400_000:
            raise ValueError("驗證碼圖片格式或大小不符")
        image = base64.b64decode(encoded, validate=True)
        from PIL import Image

        with Image.open(BytesIO(image)) as decoded:
            if decoded.width > 2048 or decoded.height > 2048:
                raise ValueError("驗證碼圖片尺寸過大")
            decoded.verify()
        with Image.open(BytesIO(image)) as decoded:
            normalized = self.normalize_image(decoded)
        prepared = BytesIO()
        normalized.save(prepared, format="PNG")
        self.warmup()
        with self._lock:
            prepared_bytes = prepared.getvalue()
            beta = self._beta_model.classification(prepared_bytes).strip().lower()
            default = self._model.classification(prepared_bytes).strip().lower()
            # Same acceptance rule as before: processed results must agree and
            # at least one original-image result must support them (3 of 4).
            # Stop as soon as acceptance/rejection is decided, saving inference.
            if re.fullmatch(r"[a-z]{4}", beta) and beta == default:
                for model in (self._beta_model, self._model):
                    if model.classification(image).strip().lower() == beta:
                        return beta
        raise ValueError("兩個模型或圖片處理前後辨識不一致，已停止填入與自動送出，請手動輸入或換圖")


ocr = CaptchaOcr()
