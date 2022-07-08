__version__ = "0.0.7"
__url__ = "https://github.com/amisadmin/fastapi_scheduler"

import gettext
import os

from fastapi_amis_admin import i18n

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

i18n.load_translations({
    "zh_CN": gettext.translation(
        domain='messages',
        localedir=os.path.join(BASE_DIR, "locale"),
        languages=['zh_CN']
    )
})

from .admin import SchedulerAdmin

__all__ = ["SchedulerAdmin"]
