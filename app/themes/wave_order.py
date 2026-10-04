"""Manual theme spectrum order for the 3D heat-wave overview.

Left → right: defensive / finance / property → cyclical → policy manufacturing → tech growth.
"""

from __future__ import annotations

# theme_id order along the X axis (spacing is uniform; MDS can refine later).
SPECTRUM_THEME_IDS: tuple[str, ...] = (
    "food",
    "finance",
    "property",
    "energy",
    "metals",
    "defense",
    "medicine",
    "renewables",
    "battery",
    "robots",
    "semiconductor",
    "ai",
)

SPECTRUM_AXIS_NOTE = (
    "横轴：防守消费/金融地产 → 周期资源 → 军工医药 → 制造成长 → 科技"
    "（主题轴为叙事近似，相邻主题已插值成连续色场）；"
    "颜色：热度（越高越热）；进深：时间。"
)

RANK_AXIS_NOTE = (
    "横轴：按窗口中间交易日群 A 热度从高到低固定排序（整窗按此序回溯，不逐日重排；"
    "相邻主题已插值平滑）；"
    "颜色与进深同上图。"
)
