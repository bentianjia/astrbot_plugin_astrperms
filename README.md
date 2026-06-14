# AstrPerms — LuckPerms 风格权限管理插件

类似 Minecraft LuckPerms 的 AstrBot 权限管理插件，**全局生效**（所有群聊、所有平台统一检查）。

## 特性

- ✅ LuckPerms 完全一致的命令语法
- ✅ 用户权限 + 组权限 + 父组递归继承
- ✅ 通配符 `*` 支持
- ✅ **自动发现**已安装插件的指令
- ✅ 双拦截机制（消息预拦截 + 返回结果拦截）
- ✅ 管理员豁免
- ✅ WebUI 配置（默认模式、管理员豁免开关）
- ✅ 全局生效，不限群聊

## 安装

将 `astrbot_plugin_astrperms` 文件夹放入 AstrBot 的 `data/plugins/` 目录。

```
data/plugins/astrbot_plugin_astrperms/
├── main.py
├── metadata.yaml
└── _conf_schema.json
```

## 快速上手

```bash
# 1. 拒绝 QQ 123456 使用 /new 指令
/lp user 123456 permission set new false

# 2. 查看用户权限
/lp user 123456 permission info

# 3. 创建 vip 组
/lp group vip create

# 4. 允许 vip 组使用 /weather
/lp group vip permission set weather true

# 5. 把用户加入 vip 组
/lp user 123456 parent add vip

# 6. 搜索可用指令
/lp search

# 7. 查看插件状态
/lp info
```

## 权限优先级

1. **用户显式权限**（最高优先级）
2. **组权限**（含父组递归继承，任意组 true 优先）
3. **默认模式**（allow / deny，在 WebUI 配置）

## 命令参考

### 用户权限
| 命令 | 说明 |
|------|------|
| `/lp user <qq> permission set <cmd> true\|false` | 设置用户权限 |
| `/lp user <qq> permission unset <cmd>` | 取消用户权限 |
| `/lp user <qq> permission info` | 查看用户权限信息 |
| `/lp user <qq> permission check <cmd>` | 检查用户对某指令的权限 |

### 用户组
| 命令 | 说明 |
|------|------|
| `/lp user <qq> parent add <group>` | 添加到组 |
| `/lp user <qq> parent remove <group>` | 从组移除 |
| `/lp user <qq> parent set <group>` | 设置唯一父组 |
| `/lp user <qq> parent clear` | 清除所有父组 |

### 组权限
| 命令 | 说明 |
|------|------|
| `/lp group <group> create` | 创建组 |
| `/lp group <group> delete` | 删除组 |
| `/lp group <group> rename <new>` | 重命名组 |
| `/lp group <group> clone <new>` | 克隆组 |
| `/lp group <group> permission set <cmd> true\|false` | 设置组权限 |
| `/lp group <group> permission unset <cmd>` | 取消组权限 |
| `/lp group <group> permission info` | 查看组权限 |
| `/lp group <group> permission check <cmd>` | 检查组权限 |
| `/lp group <group> parent add <parent>` | 设置继承父组 |
| `/lp group <group> parent remove <parent>` | 取消继承 |
| `/lp group <group> listmembers` | 列出组成员 |
| `/lp group list` | 列出所有组 |

### 其他
| 命令 | 说明 |
|------|------|
| `/lp search [query]` | 搜索可用指令 |
| `/lp editor` | 编辑器入口 |
| `/lp export` | 导出全部数据 |
| `/lp sync` | 重新加载 |
| `/lp info` | 插件信息 |
| `/lp verbose on\|off` | 调试模式 |

## 配置

在 AstrBot WebUI → 插件管理 → AstrPerms → 配置：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `default_mode` | select | `allow` | 默认权限模式 |
| `admin_bypass` | boolean | `true` | 管理员豁免权限检查 |
