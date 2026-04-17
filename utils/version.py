"""Single source of truth cho phiên bản app."""

from __future__ import annotations

# Phải khớp với version trong pyproject.toml.
# Sau khi release, update cả 2 nơi rồi tạo tag git v{VERSION}.
__version__ = "0.4.3"

# Repo GitHub để check update. Sửa thành <your-user>/<repo-name> của bạn.
GITHUB_REPO = "YOUR_GITHUB_USER/realtime-translator"
