"""机器人界面简体中文（自 5.9.6 起）。

键与 `i18n.EN_STRINGS` 相同；测试会检查是否完整，以及 `{…}` 占位符和
HTML 标签是否与英文原文一致。翻译未经母语者审校，发现问题请告知作者。
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

STRINGS: dict[str, str] = {
    # --- 语言选择 ---
    "lang.ask": "Choose your language / Выберите язык / 请选择语言",
    "lang.saved": "语言已切换为简体中文。",
    "lang.button": "🌍 语言",

    # --- 主菜单 ---
    "menu.locations": "📍 我的地址",
    "menu.weather": "🌤 天气",
    "menu.alerts": "⚙️ 通知",
    "menu.suggest": "📢 推荐信息源",
    "menu.invite": "🔗 邀请",
    "menu.digest": "📰 新闻摘要",
    "menu.sos": "🆘 SOS",
    "menu.assistant": "🧠 AI 助手",
    "menu.manage": "🛠 管理",
    "menu.about": "ℹ️ 关于",
    "menu.history": "📖 历史",
    "menu.media": "🎬 下载视频",
    "menu.partners": "🤝 合作项目",
    "menu.groups": "💬 我们的群聊",
    "groups.title": "💬 <b>我们的群聊</b>",
    "groups.hint": "点按群聊即可打开。部分群需要申请加入——由群管理员审批。",
    "groups.empty": "暂时没有可加入的群聊。",
    "menu.home": "🏠 主菜单",
    "menu.back": "◀️ 返回",

    # --- 链接检查 ---
    "linkcheck.off": "链接检查已关闭。",
    "linkcheck.usage": "🔍 在命令后发送链接：\n"
                       "<code>/check https://example.com/page</code>",
    "linkcheck.working": "⏳ 正在检查链接…",
    "linkcheck.slow_down": "⚠️ 连续检查次数过多，请等待一分钟。",
    "linkcheck.limit": "🔒 今日检查次数已用完"
                       "（每天 200 次）。\n\n订阅可取消限制。"
                       "危险警报始终免费，不受此限制影响。",
    "linkcheck.left": "今日剩余",
    "linkcheck.unlimited": "订阅后检查次数不限。",
    "linkcheck.section": "🔍 <b>链接检查</b>\n\n"
                         "分析地址是否有欺诈迹象：仿冒品牌的相似字符、"
                         "他人域名、跳转、域名年龄、Safe Browsing 名单。",
    "menu.linkcheck": "🔍 检查链接",
    "menu.music": "🎵 音乐",
    "menu.sub_button": "💳 订阅 — 不限次数检查",
    "help.cmd_linkcheck": "/check &lt;链接&gt; — 检查链接是否有诈骗迹象",
    "help.cmd_music": "/music — 音乐与播放列表",

    # --- VPN (5.0) ---
    "menu.vpn": "🔐 VPN",
    "vpn.title": "🔐 <b>VPN</b>",
    "vpn.unavailable": "管理员尚未设置此功能。",
    "vpn.link_button": "📋 订阅链接",
    "vpn.gone": "面板中没有该账户 — 请重新申请访问。",
    "vpn.ask_button": "📨 申请访问",
    "vpn.devices_limit": "📱 每个订阅的设备数：最多 {n} 台",
    "vpn.app_button": "📱 连接应用",
    "vpn.app_nothing": "需要先开通访问权限。",
    "vpn.app_title": "📱 <b>连接应用</b>",
    "vpn.app_code": "验证码：<code>{code}</code>\n一次性，5 分钟内有效。请与服务器地址一起输入 HydraVPN（“机器人账户”）。",
    "vpn.app_server": "服务器地址：<code>{url}</code>",
    "vpn.app_devices": "已连接设备：{n}",
    "vpn.app_revoke": "🔌 断开所有设备",
    "vpn.app_revoked": "已断开设备：{n}",
    "vpn.pending": "⏳ 您的申请已发送，正等待管理员处理。",
    "vpn.denied": "您之前的申请已被拒绝，可以重新提交。",
    "vpn.intro": "VPN 访问权限由管理员发放。"
                 "请提交申请 — 回复会发到这里。",
    "vpn.sent": "申请已发送。",
    "vpn.link_title": "🔐 <b>您的订阅链接</b>",
    "vpn.setup_steps": "<b>连接方法：</b>\n"
                       "1. 安装支持订阅的客户端："
                       "Android 用 HydraVPN 或 v2rayNG，iPhone 用 Streisand 或 Happ，"
                       "电脑用 Hiddify 或 v2rayN。\n"
                       "2. 用上面的链接添加订阅 — "
                       "“从剪贴板导入”或“添加订阅”。\n"
                       "3. 更新订阅并选择服务器。\n\n"
                       "链接就是您的密钥：请勿转发。同一个"
                       "链接可用于您的所有设备。",
    "vpn.key_title": "🔐 <b>您的密钥</b>",
    "vpn.config_title": "🔐 <b>您的配置链接</b>",
    "vpn.key_steps": "<b>连接方法：</b>\n"
                     "1. 安装 Outline Client 或任意 Shadowsocks 客户端。\n"
                     "2. 复制上面的密钥并添加到客户端。\n\n"
                     "密钥就是您的访问权限：请勿转发。",
    "vpn.config_steps": "<b>连接方法：</b>\n"
                        "1. 安装 WireGuard（或 AmneziaWG）。\n"
                        "2. 打开上面的链接并下载配置文件 — "
                        "该链接<b>仅限一次</b>，第二次无法打开。\n"
                        "3. 把文件导入应用。\n\n"
                        "需要再次获取？再点一次按钮，"
                        "机器人会发给您新的链接。",
    "vpn.hydra_button": "⬇️ HydraVPN Android 版",
    "vpn.no_access": "尚未开通访问权限。",
    "vpn.denied_note": "🔐 管理员拒绝了您的 VPN 申请。",
    "vpn.until": "有效期至 {until}（剩余 {left} 天）",
    "vpn.forever": "有效期：长期",
    "vpn.traffic": "流量：已用 {used}，共 {limit}",
    "vpn.traffic_free": "流量：已用 {used}，不限量",
    "vpn.disabled": "⛔ 访问已停用",
    "vpn.buy_button": "💳 购买访问权限",
    "vpn.plans_title": "💳 <b>VPN 套餐</b>\n\n续费保留同一个密钥，"
                       "并把天数加到您的剩余时间上。",
    "vpn.order_title": "🧾 <b>订单</b> <code>{id}</code>",
    "vpn.order_pay": "请用下方按钮支付账单，然后点“我已支付”。",
    "vpn.pay_button": "💳 支付",
    "vpn.paid_button": "✅ 我已支付",
    "vpn.order_manual": "付款由管理员确认。确认后访问信息会立即发到这里。",
    "vpn.cancel_order": "✖️ 取消订单",
    "vpn.order_done": "✅ 已收到付款，访问已开通。",
    "vpn.not_paid": "尚未收到付款。请一分钟后再试。",
    "link.button": "🔗 已关联的网络",
    "link.title": "🔗 <b>已关联的网络</b>",
    "link.intro": "所有网络共用一个账户：地址和设置共享，"
                  "警报也会发到那边。可关联 VK、MAX 和 Discord。",
    "link.linked": "已关联",
    "link.unlink": "✖️ 取消关联",
    "link.get_code": "🔑 获取验证码",
    "link.unlinked": "已取消关联。",
    "link.unavailable": "暂时无法关联。",
    "link.code_any": "您的验证码：{code}\n请在另一个网络里发给机器人 — 在 "
                     "Telegram 中发送 /link {code}，在 VK、MAX 或 Discord 中只发验证码。"
                     "验证码 10 分钟内有效。",
    "link.enter_hint": "<i>在另一个网络收到验证码了？请这样发到这里：</i> "
                       "<code>/link CODE</code>。",
    "link.confirm": "把此账户与拥有 {nets} 的账户关联吗？\n\n"
                    "地址和设置将共享，警报会发到所有已关联的网络。"
                    "如果这个验证码是别人发给您的，请拒绝："
                    "否则对方将获得您的地址。",
    "link.answer": "请回复“是”或“否”。",
    "link.yes": "✅ 关联",
    "link.no": "✖️ 拒绝",
    "link.done": "✅ 账户已关联。地址和设置现已共享，警报会发到所有已关联的网络。"
                 "取消关联请用 /unlink。",
    "link.declined": "好的，账户未关联。",
    "link.notice": "🔗 {net} 已与您的账户关联。如果不是您操作的，"
                   "请取消关联：在该网络里发 /unlink，或在 "
                   "Telegram 机器人设置的“已关联的网络”中操作。",
    "link.unlinked_net": "已取消关联：此账户不再与其他账户相连。",
    "link.not_linked": "此账户未关联任何账户。",
    "text.about": "雷达关注您所在地址的城市威胁与市政故障，"
                  "只发送与之相关的内容。",
    "text.has_addresses": "已设置地址 — 相关警报会发到这里。",
    "text.no_addresses": "还没有地址。添加第一个：/address 街道, 门牌, "
                         "城市 — 或发送地理位置。",
    "text.commands": "/address 街道, 门牌, 城市 — 添加地址\n"
                     "/addresses — 我的地址，/remove N — 删除\n"
                     "/link — 与 Telegram、VK、MAX 或 Discord 关联\n"
                     "/unlink — 取消此账户的关联\n"
                     "/status — 监控是否在运行\n"
                     "/panel — 网页面板登录码（版主）\n"
                     "/lang zh — 简体中文",
    "text.disclaimer": "本系统不能替代官方预警渠道。",
    "text.status_ok": "✅ 监控正在运行。",
    "text.status_bad": "🚨 监控已静默约 {minutes} 分钟。"
                       "已通知管理员。",
    "text.already": "ℹ️ 该地址已保存：{name}。",
    "text.confirm_address": "找到：{place}\n保存此地址吗？请回复“是”或“否”。"
                            "如果不对，请写得更具体：/address 街道, 门牌, 城市。",
    "text.limit": "❌ 已达到地址数量上限（{limit}）。",
    "text.saved": "🏠 地址已保存：{name}。相关警报会发到这里。",
    "text.no_street": "⚠️ 未识别出街道 — 该地址的市政故障警报"
                      "可能不够准确。",
    "text.empty": "还没有地址。/address 街道, 门牌, 城市",
    "text.list": "您的地址：",
    "text.remove_hint": "删除：/remove N",
    "text.geo_failed": "无法识别地址。请稍后再试。",
    "text.not_saved": "好的，未保存。",
    "text.not_found": "未找到地址。请写得更具体：街道, 门牌, 城市 — 或发送"
                      "地理位置。",
    "text.no_such": "没有这个编号。/addresses — 查看列表。",
    "text.removed": "已删除：{name}。",
    "text.lang_set": "回复语言：简体中文。",
    "panel.off": "网页面板已关闭。",
    "panel.denied": "网页面板仅限版主及以上。",
    "panel.code": "网页面板登录码：{code}\n一次性，5 分钟内有效。请在面板登录页面输入。"
                  "如果不是您申请的，请不要理会。",
    "panel.notice": "🔐 有人通过 {net} 申请了网页面板登录码。如果不是"
                    "您本人，请取消该网络的关联（/unlink）。",
    "vpn.gb": "GB",
    "vpn.mb": "MB",

    # --- RustDesk ---
    "menu.rustdesk": "🖥 RustDesk",
    "rustdesk.title": "🖥 <b>RustDesk</b>",
    "rustdesk.info_button": "📋 地址和密钥",
    "rustdesk.conn_button": "🔌 当前连接",
    "rustdesk.info_title": "📋 <b>连接信息</b>",
    "rustdesk.no_subscription": "⭐️ <b>地址和密钥 — 需订阅</b>\n\n"
                                "订阅可使用您自己的 RustDesk 服务器、"
                                "不限量下载视频，并解锁所有摘要主题。"
                                "危险警报始终免费。",
    "manage.chats": "🛡 群聊",
    "rustdesk.setup_steps": "<b>如何添加设备：</b>\n"
                            "1. 安装 RustDesk（下方按钮）。\n"
                            "2. 点 ⚙️ → “网络” → “ID/中继服务器”。\n"
                            "3. 粘贴本消息中的 ID 服务器、中继服务器和密钥。\n"
                            "4. 保存 — 两台设备都要做：发起连接的"
                            "和被连接的。",

    # --- 警报：最重要的部分 ---
    "alert.danger": "危险",
    "alert.utility": "市政设施与故障",
    "alert.all_clear": "警报解除",
    "alert.matched": "匹配的地址",
    "alert.citywide": "全市范围",
    "alert.whitelist.title": "移动网络",
    "alert.whitelist.body": (
        "空袭威胁期间，运营商会切换为白名单模式：只有"
        "政府服务、银行、地图和出租车可用。"
        "即时通讯和社交网络可能打不开。家用宽带"
        "和 Wi-Fi 通常正常。紧急联系请使用电话和短信。"
    ),
    "alert.not_official": "本系统不能替代官方预警渠道。",
    "alert.read_source": "阅读来源",
    "alert.no_ai": "（未使用 AI）",

    # --- 合作项目 ---
    "partners.empty": "列表暂时为空。",
    "partners.promo": "🎁 获取优惠码",
    "partners.promo.issued": "已发放",
    "partners.promo.kept": "该优惠码归您：再次点按会显示同一个。",

    # --- 媒体 ---
    "media.title": "🎬 视频下载",
    "media.prompt": "发送链接 — 我会给出清晰度选项并发送文件。",
    "media.limit": "发送上限",
    "media.quota.left": "今日剩余下载次数",
    "media.quota.spent": "已达每日上限",
    "media.quota.unlimited": "不限量，截至",
    "media.quota.buy": "⭐️ 一个月不限量",
    "media.too_big": "文件超过上限。",
    "media.looking": "🔎 <b>正在查看链接…</b>",
    "media.slow_probe": "❌ 网站在 90 秒内没有响应。",
    "media.pick_quality": "🎯 <b>请选择清晰度：</b>",
    "media.pick_note": "<i>发送上限为 {limit} MB。带 ⚠️ 的选项放不下。</i>",
    "media.btn_text": "📝 描述文字",
    "media.btn_cancel": "❌ 取消",
    "media.cancelled": "下载已取消。",
    "media.busy": "⏳ 已有另一个下载在进行。请稍候 — "
                  "同时下载会使服务器过载。",
    "media.no_file": "❌ 文件未生成。",
    "media.sending": "📤 <b>正在发送到 Telegram…</b>",
    "img.downloading": "🖼 <b>正在下载图片…</b>",
    "img.looking": "🖼 <b>正在查找帖子中的图片…</b>",
    "img.none_found": "🖼 此帖子中没有找到图片。\n"
                      "<i>私密帖子未登录时，浏览器同样看不到。</i>",
    "img.in_post": "帖子中的图片",
    "img.not_sent": "❌ 图片已下载，但无法发送。",
    "zip.too_long": "📏 <b>视频太长，无法作为文件发送"
                    "（{limit} MB），而且没有压缩手段。</b>",
    "zip.full_note": "完整版通过链接提供 — 最大 {gb} GB，保留 {hours} 小时。",
    "zip.offer": "🗜 <b>视频放不下：{size} MB，上限 "
                 "{limit} MB。</b>",
    "zip.free_line": "免费：压缩到 {height}p — 约 {limit} MB，需要 "
                     "<b>{time}</b> — 单板电脑的处理器较弱，压缩"
                     "以低优先级运行，以免耽误警报。",
    "zip.btn_zip": "🗜 压缩到 {height}p（{time}）— 免费",
    "zip.btn_full": "⭐️ 完整版链接 — 最大 {gb} GB",
    "zip.btn_other": "◀️ 选择其他清晰度",
    "zip.running": "🗜 <b>正在压缩到 {height}p</b>",
    "zip.running_pct": "🗜 <b>正在压缩到 {height}p</b> — {pct}%",
    "zip.time_note": "需要 {time}。期间警报照常运行。",
    "sub.needed_title": "⭐️ <b>完整版需要订阅</b>",
    "sub.needed_line": "完整文件，{label} 清晰度，通过链接提供 — 最大 "
                       "{gb} GB，保留 {hours} 小时。",
    "sub.needed_note": "订阅可使用此功能、不限每日次数下载视频，"
                       "并解锁所有新闻摘要主题。危险警报"
                       "始终免费。",
    "sub.btn": "💳 订阅",
    "linkcheck.choice": "🔗 <b>要如何处理这个链接？</b>",
    "linkcheck.btn_check": "🔍 检查",
    "linkcheck.btn_video": "🎬 下载视频",
    "linkcheck.btn_images": "🖼 帖子中的图片",
    "linkcheck.btn_nothing": "❌ 不处理",
    "drop.preparing": "🔗 <b>正在准备下载链接…</b>",
    "drop.ready_size": "大小",
    "drop.ready_note": "超过 Telegram 的限制，因此文件以链接形式提供。",
    "drop.download": "⬇️ 下载文件",
    "drop.ttl": "<i>链接保留 {hours} 小时，之后文件会从服务器删除。</i>",
    "drop.too_large": "⚠️ 文件超过 {gb} GB — 此类文件不通过链接提供。"
                      "请选择较低的清晰度。",
    "drop.over_limit": "⚠️ <b>文件超过 Telegram 的限制。</b>",

    # --- 摘要 ---
    "digest.title": "新闻摘要",
    "digest.buy": "⭐️ 订阅",
    "digest.sources": "来源",

    "digest.staff": "🛠 <b>工作人员权限</b> — 所有主题开放，无需付费。",
    "digest.extra_days": "额外已付费天数",
    "digest.paid": "订阅有效，剩余天数",
    "digest.covers_media": "同时取消每日视频下载次数限制。",
    "digest.free": "免费主题",
    "digest.upsell": "订阅可解锁全部主题。",
    "digest.topics": "您的主题",
    "digest.no_topics": "未选择主题 — 将不会收到摘要。",
    "digest.times": "发送时间",
    "digest.free_always": (
        "危险警报、市政设施、天气和 SOS 始终免费，"
        "不依赖订阅。"
    ),

    # --- 主题名称 ---
    "topic.city": "城市与政府",
    "topic.incidents": "事件",
    "topic.utilities": "市政与基础设施",
    "topic.transport": "交通",
    "topic.health": "健康",
    "topic.education": "教育",
    "topic.social": "社会",
    "topic.economy": "经济与商业",
    "topic.culture": "文化与休闲",
    "topic.weather_nature": "天气与自然",
    "topic.region": "地区",
    "topic.federal": "全国",
    "topic.it": "IT 与游戏",
    "topic.science": "科学与技术",
    "topic.sport": "体育",
    "topic.hobby": "爱好与汽车",
    "topic.cinema": "电影与剧集",
    "topic.finance": "金融与市场",

    # --- 天气 ---
    "weather.feels": "体感",
    "weather.wind": "风",
    "weather.humidity": "湿度",
    "weather.sunrise": "日出",
    "weather.sunset": "日落",
    "weather.now": "现在",
    "weather.today": "今天",
    "weather.tomorrow": "明天",
    "weather.hour_suffix": "时",
    "weather.error.no_coords": "没有坐标 — 请重新发送位置",
    "weather.error.bad_status": "天气服务返回了代码",
    "weather.error.fetch_failed": "获取天气失败",
    "weather.error.no_data": "没有天气数据",

    # --- 天气：WMO 代码说明 ---
    "weather.wmo.0": "晴",
    "weather.wmo.1": "大部晴朗",
    "weather.wmo.2": "多云",
    "weather.wmo.3": "阴",
    "weather.wmo.45": "雾",
    "weather.wmo.48": "雾凇",
    "weather.wmo.51": "小毛毛雨",
    "weather.wmo.53": "毛毛雨",
    "weather.wmo.55": "浓毛毛雨",
    "weather.wmo.56": "小冻毛毛雨",
    "weather.wmo.57": "浓冻毛毛雨",
    "weather.wmo.61": "小雨",
    "weather.wmo.63": "雨",
    "weather.wmo.65": "大雨",
    "weather.wmo.66": "小冻雨",
    "weather.wmo.67": "强冻雨",
    "weather.wmo.71": "小雪",
    "weather.wmo.73": "雪",
    "weather.wmo.75": "大雪",
    "weather.wmo.77": "米雪",
    "weather.wmo.80": "小阵雨",
    "weather.wmo.81": "阵雨",
    "weather.wmo.82": "强阵雨",
    "weather.wmo.85": "小阵雪",
    "weather.wmo.86": "大阵雪",
    "weather.wmo.95": "雷暴",
    "weather.wmo.96": "雷暴伴小冰雹",
    "weather.wmo.99": "雷暴伴大冰雹",

    # --- 天气图片 ---
    "weather.image.title": "天气",
    "weather.image.feels_like": "体感",
    "weather.image.gusts_to": "阵风可达",
    "weather.image.humidity": "湿度",
    "weather.image.mmhg": "毫米汞柱",
    "weather.image.ms": "米/秒",
    "weather.image.now": "现在",
    "weather.sky.night": "夜",
    "weather.sky.dawn": "黎明",
    "weather.sky.day": "白天",
    "weather.sky.dusk": "黄昏",

    # --- 风向 ---
    "wind.n": "北风",
    "wind.ne": "东北风",
    "wind.e": "东风",
    "wind.se": "东南风",
    "wind.s": "南风",
    "wind.sw": "西南风",
    "wind.w": "西风",
    "wind.nw": "西北风",

    # --- 风力 ---
    "wind.calm": "无风",
    "wind.light": "微风",
    "wind.moderate": "和风",
    "wind.fresh": "清劲风",
    "wind.strong": "强风",
    "wind.storm": "风暴",

    # --- 月相 ---
    "moon.new": "新月",
    "moon.waxing_crescent": "娥眉月",
    "moon.first_quarter": "上弦月",
    "moon.waxing_gibbous": "盈凸月",
    "moon.full": "满月",
    "moon.waning_gibbous": "亏凸月",
    "moon.last_quarter": "下弦月",
    "moon.waning_crescent": "残月",

    # --- SOS ---
    "sos.overview": "🆘 紧急求助",
    "sos.no_contacts": (
        "还没有可信联系人。添加一个人，您按下 SOS 按钮时，"
        "他会收到您的位置。"
    ),
    "sos.contacts": "可信联系人",
    "sos.ready": "可接收信号",
    "sos.pending": "未确认 — 尚未打开机器人",
    "sos.none_confirmed": (
        "⚠️ 没有已确认的联系人。Telegram 不允许机器人先发消息 — "
        "联系人必须通过您的链接打开机器人。在此之前，信号"
        "会发给系统管理员。"
    ),
    "sos.add": "➕ 添加联系人",
    "sos.fire": "🆘 发送信号",
    "sos.title": "🆘 SOS",
    "sos.send": "🆘 发送警报",
    "sos.stop": "✅ 取消警报",
    "sos.sent": "警报已发给您的联系人。",

    # --- 历史 ---
    "history.title": "📖 历史",
    "history.empty": "最近 30 天没有给您发送任何内容。",
    "history.note": (
        "这并不意味着机器人没有工作：而是说明"
        "您的地址附近没有发生事件。"
    ),
    "history.trimmed": "显示最近的记录。",

    # --- 设置 ---
    "settings.title": "⚙️ 通知",
    "settings.prompt": "选择要接收的事件和天气模式。",
    "settings.quiet": "免打扰时段",
    "settings.weather_mode": "天气模式",
    "settings.weather_view": "天气显示方式",

    # --- 通用 ---
    "common.cancelled": "✅ 已取消。",
    "common.only_superadmin": "⛔️ 仅限超级管理员。",
    "common.error": "出了点问题 — 请稍后再试。",
    "common.insufficient_rights": "权限不足。",

    # --- 帮助 (/help) ---
    "help.title": "使用说明",
    "help.step1": (
        "1. 发送您的位置（回形针 → 位置）— 即可添加一个地址。"
        "地址数量不限。"
    ),
    "help.step2": (
        "2. 军事威胁（无人机、导弹危险）会以一条全市范围的消息"
        "发来，涵盖您在该城市的所有地址。"
    ),
    "help.step3": "3. 市政故障按地址查找 — 街道和门牌号。",
    "help.step4": "4. 彼此距离不足 1 公里的地址会合并为一份汇总。",
    "help.commands_title": "命令",
    "help.cmd_basic": "/menu — 菜单 - /id — 您的 ID 和角色 - /cancel — 重置输入",
    "help.cmd_partner": "/partner — 合作项目",
    "help.cmd_assistant": "/ai &lt;问题&gt; — AI 助手 - /aireset — 清除上下文",
    "help.cmd_quota": "/quota — Gemini 配额使用情况",
    "help.cmd_admin1": "/stats — 系统统计 - /models — Gemini 模型",
    "help.cmd_admin2": "/digest — 新闻摘要 - /sos — SOS 按钮",
    "help.cmd_admin3": "/media — 通过链接下载视频 - /panel — 网页面板",
    "help.cmd_super1": (
        "/features — 系统功能\n"
        "/logs — 日志 - /logtail — 最近几行 - /logclear — 清除"
    ),
    "help.cmd_super2": "/perf — 周期耗时与资源 - /bench — AI 服务商对比",
    "help.cmd_super3": (
        "/keys — 密钥与设置 - /provider — 选择服务商\n"
        "/network — 网络与代理 - /backup — 备份"
    ),

    # --- 欢迎语与通用标题 ---
    "app.title": "雷达",
    "greeting.assistant": (
        "🧠 <i>AI 助手已启用：直接在聊天中提问，"
        "或使用 /ai。</i>"
    ),
    "greeting.no_key": (
        "⚠️ <i>未设置 GEMINI_API_KEY — 当前使用不带 AI 的"
        "启发式分析。</i>"
    ),
    "restart.missed": (
        "🛠 <b>机器人因维护暂停了服务</b>\n\n"
        "您的消息在重启期间到达，未被处理"
        " — 请重新发送。\n\n"
        "<i>危险警报没有丢失：每次重启后机器人都会重新读取"
        "自己的信息源。</i>"
    ),
    "common.your_id": "🆔 您的 ID",
    "common.role": "角色",
    "common.pinned_buttons": (
        "<b>菜单</b>和 <b>HydraSite</b> 按钮固定在"
        "输入框下方。"
    ),

    # --- 角色 ---
    "role.user": "👤 用户",
    "role.moderator": "🛡 版主",
    "role.admin": "👑 管理员",
    "role.superadmin": "⭐️ 超级管理员",

    # --- 警报类别 ---
    "category.bpla": "无人机 / 导弹危险",
    "category.mchs": "应急部门警报",
    "category.jkh": "市政设施与网络故障",
    "category.whitelist": "提醒白名单模式",

    # --- 设置：天气 ---
    "settings.weather_button": "🌤 天气",
    "settings.weather_mode.title": "⏱ <b>天气模式</b>",
    "settings.weather_mode.prompt": "选择间隔，或设置自己的数值。",
    "settings.weather.off": "关闭",
    "settings.weather.every": "每",
    "settings.weather.at": "于",
    "settings.weather.minutes": "分钟",
    "settings.weather.hours_short": "小时",
    "settings.weather.hour": "每小时",
    "settings.weather.hours3": "每 3 小时",
    "settings.weather.hours6": "每 6 小时",
    "settings.weather.disable": "关闭",
    "settings.weather.own_interval": "自定义间隔",
    "settings.weather.fixed_time": "固定时间",
    "settings.weather.disabled": "天气已关闭",
    "settings.weather.interval_set": "间隔",
    "settings.weather.ask_time": (
        "⏰ 请按 <code>HH:MM</code> 格式输入时间（例如 08:30）："
    ),
    "settings.weather.ask_interval": (
        "⏱ 请输入间隔：<code>45</code>（分钟）或 <code>2h</code>（小时）："
    ),
    "settings.weather.bad_time": (
        "❌ 格式不对。示例：<code>08:30</code>。/cancel 取消。"
    ),
    "settings.weather.bad_interval": (
        "❌ 请输入分钟数，或类似 <code>2h</code> 的值。"
    ),
    "settings.weather.range": "❌ 间隔必须在 15 分钟到 24 小时之间。",
    "settings.weather.daily_at": "✅ 天气将每天发送，时间为",
    "settings.weather.interval_ok": "✅ 间隔",

    # --- 设置：天气显示方式 ---
    "settings.wformat.title": "🖼 <b>天气汇总格式</b>",
    "settings.wformat.now": "当前",
    "settings.wformat.text": "文字",
    "settings.wformat.image": "图片",
    "settings.wformat.image_all": "图片（对所有人）",
    "settings.wformat.as_text": "📄 文字",
    "settings.wformat.as_image": "🖼 图片",
    "settings.wformat.forced": (
        "个人选择暂时不可用。管理员取消全局设置后，"
        "您之前的选择会恢复。"
    ),
    "settings.wformat.why": (
        "图片更直观，但在移动网络受限时无法加载 — 而本系统"
        "正是为这种情况而设。文字总能送达。"
    ),
    "settings.wformat.off": "图片形式的天气已关闭。",
    "settings.wformat.label": "🖼 天气格式",

    # --- 设置：免打扰时段 ---
    "settings.quiet.title": "🌙 <b>免打扰时段</b>",
    "settings.quiet.label": "🌙 免打扰时段",
    "settings.quiet.prompt": (
        "发送一个时间段，例如 <code>23:00-07:00</code>。\n"
        "发送“-”可关闭免打扰时段。"
    ),
    "settings.quiet.always": (
        "<b>军事威胁和紧急警报始终会送达</b> — "
        "只暂缓市政和天气消息。"
    ),
    "settings.quiet.bad_format": (
        "❌ 格式：<code>23:00-07:00</code>。“-”表示关闭。/cancel 取消。"
    ),
    "settings.quiet.cleared": "✅ 免打扰时段已关闭。",
    "settings.quiet.set": "✅ 免打扰时段",
    "settings.quiet.note": (
        "<i>军事威胁和紧急警报在任何时间都会送达。</i>"
    ),
    "settings.quiet.disabled": "免打扰时段已关闭。",
    "settings.quiet.none": "关闭",

    # --- 推荐信息源 ---
    "suggest.title": "📢 <b>推荐信息源</b>",
    "suggest.prompt": (
        "发送公开频道的用户名，例如 "
        "<code>saratovzhkh</code>，或其链接。"
    ),
    "suggest.thematic": (
        "<i>主题频道也可以 — 游戏、体育、科学：它们会进入"
        "新闻摘要。</i>"
    ),
    "suggest.closed": (
        "目前不接受推荐 — 信息源列表由管理方维护。"
    ),
    "suggest.sent": "✅ 频道 @{channel} 已发送给版主。",
    "suggest.already": "ℹ️ 该信息源已在列表或队列中。",
    "suggest.bad": "❌ 频道用户名无效。",

    # --- 通用（续） ---
    "common.on": "已启用",
    "common.off": "已停用",
    "common.user_not_found": "未找到用户。",
    "common.cancel": "取消",
    "common.back": "◀️ 返回",
    "common.cancel_x": "❌ 取消",
    "common.yes": "✅ 是",

    # --- 版主界面：用户（自 4.9.9.3） ---
    "users.no_rights": "权限不足。",
    "users.not_found": "未找到用户。",
    "users.list_title": "👥 <b>用户</b> — 共 {total} 位（第 {page}/{pages} 页）",
    "users.locations_count": "地址：{count}",
    "users.open_hint": "点按用户可打开其卡片。",
    "users.none": "无",
    "users.card_title": "👤 <b>用户</b>",
    "users.nick": "用户名",
    "users.role": "角色",
    "users.locations": "地址",
    "users.categories": "警报类别",
    "users.weather": "天气",
    "users.settings_title": "⚙️ <b>用户的警报</b>",
    "users.self_role": "不能更改自己的角色。",
    "users.role_denied": "权限不足，无法设置此角色。",
    "users.role_changed": "角色已更改：{role}",
    "users.role_notice": "ℹ️ 您在“雷达”中的角色已更改为 {role}。",
    "users.delete_admins": "删除功能仅限管理员。",
    "users.delete_ask": "⚠️ 删除用户 {id}（{role}）及其所有地址？",
    "users.deleted_short": "用户已删除",
    "users.deleted": "✅ 用户 {id} 已删除。",
    "users.invite_title": "🔗 <b>邀请链接</b>",
    "users.invite_hint": "通过它加入的人获得“用户”角色：自己的"
                         "地址和警报。只有管理方可以提升角色。",
    "users.default_city": "默认城市是 {city}。",
    "users.add_loc_title": "➕ <b>为以下用户添加地址</b>",
    "users.add_loc_prompt": "以文字发送地址，例如 "
                            "<code>恰帕耶夫街 12 号</code>。",
    "users.add_loc_geo": "也可以转发或发送位置 — 它会"
                         "添加给该用户。",
    "users.cancel_hint": "/cancel — 取消。",
    "users.loc_added_notice": "📍 管理员为您添加了一个地址：{name}。\n"
                              "它的警报已开启 — 可在“我的地址”中管理。",
    "users.loc_added": "✅ 地址 {name} 已添加给用户 {id}。",
    "users.no_street": "未识别出街道 — 该地址的市政故障"
                       "警报可能不够准确。",
    "users.back_to_user": "◀️ 返回用户",
    "users.gone_or_denied": "未找到用户或权限不足。",
    "users.address_not_found": "未找到地址。请写得更具体 — 例如 "
                               "<code>萨拉托夫, 恰帕耶夫街 12 号</code>。"
                               "/cancel — 取消。",
    "users.variants": "🔎 <b>找到匹配项：{count}</b>",
    "users.pick_one": "请选择正确的一项。",
    "users.list_stale": "列表已过期，请重新开始。",
    "users.adding": "正在添加…",

    # --- 版主键盘（自 4.9.9.3） ---
    "ucard.locs": "📍 地址",
    "ucard.alerts": "⚙️ 警报",
    "ucard.add_loc": "➕ 添加地址",
    "ucard.weather": "🌤 用户的天气",
    "ucard.delete": "🔨 删除用户",
    "ucard.back": "◀️ 返回列表",
    "ucard.locs_short": "址",
    "mod.queue": "📥 信息源队列",
    "mod.list": "📋 信息源列表",
    "mod.check": "🔍 检查可用性",
    "mod.add_channel": "➕ 添加频道",
    "mod.add_rss": "🌐 添加新闻 RSS 订阅源",
    "mod.export": "⬇️ 下载列表",
    "mod.import": "⬆️ 上传列表",
    "mod.back": "◀️ 返回管理",
    "mod.approve": "✅ 接受",
    "mod.reject": "❌ 拒绝",

    # --- 受管理的群聊，管理方部分（自 4.9.9.3） ---
    "chats.title": "🛡 <b>受管理的群聊</b>",
    "chats.mod_on": "管理已开启",
    "chats.mod_off": "管理已关闭",
    "chats.tap_hint": "点按群组即可打开。",
    "chats.mod_disabled": "管理已关闭 — 请在“功能”中开启。",
    "chats.admins_only": "仅限管理方。",
    "chats.add_hint": (
        "🛡 <b>受管理的群聊</b>\n\n"
        "还没有群组。\n\n"
        "<b>如何添加机器人：</b>\n"
        "1. 打开群组 → “成员” → “添加”。\n"
        "2. 按名称找到机器人并添加。\n"
        "3. 在群里将其设为管理员，并开启"
        "<b>“删除消息”</b>和<b>“封禁用户”</b>。\n"
        "4. 在群里发送 <code>/modon</code> — 群聊会出现在这里。\n\n"
        "<b>机器人已经在群里了？</b>那就无需再添加："
        "确认它是具备这些权限的管理员，然后在群里发送 "
        "<code>/modon</code>。机器人之前被加入的群组"
        "不会自行上报 — Telegram 只会把变化通知机器人。\n\n"
        "<i>无需在 @BotFather 中更改隐私模式：管理员"
        "本来就会收到所有消息。机器人不会向已经在群里的人"
        "发送任何内容 — 检查只针对开启之后加入的人。</i>"
    ),

    # --- 版主界面：信息源（自 4.9.9.3） ---
    "src.menu_text": "📡 <b>信息源</b>\n\n在这里添加频道和订阅源、"
                     "检查其可用性，并审核用户的推荐。",
    "src.queue_empty": "📥 队列为空。",
    "src.queue_item": "📥 <b>队列：{count}</b>\n正在审核：{channel}",
    "src.approved": "已接受",
    "src.rejected": "已拒绝",
    "src.empty": "— 空 —",
    "src.list_channels": "📋 <b>Telegram 频道</b>",
    "src.list_feeds": "🌐 <b>RSS 订阅源</b>",
    "src.add_prompt": "➕ 发送频道用户名。可一次发送多个 — 用"
                      "逗号或换行分隔。",
    "src.added": "✅ 已添加：",
    "src.skipped": "⚠️ 已跳过：",
    "src.nothing_added": "未添加任何内容",
    "src.rss_prompt": "🌐 发送新闻或官方 RSS 订阅源的地址"
                      "（例如 <code>https://example.ru/rss</code>）。",
    "src.feeds_added": "✅ 已添加的订阅源：",
    "src.no_valid": "⚠️ 未找到有效地址。",
    "src.export_off": "信息源导出已关闭。",
    "src.preparing": "正在准备文件…",
    "src.import_off": "信息源导入已关闭。",
    "src.import_admins": "导入功能仅限管理员。",
    "src.import_denied": "⛔️ 导入信息源仅限管理员。",
    "src.none": "没有信息源。",
    "src.check_start": "开始检查…",
    "src.checking": "🔍 正在检查信息源：<b>{total}</b>…",
    "src.check_denied": "⛔️ 检查信息源仅限版主及以上。",
    "src.drop_hint": "不可用的信息源可用下方按钮移除。",
    "src.drop_button": "🗑 移除不可用项（{count}）",
    "src.stale": "列表已过期 — 请重新运行检查。",
    "src.removed_short": "已移除信息源：{count}",
    "src.removed": "🗑 已移除不可用的信息源：<b>{removed}</b>。\n"
                   "剩余：频道 {channels}，订阅源 {feeds}。",

    # --- “管理”部分 ---
    "manage.sources": "📡 信息源",
    "manage.users": "👥 用户",
    "manage.stats": "📊 统计",
    "manage.metrics": "🩺 指标与健康状况",
    "manage.links": "🔗 链接",
    "manage.features": "⚙️ 功能",
    "manage.keys": "🔑 访问密钥",
    "manage.ai": "🧠 AI 管理",
    "manage.backups": "💾 备份",
    "manage.network": "🌐 网络访问",
    "manage.logs": "📋 日志",
    "manage.panel": "🖥 网页面板",
    "manage.role_line": "您的角色",
    "manage.all_sections": "所有部分均可使用，包括访问密钥和日志。",
    "manage.admin_sections": "可使用信息源、用户、统计、链接和邀请。",
    "manage.mod_sections": "可编辑信息源和用户设置。",
    # --- 代码用到但词典里缺少的键（自 5.9.6） ---
    "img.too_slow": "🖼 站点两分钟内没有提供图片 — 已停止。\n"
                    "<i>帖子已关闭，或站点对陌生访客限速时会这样。请稍后再试。</i>",
    "settings.back": "◀️ 返回设置",
    "settings.tz.whole": "◀️ 整点时区",
    "settings.tz.fractional": "⏱ 半小时时区",
    "settings.tz.bad": "无法识别该时区。",
    "settings.tz.now": "当前",
    "settings.tz.saved": "时区",
    "settings.tz.title": "🕓 <b>时区</b>",
    "settings.tz.prompt": "偏移量以 UTC 为准。免打扰时段、天气时间和摘要发送"
                          "都按您在此选择的时区计算。",
}
