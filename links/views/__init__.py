"""Stable view imports; implementations are grouped by feature ownership."""

from .accounts import (
    login_view as login_view,
)
from .accounts import (
    signup as signup,
)
from .analytics import (
    analytics_data as analytics_data,
)
from .analytics import (
    dashboard as dashboard,
)
from .analytics import (
    platform_analytics as platform_analytics,
)
from .analytics import (
    report_filters as report_filters,
)
from .analytics import (
    tag_filter as tag_filter,
)
from .management import (
    create_workspace as create_workspace,
)
from .management import (
    group_delete as group_delete,
)
from .management import (
    group_edit as group_edit,
)
from .management import (
    link_detail as link_detail,
)
from .management import (
    link_edit as link_edit,
)
from .management import (
    link_list as link_list,
)
from .management import (
    link_preview as link_preview,
)
from .management import (
    link_toggle as link_toggle,
)
from .management import (
    organize as organize,
)
from .management import (
    switch_workspace as switch_workspace,
)
from .redirects import (
    redirect_link as redirect_link,
)
from .redirects import (
    unavailable as unavailable,
)
from .redirects import (
    unlock_link as unlock_link,
)
from .sharing import (
    bio_page as bio_page,
)
from .sharing import (
    export_links as export_links,
)
from .sharing import (
    health as health,
)
from .sharing import (
    import_batch as import_batch,
)
from .sharing import (
    import_csv as import_csv,
)
from .sharing import (
    link_qr as link_qr,
)
from .sharing import (
    safe_cell as safe_cell,
)
from .sharing import (
    sample_csv as sample_csv,
)
from .sharing import (
    settings_view as settings_view,
)
