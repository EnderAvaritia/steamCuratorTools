"""Built-in email templates and safe placeholder rendering."""

from __future__ import annotations

import re
from collections.abc import Mapping

templateKinds = ("subject", "from", "body")

defaultTemplates: dict[str, str] = {
    "subject": "关于您的游戏 {game_name} ({appid}) 的合作咨询",
    "from": "ETC",
    "body": """尊敬的 {publisher_name}，

您好！

我是一名独立游戏开发者/发行商，对贵公司在 Steam 上发行的游戏《{game_name}》非常感兴趣。
这款游戏（AppID: {appid}）给我留下了深刻印象。

我目前正在开发一款名为 [您的游戏名称] 的游戏，它是一款 [游戏类型]，
拥有 [核心玩法特点] 和 [独特卖点]。
我相信这款游戏与贵公司的发行理念/游戏组合非常契合。

您可以在这里查看更多关于我的游戏的信息：
[您的游戏链接，例如 Steam 商店页面、预告片、Demo 链接等]

我非常希望能有机会与您探讨潜在的合作机会，例如发行、市场推广或其他形式的合作。

期待您的回复。

此致，
[您的姓名/公司名称]
[您的联系方式/邮箱]
[您的网站/社交媒体链接]

Steam URL(s) for reference:
{steam_url}
""",
}

_placeholderPattern = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def renderTemplate(template: str, values: Mapping[str, object]) -> str:
    """Replace ``{name}`` placeholders without raising on unknown keys.

    ``str.format`` raises for unknown placeholders and for literal braces in
    user-written templates (common in JSON snippets). Only word-shaped
    placeholders are substituted here; everything else is left untouched.
    """

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            return match.group(0)
        return str(values[key])

    return _placeholderPattern.sub(replace, template)