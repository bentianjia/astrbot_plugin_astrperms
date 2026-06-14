"""
AstrPerms — LuckPerms 风格权限管理插件 for AstrBot

语法与 Minecraft LuckPerms 保持一致。

命令参考:
  /lp user <qq> permission set <node> true|false
  /lp user <qq> permission unset <node>
  /lp user <qq> permission info
  /lp user <qq> parent add <group>
  /lp user <qq> parent remove <group>
  /lp user <qq> parent set <group>
  /lp user <qq> parent clear

  /lp group <group> permission set <node> true|false
  /lp group <group> permission unset <node>
  /lp group <group> permission info
  /lp group <group> parent add <group>
  /lp group <group> parent remove <group>
  /lp group <group> create
  /lp group <group> delete
  /lp group <group> rename <new>
  /lp group <group> clone <new>
  /lp group <group> listmembers
  /lp group list

  /lp search [query]
  /lp editor
  /lp export
  /lp sync
  /lp info
  /lp verbose on|off

权限解析优先级（从高到低）:
  1. 用户显式权限
  2. 用户所属组的权限 (任意组 true 优先)
  3. 用户所属组的父组权限 (递归继承)
  4. 默认模式 (config: default_mode = allow / deny)
"""

import json
from typing import Any, Dict, List, Optional, Set, Tuple

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.event.filter import EventMessageType, PermissionType
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

# ──────────────────────────────────────────────
#  常量
# ──────────────────────────────────────────────
KV_KEY = "astrperms_data"
DEFAULT_DATA: Dict[str, Any] = {
    "users": {},
    "groups": {},
}

# LuckPerms 风格消息前缀
LP_PREFIX = "&7[&bLP&7] &r"  # (在 AstrBot 中用纯文本模拟)


def _lp(msg: str) -> str:
    """包装 LuckPerms 风格输出"""
    return f"[LP] {msg}"


# ══════════════════════════════════════════════
@register("astrperms", "Claude",
          "类似 LuckPerms 的权限管理插件，语法与 LP 一致，自动发现已安装插件的指令",
          "1.0.0", "")
