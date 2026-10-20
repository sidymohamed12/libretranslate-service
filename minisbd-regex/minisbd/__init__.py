"""API minimale de minisbd utilisée par argos-translate et LibreTranslate.

  argostranslate/sbd.py  : from minisbd import SBDetect, models as minisbd_models
                           minisbd_models.cache_dir = ...
                           minisbd_models.list_models()
                           SBDetect(lang, use_gpu=...).sentences(text)
  libretranslate/init.py : from minisbd import download_models
"""

from . import models
from .models import download_models, list_models
from .sbd import SBDetect

__all__ = ["SBDetect", "download_models", "list_models", "models"]
