# AstrPerms — LuckPerms 风格权限管理插件

类似 Minecraft LuckPerms 的 AstrBot 权限管理插件，**全局生效**（所有群聊、所有平台统一检查）。

## 对应关系

| LuckPerms | AstrPerms |
|-----------|-----------|
| `lp.*` 权限 | AstrBot 管理员 |
| 普通玩家 | QQ 用户 |
| `default` 组 | 默认组（所有人自动归属） |
| permission node | AstrBot 指令名 |

## 特性

- ✅ LuckPerms 完全一致的命令语法
- ✅ 用户权限 + 组权限 + 父组递归继承
- ✅ **默认组 — 所有人自动归属，首次交互即写入**
- ✅ 通配符 `*` 支持
- ✅ **自动发现**已安装插件的指令 (`/lp search`)
- ✅ 三层拦截（消息预检 + LLM 拦截 + 返回拦截）
- ✅ AstrBot 管理员 = `lp.*`，豁免所有权限检查
- ✅ WebUI 配置（默认组名、默认模式、管理员豁免、额外前缀）
- ✅ 自动读取 AstrBot `wake_prefix` 配置

## 安装

将 `astrbot_plugin_astrperms` 文件夹放入 AstrBot 的 `data/plugins/` 目录，WebUI 启用即可。

```
data/plugins/astrbot_plugin_astrperms/
├── main.py
├── metadata.yaml
└── _conf_schema.json
```

## 场景实战

每个场景直接复制命令执行即可。

### 场景一：禁掉单个指令

最常用——不让任何人用 `/new`。

```bash
/lp group default permission set new false
```

### 场景二：某个组只能用特定指令（白名单）

VIP 组只能刷 `/weather` 和 `/music`，其他指令全禁。

```bash
# 1. 创建 vip 组
/lp group vip create

# 2. 拒绝 vip 组使用所有指令
/lp group vip permission set * false

# 3. 开放指定指令
/lp group vip permission set weather true
/lp group vip permission set music true

# 4. 把用户拉进 vip 组
/lp user 123456 parent add vip
```

用户 123456 现在只能用 `/weather` 和 `/music`，其他指令全被 `* false` 拦截。

### 场景三：全局白名单模式

直接用 `default_mode = deny`，只放行你允许的指令。

WebUI → AstrPerms 配置 → `default_mode` 填 `deny`，然后：

```bash
# 允许所有人的指令
/lp group default permission set help true
/lp group default permission set ping true
/lp group default permission set weather true
```

所有不在列表里的指令不管是谁都被拒。

### 场景四：禁一个指令，但给某人开绿灯

```bash
# 全局禁止 /new
/lp group default permission set new false

# 唯独 123456 可以用
/lp user 123456 permission set new true
```

### 场景五：组套组（继承链）

```bash
# vip 继承 member 的所有权限
/lp group member create
/lp group member permission set help true
/lp group member permission set ping true

/lp group vip create
/lp group vip parent add member          # vip 继承 member
/lp group vip permission set weather true # vip 额外权限

# 结果：vip 成员有 help + ping + weather
```

### 场景六：查权限、排障

```bash
/lp user 123456 permission info          # 查看用户的有效权限
/lp group default permission check new   # 查默认组对 /new 的权限
/lp search weather                       # 搜索指令名
/lp export                               # 导出全部配置
```

## 权限优先级

```
1. 用户显式权限              /lp user xxx permission set ...
2. 用户加入的组（含父组递归）  /lp group xxx permission set ...
3. 默认组（所有人自动归属）    /lp group default permission set ...
4. 全局默认模式              WebUI → default_mode
```

**默认组**是核心机制：所有人首次与 bot 交互时自动写入，无需手动逐个添加。

## 命令参考

### 用户权限
| 命令 | 说明 |
|------|------|
| `/lp user <qq> permission set <cmd> true\|false` | 设置用户权限 |
| `/lp user <qq> permission unset <cmd>` | 取消用户权限 |
| `/lp user <qq> permission info` | 查看用户权限 |
| `/lp user <qq> permission check <cmd>` | 检查用户对某指令的权限 |

### 用户组归属
| 命令 | 说明 |
|------|------|
| `/lp user <qq> parent add <group>` | 添加到组 |
| `/lp user <qq> parent remove <group>` | 从组移除 |
| `/lp user <qq> parent set <group>` | 设置唯一父组（替换所有） |
| `/lp user <qq> parent clear` | 清除所有父组 |

### 组管理
| 命令 | 说明 |
|------|------|
| `/lp group <group> create` | 创建组 |
| `/lp group <group> delete` | 删除组 |
| `/lp group <group> rename <new>` | 重命名组 |
| `/lp group <group> clone <new>` | 克隆组（不复制成员） |
| `/lp group <group> permission set <cmd> true\|false` | 设置组权限 |
| `/lp group <group> permission unset <cmd>` | 取消组权限 |
| `/lp group <group> permission info` | 查看组权限 |
| `/lp group <group> permission check <cmd>` | 检查组权限 |
| `/lp group <group> parent add <parent>` | 继承父组权限 |
| `/lp group <group> parent remove <parent>` | 取消继承 |
| `/lp group <group> listmembers` | 列出组成员 |
| `/lp group list` | 列出所有组 |

### 其他
| 命令 | 说明 |
|------|------|
| `/lp search [query]` | 搜索可用指令 |
| `/lp editor` | 编辑器入口 |
| `/lp export` | 导出全部数据 (JSON) |
| `/lp sync` | 重新从存储加载 |
| `/lp info` | 插件信息 |
| `/lp verbose on\|off` | 调试模式 |

## 配置

在 AstrBot WebUI → 插件管理 → AstrPerms → 配置：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `default_group` | string | `default` | 所有人自动归属的组名 |
| `default_mode` | string | `allow` | 全局兜底，`allow` 或 `deny` |
| `admin_bypass` | bool | `true` | 管理员豁免 |
| `extra_prefixes` | string | `#` | 额外拦截的指令前缀，逗号分隔 |