class AstrPerms(Star):
    """
    AstrPerms — 全局权限管理插件

    权限在所有群聊、所有平台统一生效。
    支持 LuckPerms 命令语法，自动发现 AstrBot 已注册的指令。
    """

    def __init__(self, context: Context) -> None:
        super().__init__(context)
        self._data_cache: Optional[Dict[str, Any]] = None
        self._commands_cache: Optional[List[str]] = None
        self._verbose: bool = False

    # ══════════════════════════════════════════
    #  指令自动发现
    # ══════════════════════════════════════════

    def _discover_commands(self, force: bool = False) -> List[str]:
        """
        扫描 star_handlers_registry，自动发现所有已注册的指令。
        结果会被缓存，force=True 强制重新扫描。

        发现策略（按优先级尝试）:
          1. star_handlers_registry (AstrBot v4.x 内部 API)
          2. 遍历 _handlers 属性
          3. context.get_all_stars() (公开 API)
        """
        if self._commands_cache is not None and not force:
            return self._commands_cache

        commands: Set[str] = set()

        # ── 策略 1: star_handlers_registry ──
        try:
            from astrbot.core.star.star_handler import star_handlers_registry

            # 尝试不同的 EventType
            for event_type_name in (
                "AdapterMessageEvent",
                "ON_ADAPTER_MESSAGE_EVENT",
                "ON_MESSAGE",
                "ON_LLM_RESPONSE",
            ):
                try:
                    handlers = star_handlers_registry.get_handlers_by_event_type(
                        event_type_name
                    )
                    if handlers:
                        for h in handlers:
                            for f in getattr(h, "event_filters", []):
                                cmd = self._extract_command_from_filter(f)
                                if cmd:
                                    commands.add(cmd)
                except Exception:
                    pass

            # 遍历内部 handler 列表作为兜底
            all_handlers = getattr(star_handlers_registry, "_handlers", [])
            if not all_handlers:
                all_handlers = getattr(
                    star_handlers_registry, "star_handlers_map", {}
                ).values()
            for h in all_handlers:
                for f in getattr(h, "event_filters", []):
                    cmd = self._extract_command_from_filter(f)
                    if cmd:
                        commands.add(cmd)

        except ImportError:
            if self._verbose:
                logger.info("[AstrPerms] star_handlers_registry 不可用，尝试备选方案")
        except Exception as e:
            if self._verbose:
                logger.info(f"[AstrPerms] 策略1异常: {e}")

        # ── 策略 2: context.get_all_stars() ──
        if not commands:
            try:
                stars = self.context.get_all_stars()
                for star_meta in stars:
                    # star_handler_full_names: list of "module.method" strings
                    full_names = getattr(
                        star_meta, "star_handler_full_names", []
                    )
                    for name in full_names:
                        # handler_full_name 格式如 "astrbot_plugin_xxx_main_method"
                        # 最后一个 _ 之后的部分通常是方法名
                        # 去掉常见前缀
                        method = name.rsplit("_", 1)[-1] if "_" in name else name
                        if method and not method.startswith("on_") and len(method) >= 2:
                            pass  # 方法名不一定是命令名，跳过
            except Exception as e:
                if self._verbose:
                    logger.info(f"[AstrPerms] 策略2异常: {e}")

        # ── 策略 3: 遍历所有已注册的 star 实例 ──
        if not commands:
            try:
                stars = self.context.get_all_stars()
                for star_meta in stars:
                    # 尝试获取 star 实例的方法
                    star_name = getattr(star_meta, "name", "")
                    # 检查 star 中注册的命令处理器
                    try:
                        registered = self.context.get_registered_star(star_name)
                        if registered:
                            for attr_name in dir(registered):
                                if not attr_name.startswith("_"):
                                    attr = getattr(registered, attr_name)
                                    if callable(attr):
                                        # 检查是否有 command filter
                                        if hasattr(attr, "__wrapped__"):
                                            pass
                    except Exception:
                        pass
            except Exception as e:
                if self._verbose:
                    logger.info(f"[AstrPerms] 策略3异常: {e}")

        # 始终包含 lp 自身
        commands.add("lp")

        result = sorted(commands)
        self._commands_cache = result
        if self._verbose:
            logger.info(f"[AstrPerms] 发现 {len(result)} 个指令: {result}")
        return result

    @staticmethod
    def _extract_command_from_filter(f: Any) -> Optional[str]:
        """从 HandlerFilter 中提取命令名"""
        fname = type(f).__name__
        if fname == 'CommandFilter':
            # CommandFilter 有 command_name 属性
            cmd = getattr(f, 'command_name', None)
            if cmd:
                return str(cmd)
        # 可能还有其他 filter 类型
        return None

    def _suggest_commands(self, query: str = "", limit: int = 20) -> List[str]:
        """搜索匹配的指令名"""
        all_cmds = self._discover_commands()
        query_lower = query.lower() if query else ""
        if not query_lower:
            return all_cmds[:limit]
        # 模糊匹配
        matched = [c for c in all_cmds if query_lower in c.lower()]
        return matched[:limit]

    # ══════════════════════════════════════════
    #  数据持久化
    # ══════════════════════════════════════════

    async def _load_data(self) -> Dict[str, Any]:
        if self._data_cache is not None:
            return self._data_cache
        raw = await self.get_kv_data(KV_KEY, None)
        if raw is None:
            self._data_cache = json.loads(json.dumps(DEFAULT_DATA))
            await self._save_data(self._data_cache)
        else:
            self._data_cache = raw if isinstance(raw, dict) else json.loads(str(raw))
        # 兼容旧数据
        if "users" not in self._data_cache:
            self._data_cache["users"] = {}
        if "groups" not in self._data_cache:
            self._data_cache["groups"] = {}
        return self._data_cache

    async def _save_data(self, data: Dict[str, Any]) -> None:
        self._data_cache = data
        await self.put_kv_data(KV_KEY, data)

    async def _invalidate_cache(self) -> None:
        self._data_cache = None
        self._commands_cache = None

    # ══════════════════════════════════════════
    #  配置
    # ══════════════════════════════════════════

    def _get_default_mode(self) -> str:
        try:
            cfg = self.context.get_config()
            if cfg and "default_mode" in cfg:
                return str(cfg["default_mode"])
        except Exception:
            pass
        return "allow"

    def _is_admin_bypass(self) -> bool:
        try:
            cfg = self.context.get_config()
            if cfg and "admin_bypass" in cfg:
                return bool(cfg["admin_bypass"])
        except Exception:
            pass
        return True

    # ══════════════════════════════════════════
    #  权限核心逻辑
    # ══════════════════════════════════════════

    def _resolve_group_permission(
        self,
        group_name: str,
        node: str,
        groups: Dict[str, Any],
        visited: Optional[set] = None,
    ) -> Optional[bool]:
        """
        递归解析组权限（含父组继承）。
        返回值: True=允许, False=拒绝, None=未设置
        """
        if visited is None:
            visited = set()
        if group_name in visited:
            return None  # 避免循环引用
        visited.add(group_name)

        group = groups.get(group_name)
        if not group:
            return None

        # 本组权限
        perms = group.get("permissions", {})
        if node in perms:
            return bool(perms[node])
        if "*" in perms:
            return bool(perms["*"])

        # 父组继承
        parents = group.get("parents", [])
        for pname in parents:
            result = self._resolve_group_permission(pname, node, groups, visited)
            if result is True:
                return True
            if result is False:
                return False

        return None

    async def _get_effective_permission(self, user_id: str, node: str) -> Optional[bool]:
        """
        查询用户对某权限节点的有效权限。

        优先级:
          1. 用户显式权限
          2. 用户所属组权限（含父组递归继承，任意组 true 优先）
          3. 默认模式
        """
        data = await self._load_data()
        users = data.get("users", {})
        groups = data.get("groups", {})

        user_entry = users.get(str(user_id))
        if user_entry:
            # 用户显式权限 — 最高优先级
            perms = user_entry.get("permissions", {})
            if node in perms:
                return bool(perms[node])
            if "*" in perms:
                return bool(perms["*"])

        # 组权限
        if user_entry:
            user_groups = user_entry.get("groups", [])
            best: Optional[bool] = None  # None < False < True
            for gname in user_groups:
                result = self._resolve_group_permission(gname, node, groups)
                if result is True:
                    return True
                if result is False:
                    best = False
            return best

        return None

    async def check_permission(self, user_id: str, node: str) -> bool:
        """
        公开 API: 检查用户权限。
        """
        effective = await self._get_effective_permission(user_id, node)
        if effective is not None:
            return effective
        return self._get_default_mode() == "allow"

    def _ensure_user(self, data: Dict[str, Any], user_id: str) -> None:
        if user_id not in data["users"]:
            data["users"][user_id] = {"permissions": {}, "groups": []}

    # ══════════════════════════════════════════
    #  管理员判断
    # ══════════════════════════════════════════

    async def _is_admin(self, event: AstrMessageEvent) -> bool:
        try:
            sender_id = str(event.get_sender_id())
            admin_ids = getattr(self.context, "admin_ids", [])
            if callable(admin_ids):
                admin_ids = admin_ids()
            if isinstance(admin_ids, (list, set, tuple)):
                return sender_id in [str(x) for x in admin_ids]
        except Exception:
            pass
        return False

    # ══════════════════════════════════════════
    #  权限拦截: on_decorating_result
    # ══════════════════════════════════════════

    @filter.on_decorating_result()
    async def on_decorating_result(self, event: AstrMessageEvent):
        """在消息发送前检查权限，拒绝时替换返回内容。"""
        try:
            msg = event.message_str.strip() if event.message_str else ""
        except Exception:
            return
        if not msg.startswith("/"):
            return

        cmd = msg[1:].split()[0].lower() if len(msg) > 1 else ""
        if not cmd or cmd == "lp":
            return

        sender_id = str(event.get_sender_id()) if event.get_sender_id() else ""
        if self._is_admin_bypass() and await self._is_admin(event):
            return

        allowed = await self.check_permission(sender_id, cmd)
        if not allowed:
            logger.info(f"[AstrPerms] 拦截: {sender_id} -> /{cmd}")
            yield event.plain_result(
                _lp(f"&c你没有使用 &e/{cmd}&c 的权限。")
            )

    # ══════════════════════════════════════════
    #  消息级预拦截
    # ══════════════════════════════════════════

    @filter.event_message_type(EventMessageType.ALL)
    async def on_all_message(self, event: AstrMessageEvent):
        """对所有消息进行权限预检。"""
        try:
            msg = event.message_str.strip() if event.message_str else ""
        except Exception:
            return
        if not msg.startswith("/"):
            return

        cmd = msg[1:].split()[0].lower() if len(msg) > 1 else ""
        if not cmd or cmd == "lp":
            return

        sender_id = str(event.get_sender_id()) if event.get_sender_id() else ""
        if self._is_admin_bypass() and await self._is_admin(event):
            return

        allowed = await self.check_permission(sender_id, cmd)
        if not allowed:
            yield event.plain_result(
                _lp(f"&c你没有使用 &e/{cmd}&c 的权限。")
            )
            event.stop_event()

    # ══════════════════════════════════════════
    #  /lp 命令 — 主入口
    # ══════════════════════════════════════════

    @filter.command("lp")
    @filter.permission_type(PermissionType.ADMIN)
    async def lp(self, event: AstrMessageEvent):
        """
        /lp — LuckPerms 风格权限管理。

        子命令:
          user <qq> permission set|unset|info ...
          user <qq> parent add|remove|set|clear ...
          group <name> permission set|unset|info ...
          group <name> parent add|remove ...
          group <name> create|delete|rename|clone|listmembers
          group list
          search [query]
          editor
          export
          sync
          info
          verbose on|off
        """
        msg = event.message_str.strip()
        if msg.startswith("/lp"):
            msg = msg[3:].strip()
        if msg.startswith("lp "):
            msg = msg[3:].strip()

        parts = msg.split()
        if not parts:
            yield event.plain_result(self._help_text())
            return

        sub = parts[0].lower()
        args = parts[1:]

        # 路由
        handlers = {
            "user": lambda: self._handle_user(event, args),
            "group": lambda: self._handle_group(event, args),
            "search": lambda: self._handle_search(args),
            "editor": lambda: self._handle_editor(args),
            "export": lambda: self._handle_export(),
            "sync": lambda: self._handle_sync(),
            "info": lambda: self._handle_info(),
            "verbose": lambda: self._handle_verbose(args),
        }

        if sub in handlers:
            result = await handlers[sub]() if callable(handlers[sub]) else handlers[sub]()
        elif sub in ("help", "-h", "--help", "?"):
            result = self._help_text()
        else:
            result = _lp(f"&c未知子命令: &e{sub}&c。输入 &e/lp&c 查看帮助。")

        if callable(result):
            result = result
        yield event.plain_result(result)

    # ══════════════════════════════════════════
    #  /lp user
    # ══════════════════════════════════════════

    async def _handle_user(self, event: AstrMessageEvent, args: List[str]) -> str:
        if not args:
            return _lp("&c用法: /lp user <qq号> permission|parent ...")

        user_id = args[0]
        if len(args) < 2:
            return _lp(f"&c请指定操作: permission 或 parent")

        action = args[1].lower()

        if action == "permission":
            return await self._user_permission(user_id, args[2:])
        elif action == "parent":
            return await self._user_parent(user_id, args[2:])
        else:
            return _lp(f"&c未知操作: &e{action}&c，可用: permission, parent")

    async def _user_permission(self, user_id: str, args: List[str]) -> str:
        if not args:
            return _lp(f"&c用法: /lp user {user_id} permission <set|unset|info> ...")

        op = args[0].lower()
        data = await self._load_data()
        self._ensure_user(data, user_id)

        if op == "set":
            if len(args) < 3:
                return _lp(f"&c用法: /lp user {user_id} permission set <node> <true|false>")
            node = args[1].lower()
            val_str = args[2].lower()
            if val_str in ("true", "yes", "1", "t"):
                val = True
            elif val_str in ("false", "no", "0", "f"):
                val = False
            else:
                return _lp(f"&c值必须为 true 或 false，收到: &e{val_str}")

            data["users"][user_id]["permissions"][node] = val
            await self._save_data(data)
            status = "&atrue" if val else "&cfalse"
            return _lp(
                f"设置 &e{user_id}&r 的权限 &e{node}&r 为 {status}&r。"
            )

        elif op == "unset":
            if len(args) < 2:
                return _lp(f"&c用法: /lp user {user_id} permission unset <node>")
            node = args[1].lower()
            perms = data["users"][user_id].get("permissions", {})
            if node in perms:
                del perms[node]
                await self._save_data(data)
                return _lp(f"已取消 &e{user_id}&r 的权限 &e{node}&r。")
            return _lp(f"&e{user_id}&r 没有对 &e{node}&r 的显式权限设置。")

        elif op == "info":
            return self._format_user_info(user_id, data)

        elif op == "check":
            if len(args) < 2:
                return _lp(f"&c用法: /lp user {user_id} permission check <node>")
            node = args[1].lower()
            effective = await self._get_effective_permission(user_id, node)
            if effective is True:
                return _lp(f"&e{user_id}&r 对 &e{node}&r 的权限: &atrue")
            elif effective is False:
                return _lp(f"&e{user_id}&r 对 &e{node}&r 的权限: &cfalse")
            else:
                mode = self._get_default_mode()
                default = "&atrue" if mode == "allow" else "&cfalse"
                return _lp(f"&e{user_id}&r 对 &e{node}&r 的权限: {default} &7(默认)")

        else:
            return _lp(f"&c未知操作: &e{op}&c，可用: set, unset, info, check")

    async def _user_parent(self, user_id: str, args: List[str]) -> str:
        if not args:
            return _lp(f"&c用法: /lp user {user_id} parent <add|remove|set|clear> [组名]")

        op = args[0].lower()
        data = await self._load_data()
        self._ensure_user(data, user_id)

        if op == "add":
            if len(args) < 2:
                return _lp(f"&c用法: /lp user {user_id} parent add <组名>")
            gname = args[1]
            if gname not in data["groups"]:
                return _lp(f"&c组 &e{gname}&c 不存在。先用 /lp group {gname} create 创建。")
            ug = data["users"][user_id].get("groups", [])
            if gname in ug:
                return _lp(f"&e{user_id}&r 已在组 &e{gname}&r 中。")
            ug.append(gname)
            data["users"][user_id]["groups"] = ug
            # 同步 members
            members = data["groups"][gname].get("members", [])
            if user_id not in members:
                members.append(user_id)
            await self._save_data(data)
            return _lp(f"已将 &e{user_id}&r 添加到组 &e{gname}&r。")

        elif op == "remove":
            if len(args) < 2:
                return _lp(f"&c用法: /lp user {user_id} parent remove <组名>")
            gname = args[1]
            ug = data["users"][user_id].get("groups", [])
            if gname not in ug:
                return _lp(f"&e{user_id}&r 不在组 &e{gname}&r 中。")
            ug.remove(gname)
            if gname in data["groups"]:
                members = data["groups"][gname].get("members", [])
                if user_id in members:
                    members.remove(user_id)
            await self._save_data(data)
            return _lp(f"已将 &e{user_id}&r 从组 &e{gname}&r 移除。")

        elif op == "set":
            if len(args) < 2:
                return _lp(f"&c用法: /lp user {user_id} parent set <组名>")
            gname = args[1]
            if gname not in data["groups"]:
                return _lp(f"&c组 &e{gname}&c 不存在。先用 /lp group {gname} create 创建。")
            # 清理旧组的 members
            old_groups = data["users"][user_id].get("groups", [])
            for og in old_groups:
                if og in data["groups"]:
                    members = data["groups"][og].get("members", [])
                    if user_id in members:
                        members.remove(user_id)
            data["users"][user_id]["groups"] = [gname]
            members = data["groups"][gname].get("members", [])
            if user_id not in members:
                members.append(user_id)
            await self._save_data(data)
            return _lp(f"已将 &e{user_id}&r 的父组设置为 &e{gname}&r。")

        elif op == "clear":
            old_groups = data["users"][user_id].get("groups", [])
            for og in old_groups:
                if og in data["groups"]:
                    members = data["groups"][og].get("members", [])
                    if user_id in members:
                        members.remove(user_id)
            data["users"][user_id]["groups"] = []
            await self._save_data(data)
            return _lp(f"已清除 &e{user_id}&r 的所有父组。")

        else:
            return _lp(f"&c未知操作: &e{op}&c，可用: add, remove, set, clear")

    # ══════════════════════════════════════════
    #  /lp group
    # ══════════════════════════════════════════

    async def _handle_group(self, event: AstrMessageEvent, args: List[str]) -> str:
        if not args:
            return _lp("&c用法: /lp group <组名|list> ...")

        first = args[0]

        if first.lower() == "list":
            return await self._group_list()

        gname = first
        if len(args) < 2:
            return _lp(f"&c用法: /lp group {gname} <create|delete|rename|clone|permission|parent|listmembers> ...")

        action = args[1].lower()
        rest = args[2:]

        handlers = {
            "create": self._group_create,
            "delete": self._group_delete,
            "rename": self._group_rename,
            "clone": self._group_clone,
            "permission": self._group_permission,
            "parent": self._group_parent,
            "listmembers": self._group_listmembers,
            "info": self._group_info,
        }

        if action in handlers:
            h = handlers[action]
            if action in ("create", "delete", "listmembers", "info"):
                return await h(gname)
            elif action == "permission":
                return await h(gname, rest)
            elif action == "parent":
                return await h(gname, rest)
            else:
                return await h(gname, rest)  # rename, clone
        else:
            return _lp(f"&c未知操作: &e{action}&c，可用: create, delete, rename, clone, permission, parent, listmembers, info")

    async def _group_create(self, name: str) -> str:
        data = await self._load_data()
        if name in data["groups"]:
            return _lp(f"&c组 &e{name}&c 已存在。")
        data["groups"][name] = {"permissions": {}, "members": [], "parents": []}
        await self._save_data(data)
        return _lp(f"创建了组 &e{name}&r。")

    async def _group_delete(self, name: str) -> str:
        data = await self._load_data()
        if name not in data["groups"]:
            return _lp(f"&c组 &e{name}&c 不存在。")
        # 从所有用户中移除
        for uid, uentry in data["users"].items():
            ug = uentry.get("groups", [])
            if name in ug:
                ug.remove(name)
        # 从其他组的 parents 中移除
        for gn, gdata in data["groups"].items():
            parents = gdata.get("parents", [])
            if name in parents:
                parents.remove(name)
        del data["groups"][name]
        await self._save_data(data)
        return _lp(f"删除了组 &e{name}&r。")

    async def _group_rename(self, name: str, args: List[str]) -> str:
        if not args:
            return _lp(f"&c用法: /lp group {name} rename <新名称>")
        new_name = args[0]
        data = await self._load_data()
        if name not in data["groups"]:
            return _lp(f"&c组 &e{name}&c 不存在。")
        if new_name in data["groups"]:
            return _lp(f"&c组 &e{new_name}&c 已存在。")
        data["groups"][new_name] = data["groups"].pop(name)
        # 更新所有引用
        for uid, uentry in data["users"].items():
            ug = uentry.get("groups", [])
            if name in ug:
                ug[ug.index(name)] = new_name
        for gn, gdata in data["groups"].items():
            parents = gdata.get("parents", [])
            if name in parents:
                parents[parents.index(name)] = new_name
        await self._save_data(data)
        return _lp(f"已将组 &e{name}&r 重命名为 &e{new_name}&r。")

    async def _group_clone(self, name: str, args: List[str]) -> str:
        if not args:
            return _lp(f"&c用法: /lp group {name} clone <新名称>")
        new_name = args[0]
        data = await self._load_data()
        if name not in data["groups"]:
            return _lp(f"&c组 &e{name}&c 不存在。")
        if new_name in data["groups"]:
            return _lp(f"&c组 &e{new_name}&c 已存在。")
        import copy
        data["groups"][new_name] = copy.deepcopy(data["groups"][name])
        data["groups"][new_name]["members"] = []  # 不复制成员
        await self._save_data(data)
        return _lp(f"已克隆组 &e{name}&r 为 &e{new_name}&r（未复制成员）。")

    async def _group_permission(self, gname: str, args: List[str]) -> str:
        if not args:
            return _lp(f"&c用法: /lp group {gname} permission <set|unset|info|check> ...")
        op = args[0].lower()
        data = await self._load_data()

        if gname not in data["groups"]:
            return _lp(f"&c组 &e{gname}&c 不存在。先用 /lp group {gname} create 创建。")

        if op == "set":
            if len(args) < 3:
                return _lp(f"&c用法: /lp group {gname} permission set <node> <true|false>")
            node = args[1].lower()
            val_str = args[2].lower()
            if val_str in ("true", "yes", "1", "t"):
                val = True
            elif val_str in ("false", "no", "0", "f"):
                val = False
            else:
                return _lp(f"&c值必须为 true 或 false，收到: &e{val_str}")
            data["groups"][gname]["permissions"][node] = val
            await self._save_data(data)
            status = "&atrue" if val else "&cfalse"
            return _lp(f"设置组 &e{gname}&r 的权限 &e{node}&r 为 {status}&r。")

        elif op == "unset":
            if len(args) < 2:
                return _lp(f"&c用法: /lp group {gname} permission unset <node>")
            node = args[1].lower()
            perms = data["groups"][gname].get("permissions", {})
            if node in perms:
                del perms[node]
                await self._save_data(data)
                return _lp(f"已取消组 &e{gname}&r 的权限 &e{node}&r。")
            return _lp(f"组 &e{gname}&r 没有对 &e{node}&r 的显式权限设置。")

        elif op == "info":
            return self._format_group_info(gname, data)

        elif op == "check":
            if len(args) < 2:
                return _lp(f"&c用法: /lp group {gname} permission check <node>")
            node = args[1].lower()
            result = self._resolve_group_permission(gname, node, data.get("groups", {}))
            if result is True:
                return _lp(f"组 &e{gname}&r 对 &e{node}&r: &atrue")
            elif result is False:
                return _lp(f"组 &e{gname}&r 对 &e{node}&r: &cfalse")
            else:
                return _lp(f"组 &e{gname}&r 对 &e{node}&r: &7未设置")

        else:
            return _lp(f"&c未知操作: &e{op}&c，可用: set, unset, info, check")

    async def _group_parent(self, gname: str, args: List[str]) -> str:
        if not args:
            return _lp(f"&c用法: /lp group {gname} parent <add|remove> <父组名>")
        op = args[0].lower()
        data = await self._load_data()

        if gname not in data["groups"]:
            return _lp(f"&c组 &e{gname}&c 不存在。")

        if len(args) < 2:
            return _lp(f"&c用法: /lp group {gname} parent {op} <父组名>")

        parent_name = args[1]
        if parent_name not in data["groups"]:
            return _lp(f"&c父组 &e{parent_name}&c 不存在。")
        if parent_name == gname:
            return _lp("&c不能设置自己为父组。")

        parents = data["groups"][gname].get("parents", [])

        if op == "add":
            if parent_name in parents:
                return _lp(f"组 &e{gname}&r 已继承自 &e{parent_name}&r。")
            parents.append(parent_name)
            data["groups"][gname]["parents"] = parents
            await self._save_data(data)
            return _lp(f"设置组 &e{gname}&r 继承自 &e{parent_name}&r。")

        elif op == "remove":
            if parent_name not in parents:
                return _lp(f"组 &e{gname}&r 未继承自 &e{parent_name}&r。")
            parents.remove(parent_name)
            data["groups"][gname]["parents"] = parents
            await self._save_data(data)
            return _lp(f"已取消组 &e{gname}&r 对 &e{parent_name}&r 的继承。")

        else:
            return _lp(f"&c未知操作: &e{op}&c，可用: add, remove")

    async def _group_list(self) -> str:
        data = await self._load_data()
        groups = data.get("groups", {})
        if not groups:
            return _lp("当前没有任何组。")
        lines = ["&7&m--------------------", "&b组列表:", ""]
        for gname, gdata in sorted(groups.items()):
            count = len(gdata.get("members", []))
            perm_count = len(gdata.get("permissions", {}))
            parent_count = len(gdata.get("parents", []))
            extra = ""
            if parent_count:
                extra = f" &7(继承: {', '.join(gdata['parents'])})"
            lines.append(f"  &e{gname}&r — {count} 成员, {perm_count} 权限{extra}")
        lines.append("&7&m--------------------")
        return "\n".join(lines).replace("&7&m--------------------", "──────────────")

    async def _group_listmembers(self, gname: str) -> str:
        data = await self._load_data()
        group = data["groups"].get(gname)
        if not group:
            return _lp(f"&c组 &e{gname}&c 不存在。")
        members = group.get("members", [])
        if not members:
            return _lp(f"组 &e{gname}&r 暂无成员。")
        lines = ["&7&m--------------------", f"&b组 &e{gname}&b 成员 ({len(members)}):", ""]
        for m in sorted(members):
            uentry = data["users"].get(m, {})
            perms = uentry.get("permissions", {})
            extra = ""
            if perms:
                items = [f"{'&a' if v else '&c'}{k}" for k, v in sorted(perms.items())]
                extra = f" &7(个人: {', '.join(items)}&7)"
            lines.append(f"  &e{m}{extra}")
        lines.append("&7&m--------------------")
        return "\n".join(lines).replace("&7&m--------------------", "──────────────")

    async def _group_info(self, gname: str) -> str:
        data = await self._load_data()
        return self._format_group_info(gname, data)

    # ══════════════════════════════════════════
    #  /lp search
    # ══════════════════════════════════════════

    async def _handle_search(self, args: List[str]) -> str:
        query = args[0] if args else ""
        results = self._suggest_commands(query, limit=30)
        if not results:
            return _lp(f"&c未找到匹配 &e{query}&c 的指令。")
        count = len(self._discover_commands())
        header = _lp(
            f"搜索 &e{query}&r 的结果 &7(共发现 {count} 个指令):"
        )
        lines = [header, "&7&m--------------------"]
        for cmd in results:
            lines.append(f"  &e/{cmd}")
        lines.append("&7&m--------------------")
        return "\n".join(lines).replace("&7&m--------------------", "──────────────")

    # ══════════════════════════════════════════
    #  /lp editor
    # ══════════════════════════════════════════

    async def _handle_editor(self, args: List[str]) -> str:
        """简易交互式编辑器"""
        if args and args[0].lower() == "start":
            return _lp(
                "&7AstrBot 暂不支持交互式编辑器。\n"
                "&7请使用以下命令管理权限:\n"
                "&e/lp user <qq> permission set <node> true|false\n"
                "&e/lp group <group> permission set <node> true|false\n"
                "&e/lp search [query] &7— 搜索可用指令\n"
                "&e/lp export &7— 导出全部数据"
            )
        return _lp(
            "&7编辑器用法: &e/lp editor start\n"
            "&7或直接使用 &e/lp user|group &7命令管理。\n"
            "&7用 &e/lp search&7 查看所有可用指令。"
        )

    # ══════════════════════════════════════════
    #  /lp export / /lp sync / /lp info / /lp verbose
    # ══════════════════════════════════════════

    async def _handle_export(self) -> str:
        data = await self._load_data()
        pretty = json.dumps(data, ensure_ascii=False, indent=2)
        return _lp(f"权限数据导出:\n```json\n{pretty}\n```")

    async def _handle_sync(self) -> str:
        await self._invalidate_cache()
        data = await self._load_data()
        cmds = self._discover_commands(force=True)
        user_count = len(data.get("users", {}))
        group_count = len(data.get("groups", {}))
        return _lp(
            f"数据已重新加载。\n"
            f"用户数: {user_count} | 组数: {group_count} | 可用指令: {len(cmds)}"
        )

    async def _handle_info(self) -> str:
        data = await self._load_data()
        cmds = self._discover_commands()
        mode = self._get_default_mode()
        mode_str = "&a全部允许 (allow)" if mode == "allow" else "&c全部拒绝 (deny)"
        lines = [
            "&7&m--------------------",
            "&bAstrPerms 信息",
            "",
            f"  默认模式: {mode_str}",
            f"  用户数: &e{len(data.get('users', {}))}",
            f"  组数: &e{len(data.get('groups', {}))}",
            f"  可用指令数: &e{len(cmds)}",
            f"  管理员豁免: &e{self._is_admin_bypass()}",
            f"  Verbose: &e{self._verbose}",
            "&7&m--------------------",
        ]
        return "\n".join(lines).replace("&7&m--------------------", "──────────────")

    async def _handle_verbose(self, args: List[str]) -> str:
        if not args:
            return _lp(f"verbose 当前: &e{'on' if self._verbose else 'off'}")
        val = args[0].lower()
        if val in ("on", "true", "1"):
            self._verbose = True
            return _lp("verbose 已开启 &a(on)&r。")
        elif val in ("off", "false", "0"):
            self._verbose = False
            return _lp("verbose 已关闭 &c(off)&r。")
        else:
            return _lp(f"&c用法: /lp verbose <on|off>")

    # ══════════════════════════════════════════
    #  格式化输出
    # ══════════════════════════════════════════

    def _format_user_info(self, user_id: str, data: Dict[str, Any]) -> str:
        uentry = data["users"].get(user_id, {})
        perms = uentry.get("permissions", {})
        ug = uentry.get("groups", [])

        lines = ["&7&m--------------------", f"&b用户 &e{user_id}&b 权限信息", ""]

        # 组
        if ug:
            # 计算完整继承链
            all_parents: Set[str] = set()
            def collect_parents(gn: str):
                g = data["groups"].get(gn)
                if g:
                    for p in g.get("parents", []):
                        if p not in all_parents:
                            all_parents.add(p)
                            collect_parents(p)

            for gname in ug:
                collect_parents(gname)

            lines.append(f"  父组: &e{', '.join(ug)}")
            if all_parents:
                lines.append(f"  继承链: &7{', '.join(sorted(all_parents))}")
            lines.append("")

        # 权限
        if perms:
            lines.append("  权限:")
            for node, val in sorted(perms.items()):
                icon = "&a✔" if val else "&c✘"
                lines.append(f"    {icon} &e{node}")
        else:
            lines.append("  权限: &7(无显式设置)")

        # 有效权限
        all_nodes = set(perms.keys())
        for gname in ug:
            g = data["groups"].get(gname, {})
            all_nodes.update(g.get("permissions", {}).keys())
            for p in self._get_all_parents(gname, data["groups"]):
                pg = data["groups"].get(p, {})
                all_nodes.update(pg.get("permissions", {}).keys())

        if all_nodes - set(perms.keys()):
            lines.append("")
            lines.append("  有效权限 (含组继承):")
            for node in sorted(all_nodes):
                if node in perms:
                    continue  # 已在上面显示
                # 计算有效值
                effective = None
                for gname in ug:
                    val = self._resolve_group_permission(gname, node, data.get("groups", {}))
                    if val is True:
                        effective = True
                        break
                    if val is False:
                        effective = False
                icon = "&a✔" if effective else "&c✘" if effective is False else "&7-"
                source = "组" if effective is not None else "默认"
                lines.append(f"    {icon} &e{node} &7({source})")

        lines.append("&7&m--------------------")
        return "\n".join(lines).replace("&7&m--------------------", "──────────────")

    def _get_all_parents(self, gname: str, groups: Dict[str, Any]) -> Set[str]:
        """递归获取组的所有祖先"""
        result: Set[str] = set()
        group = groups.get(gname)
        if group:
            for p in group.get("parents", []):
                if p not in result:
                    result.add(p)
                    result.update(self._get_all_parents(p, groups))
        return result

    def _format_group_info(self, gname: str, data: Dict[str, Any]) -> str:
        group = data["groups"].get(gname, {})
        perms = group.get("permissions", {})
        members = group.get("members", [])
        parents = group.get("parents", [])

        lines = [
            "&7&m--------------------",
            f"&b组 &e{gname}&b 信息",
            "",
            f"  权重: &e{len(members)} 成员",
        ]

        if parents:
            lines.append(f"  继承自: &e{', '.join(parents)}")
            all_parents = self._get_all_parents(gname, data.get("groups", {}))
            if all_parents:
                lines.append(f"  完整继承链: &7{', '.join(sorted(all_parents))}")

        lines.append("")

        if perms:
            lines.append("  权限:")
            for node, val in sorted(perms.items()):
                icon = "&a✔" if val else "&c✘"
                lines.append(f"    {icon} &e{node}")
        else:
            lines.append("  权限: &7(无显式设置)")

        if members:
            lines.append("")
            lines.append(f"  成员 ({len(members)}):")
            for m in sorted(members)[:30]:
                lines.append(f"    &e{m}")
            if len(members) > 30:
                lines.append(f"    &7... 及其他 {len(members) - 30} 人")

        lines.append("&7&m--------------------")
        return "\n".join(lines).replace("&7&m--------------------", "──────────────")

    # ══════════════════════════════════════════
    #  帮助
    # ══════════════════════════════════════════

    def _help_text(self) -> str:
        return (
            "&b&lAstrPerms &r&7— LuckPerms 风格权限管理\n"
            "\n"
            "&7&m------------------------------------------------\n"
            "&e/lp user <qq> permission set <node> true|false\n"
            "&e/lp user <qq> permission unset <node>\n"
            "&e/lp user <qq> permission info\n"
            "&e/lp user <qq> permission check <node>\n"
            "&e/lp user <qq> parent add <group>\n"
            "&e/lp user <qq> parent remove <group>\n"
            "&e/lp user <qq> parent set <group>\n"
            "&e/lp user <qq> parent clear\n"
            "\n"
            "&e/lp group <group> permission set <node> true|false\n"
            "&e/lp group <group> permission unset <node>\n"
            "&e/lp group <group> permission info\n"
            "&e/lp group <group> parent add <group>\n"
            "&e/lp group <group> parent remove <group>\n"
            "&e/lp group <group> create\n"
            "&e/lp group <group> delete\n"
            "&e/lp group <group> rename <new>\n"
            "&e/lp group <group> clone <new>\n"
            "&e/lp group <group> listmembers\n"
            "&e/lp group list\n"
            "\n"
            "&e/lp search [query]    &7搜索可用指令\n"
            "&e/lp editor             &7编辑器入口\n"
            "&e/lp export             &7导出全部数据\n"
            "&e/lp sync               &7重新加载\n"
            "&e/lp info               &7插件信息\n"
            "&e/lp verbose on|off     &7调试模式\n"
            "&7&m------------------------------------------------\n"
            "&7权限优先级: 用户 > 组(含父组递归) > 默认\n"
            "&7通配符 &e*&7 代表所有指令\n"
            "&7仅管理员可使用 &e/lp&7 命令"
        )

    # ══════════════════════════════════════════
    #  生命周期
    # ══════════════════════════════════════════

    async def terminate(self):
        self._data_cache = None
        self._commands_cache = None
        logger.info("[AstrPerms] 插件已卸载")
