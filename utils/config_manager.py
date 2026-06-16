import os
import json
from typing import Any, Dict, List, Optional


class ConfigManager:
    """配置管理类，用于解析和管理 plugin.json 配置文件"""

    def __init__(self, config_path: str = None):
        self._config_path = config_path
        self._config: Dict[str, Any] = {}
        self._plugin_configs: Dict[str, Dict[str, Any]] = {}
        
        if config_path:
            self.load(config_path)

    def load(self, config_path: str) -> bool:
        """加载配置文件"""
        if not os.path.exists(config_path):
            return False
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self._config = json.load(f)
            self._config_path = config_path
            
            # 加载每个插件的单独配置文件
            self._load_plugin_configs()
            return True
        except (json.JSONDecodeError, IOError) as e:
            print(f"加载配置文件失败: {e}")
            return False

    def _load_plugin_configs(self) -> None:
        """加载每个插件的单独配置文件"""
        self._plugin_configs = {}
        base_dir = os.path.dirname(self._config_path)
        
        for plugin in self.get_plugins():
            plugin_name = plugin.get('name', '')
            module = plugin.get('module', '')
            
            if module:
                # 从 module 路径推导配置文件位置
                # module: "plugins.terminal" -> config: "plugins/terminal/config.json"
                module_path = module.replace('.', os.sep)
                config_file = os.path.join(base_dir, module_path, 'config.json')
                
                if os.path.exists(config_file):
                    try:
                        with open(config_file, 'r', encoding='utf-8') as f:
                            self._plugin_configs[plugin_name] = json.load(f)
                    except (json.JSONDecodeError, IOError) as e:
                        print(f"加载插件配置失败 {plugin_name}: {e}")

    def save(self, config_path: str = None) -> bool:
        """保存主配置到文件"""
        path = config_path or self._config_path
        if not path:
            return False
        
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=4, ensure_ascii=False)
            return True
        except IOError as e:
            print(f"保存配置文件失败: {e}")
            return False

    def save_plugin_config(self, plugin_name: str) -> bool:
        """保存插件配置到文件"""
        if plugin_name not in self._plugin_configs:
            return False
        
        # 找到插件配置文件路径
        for plugin in self.get_plugins():
            if plugin.get('name') == plugin_name:
                module = plugin.get('module', '')
                if module:
                    base_dir = os.path.dirname(self._config_path)
                    module_path = module.replace('.', os.sep)
                    config_file = os.path.join(base_dir, module_path, 'config.json')
                    
                    try:
                        with open(config_file, 'w', encoding='utf-8') as f:
                            json.dump(self._plugin_configs[plugin_name], f, indent=4, ensure_ascii=False)
                        return True
                    except IOError as e:
                        print(f"保存插件配置失败 {plugin_name}: {e}")
        return False

    def get_plugins(self) -> List[Dict[str, Any]]:
        """获取所有插件注册信息"""
        return self._config.get('plugins', [])

    def get_plugin(self, name: str) -> Optional[Dict[str, Any]]:
        """根据名称获取单个插件注册信息"""
        for plugin in self.get_plugins():
            if plugin.get('name') == name:
                return plugin
        return None

    def get_plugin_config(self, name: str) -> Optional[Dict[str, Any]]:
        """获取插件的详细配置（从插件单独配置文件）"""
        return self._plugin_configs.get(name)

    def get_plugin_setting(self, plugin_name: str, key: str, default: Any = None) -> Any:
        """获取插件的单个设置项"""
        config = self.get_plugin_config(plugin_name)
        if config:
            return config.get('settings', {}).get(key, default)
        return default

    def set_plugin_setting(self, plugin_name: str, key: str, value: Any) -> None:
        """设置插件的单个设置项"""
        config = self.get_plugin_config(plugin_name)
        if config:
            if 'settings' not in config:
                config['settings'] = {}
            config['settings'][key] = value

    def get_plugin_toolbar(self, name: str) -> List[Dict[str, Any]]:
        """获取插件的工具栏配置"""
        config = self.get_plugin_config(name)
        return config.get('toolbar', []) if config else []

    def get_plugin_menu(self, name: str) -> Optional[Dict[str, Any]]:
        """获取插件的菜单配置"""
        config = self.get_plugin_config(name)
        return config.get('menu') if config else None

    def get_all_toolbar_actions(self) -> List[Dict[str, Any]]:
        """获取所有插件的工具栏动作"""
        actions = []
        for plugin_name, config in self._plugin_configs.items():
            for item in config.get('toolbar', []):
                item['_plugin_name'] = plugin_name
                actions.append(item)
        return actions

    def get_all_menu_actions(self) -> Dict[str, List[Dict[str, Any]]]:
        """获取所有插件的菜单动作，按父菜单分组"""
        menu_actions = {}
        for plugin_name, config in self._plugin_configs.items():
            menu = config.get('menu')
            if menu:
                parent = menu.get('parent', '')
                if parent not in menu_actions:
                    menu_actions[parent] = []
                menu['_plugin_name'] = plugin_name
                menu_actions[parent].append(menu)
        return menu_actions

    def get_settings(self) -> Dict[str, Any]:
        """获取全局设置"""
        return self._config.get('settings', {})

    def get_setting(self, key: str, default: Any = None) -> Any:
        """获取单个全局设置项"""
        return self._config.get('settings', {}).get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        """设置单个全局设置项"""
        if 'settings' not in self._config:
            self._config['settings'] = {}
        self._config['settings'][key] = value

    def add_plugin(self, plugin_info: Dict[str, Any]) -> None:
        """添加新插件注册信息"""
        if 'plugins' not in self._config:
            self._config['plugins'] = []
        self._config['plugins'].append(plugin_info)

    def remove_plugin(self, name: str) -> bool:
        """移除插件注册信息"""
        plugins = self.get_plugins()
        for i, plugin in enumerate(plugins):
            if plugin.get('name') == name:
                plugins.pop(i)
                if name in self._plugin_configs:
                    del self._plugin_configs[name]
                return True
        return False

    def get_config_path(self) -> Optional[str]:
        """获取当前配置文件路径"""
        return self._config_path

    def get_raw_config(self) -> Dict[str, Any]:
        """获取原始配置字典"""
        return self._config

    def reload(self) -> bool:
        """重新加载配置文件"""
        if self._config_path:
            return self.load(self._config_path)
        return False

    @staticmethod
    def get_default_config_path() -> str:
        """获取默认配置文件路径"""
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "plugin.json"
        )