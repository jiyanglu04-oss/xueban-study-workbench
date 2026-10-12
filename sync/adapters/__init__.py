# -*- coding: utf-8 -*-
"""把学伴能自动抓取的平台适配器集合起来。

想加自己的学校/平台，照抄一个适配器文件，然后在下面注册即可。
（适配器基类见 base.py，现成的例子见 chaoxing.py / yuketang.py / icourse163.py）
"""

from .base import Adapter                    # noqa: F401
from .chaoxing import ChaoxingAdapter
from .yuketang import YuketangAdapter
from .icourse163 import Mooc163Adapter

ALL_ADAPTERS = [
    ChaoxingAdapter,     # 超星学习通
    YuketangAdapter,     # 雨课堂
    Mooc163Adapter,      # 中国大学 MOOC
]

BY_KEY = {a.key: a for a in ALL_ADAPTERS}
