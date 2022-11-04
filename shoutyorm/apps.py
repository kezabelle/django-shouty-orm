from __future__ import annotations
import logging
from django.apps import AppConfig
from .patches import patch

logger = logging.getLogger(__name__)


class Shout(AppConfig):  # type: ignore
    """
    Applies the patch automatically if enabled by adding `shoutyorm` or
    `shoutyorm.Shout` to INSTALLED_APPS.
    """

    # noinspection PyUnresolvedReferences
    name = "shoutyorm"

    def ready(self) -> bool:
        # The import of settings is deferred until here so that help(shoutyorm)
        # and by extension "$ pydoc shoutyorm" both work instead of barfing
        # about django not being configured yet.
        from django.conf import settings

        logger.info("Applying shouty ORM patch")
        return patch()
