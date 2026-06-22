import os
import json
from typing import Any, Dict, List, Optional


class ConfigManager:
    """统一配置管理类，所有配置文件都在 config 目录下"""

    def __init__(self, config_dir: str = None):
        self._config_dir = config_dir
        self._main_config: Dict[str, Any] = {}
        self._plugin_configs: Dict[str, Dict[str, Any]] = {}
        self._plugin_data: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._style_config: Dict[str, Any] = {}
        
        if config_dir:
            self.load_all()

    def load_all(self) -> bool:
        """加载所有配置文件"""
        if not self._config_dir or not os.path.exists(self._config_dir):
            return False
        
        # 加载主配置
        main_config_path = os.path.join(self._config_dir, 'plugin.json')
        if os.path.exists(main_config_path):
            try:
                with open(main_config_path, 'r', encoding='utf-8') as f:
                    self._main_config = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"加载主配置失败: {e}")
                return False
        
        # 加载样式配置
        self._load_style_config()
        
        # 加载每个插件的配置和数据
        self._load_all_plugin_configs()
        return True
    
    def _load_style_config(self) -> None:
        """加载样式配置文件"""
        style_config_path = os.path.join(self._config_dir, 'style_config.json')
        if os.path.exists(style_config_path):
            try:
                with open(style_config_path, 'r', encoding='utf-8') as f:
                    self._style_config = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"加载样式配置失败: {e}")
                self._style_config = self._get_default_style_config()
        else:
            self._style_config = self._get_default_style_config()
    
    def _get_default_style_config(self) -> Dict[str, Any]:
        """获取默认样式配置"""
        return {
            "color_scheme": {
                "primary": "#007acc",
                "primary_hover": "#005a9e",
                "primary_pressed": "#004575",
                "success": "#28a745",
                "warning": "#ffc107",
                "danger": "#dc3545",
                "info": "#17a2b8",
                "background_main": "#1e1e1e",
                "background_secondary": "#252526",
                "background_tertiary": "#2d2d30",
                "background_input": "#3c3c3c",
                "background_input_focus": "#4c4c4c",
                "border": "#3d3d40",
                "border_light": "#4a4a4d",
                "border_focus": "#007acc",
                "text_primary": "#ffffff",
                "text_secondary": "#cccccc",
                "text_hint": "#888888",
                "text_success": "#00ff00",
                "text_warning": "#ffff00",
                "text_danger": "#ff6b6b",
                "text_info": "#00d4ff",
                "selection": "#007acc",
                "selection_text": "#ffffff"
            },
            "font_sizes": {
                "small": "11px",
                "normal": "12px",
                "medium": "13px",
                "large": "14px",
                "extra_large": "16px"
            },
            "font_weights": {
                "normal": "500",
                "bold": "bold"
            },
            "border_radius": {
                "small": "4px",
                "normal": "6px",
                "large": "8px",
                "extra_large": "12px"
            },
            "components": {}
        }

    def _load_all_plugin_configs(self) -> None:
        """加载所有插件的配置文件（扁平结构）"""
        self._plugin_configs = {}
        self._plugin_data = {}
        
        for plugin in self.get_plugins():
            plugin_name = plugin.get('name', '')
            if not plugin_name:
                continue
            
            # 插件配置文件名: {name}_config.json (如 terminal_config.json, quickly_cmd_config.json)
            config_filename = f"{plugin_name.lower()}_config.json"
            config_file = os.path.join(self._config_dir, config_filename)
            
            if os.path.exists(config_file):
                try:
                    with open(config_file, 'r', encoding='utf-8') as f:
                        self._plugin_configs[plugin_name] = json.load(f)
                except (json.JSONDecodeError, IOError) as e:
                    print(f"加载插件配置失败 {plugin_name}: {e}")
            
            # 插件数据目录为空，数据直接存储在config根目录
            self._plugin_data[plugin_name] = {}
        
        # 加载公共数据文件（如 connections.json）
        # connections.json 属于 Terminal 插件
        terminal_data_files = ['connections']
        for filename in os.listdir(self._config_dir):
            if filename.endswith('.json') and filename not in ['plugin.json'] and '_config.json' not in filename:
                data_file = os.path.join(self._config_dir, filename)
                if os.path.isfile(data_file):
                    try:
                        with open(data_file, 'r', encoding='utf-8') as f:
                            data_key = filename[:-5]  # 移除 .json 后缀
                            # 尝试推断属于哪个插件
                            assigned = False
                            for plugin_name in self._plugin_configs:
                                if plugin_name.lower() in filename.lower():
                                    self._plugin_data[plugin_name][data_key] = json.load(f)
                                    assigned = True
                                    break
                            # 如果没有匹配，检查是否是已知的特殊数据文件
                            if not assigned:
                                if data_key in terminal_data_files and 'Terminal' in self._plugin_configs:
                                    self._plugin_data['Terminal'][data_key] = json.load(f)
                    except (json.JSONDecodeError, IOError) as e:
                        print(f"加载数据文件失败 {filename}: {e}")

    def save_main_config(self) -> bool:
        """保存主配置"""
        if not self._config_dir:
            return False
        
        main_config_path = os.path.join(self._config_dir, 'plugin.json')
        try:
            with open(main_config_path, 'w', encoding='utf-8') as f:
                json.dump(self._main_config, f, indent=4, ensure_ascii=False)
            return True
        except IOError as e:
            print(f"保存主配置失败: {e}")
            return False

    def save_plugin_config(self, plugin_name: str) -> bool:
        """保存插件配置"""
        if not self._config_dir or plugin_name not in self._plugin_configs:
            return False
        
        config_filename = f"{plugin_name.lower()}_config.json"
        config_file = os.path.join(self._config_dir, config_filename)
        
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(self._plugin_configs[plugin_name], f, indent=4, ensure_ascii=False)
            return True
        except IOError as e:
            print(f"保存插件配置失败 {plugin_name}: {e}")
            return False

    def save_plugin_data(self, plugin_name: str, data_key: str) -> bool:
        """保存插件数据文件"""
        if not self._config_dir:
            return False
        
        if plugin_name not in self._plugin_data or data_key not in self._plugin_data[plugin_name]:
            return False
        
        # 数据文件直接保存在config根目录
        data_file = os.path.join(self._config_dir, f"{data_key}.json")
        try:
            with open(data_file, 'w', encoding='utf-8') as f:
                json.dump(self._plugin_data[plugin_name][data_key], f, indent=4, ensure_ascii=False)
            return True
        except IOError as e:
            print(f"保存插件数据失败 {plugin_name}/{data_key}: {e}")
            return False

    def get_plugins(self) -> List[Dict[str, Any]]:
        """获取所有插件注册信息"""
        return self._main_config.get('plugins', [])

    def get_plugin(self, name: str) -> Optional[Dict[str, Any]]:
        """根据名称获取单个插件注册信息"""
        for plugin in self.get_plugins():
            if plugin.get('name') == name:
                return plugin
        return None

    def get_plugin_config(self, name: str) -> Optional[Dict[str, Any]]:
        """获取插件的详细配置"""
        return self._plugin_configs.get(name)

    def get_plugin_data(self, plugin_name: str, data_key: str) -> Optional[Dict[str, Any]]:
        """获取插件数据文件内容"""
        if plugin_name in self._plugin_data:
            return self._plugin_data[plugin_name].get(data_key)
        return None

    def set_plugin_data(self, plugin_name: str, data_key: str, data: Any) -> None:
        """设置插件数据"""
        if plugin_name not in self._plugin_data:
            self._plugin_data[plugin_name] = {}
        self._plugin_data[plugin_name][data_key] = data

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
        return self._main_config.get('settings', {})

    def get_setting(self, key: str, default: Any = None) -> Any:
        """获取单个全局设置项"""
        return self._main_config.get('settings', {}).get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        """设置单个全局设置项"""
        if 'settings' not in self._main_config:
            self._main_config['settings'] = {}
        self._main_config['settings'][key] = value

    def add_plugin(self, plugin_info: Dict[str, Any]) -> None:
        """添加新插件注册信息"""
        if 'plugins' not in self._main_config:
            self._main_config['plugins'] = []
        self._main_config['plugins'].append(plugin_info)

    def remove_plugin(self, name: str) -> bool:
        """移除插件注册信息"""
        plugins = self.get_plugins()
        for i, plugin in enumerate(plugins):
            if plugin.get('name') == name:
                plugins.pop(i)
                if name in self._plugin_configs:
                    del self._plugin_configs[name]
                if name in self._plugin_data:
                    del self._plugin_data[name]
                return True
        return False

    def get_config_dir(self) -> Optional[str]:
        """获取配置目录路径"""
        return self._config_dir

    def get_plugin_config_dir(self, plugin_name: str) -> str:
        """获取插件配置目录路径"""
        return os.path.join(self._config_dir, plugin_name.lower())

    def reload(self) -> bool:
        """重新加载所有配置文件"""
        return self.load_all()

    def get_style_config(self) -> Dict[str, Any]:
        """获取完整的样式配置"""
        return self._style_config
    
    def get_color_scheme(self) -> Dict[str, Any]:
        """获取颜色方案配置"""
        return self._style_config.get('color_scheme', {})
    
    def get_color(self, key: str, default: str = '#ffffff') -> str:
        """获取单个颜色值"""
        return self.get_color_scheme().get(key, default)
    
    def get_font_size(self, key: str, default: str = '12px') -> str:
        """获取字体大小配置"""
        value = self._style_config.get('font_sizes', {}).get(key, default)
        return self._validate_font_size(value, default)
    
    def _validate_font_size(self, value: str, default: str = '12px') -> str:
        """验证字体大小值是否有效"""
        if not value or not isinstance(value, str):
            return default
        import re
        match = re.match(r'^(\d+)(px|pt|em)?$', value.strip())
        if match and int(match.group(1)) > 0:
            return value
        return default
    
    def get_border_radius(self, key: str, default: str = '4px') -> str:
        """获取边框圆角配置"""
        return self._style_config.get('border_radius', {}).get(key, default)
    
    def get_component_style(self, component_name: str) -> Dict[str, Any]:
        """获取指定组件的样式配置"""
        return self._style_config.get('components', {}).get(component_name, {})
    
    def get_component_style_value(self, component_name: str, key: str, default: Any = None) -> Any:
        """获取指定组件的样式值（自动解析变量引用）"""
        component = self.get_component_style(component_name)
        value = component.get(key, default)
        if isinstance(value, str):
            return self.resolve_style_value(value)
        return value
    
    def resolve_style_value(self, value: str) -> str:
        """解析样式值中的变量引用，如 ${color_scheme.primary}"""
        if isinstance(value, str) and '${' in value and '}' in value:
            parts = value.split('${')
            result = parts[0]
            for part in parts[1:]:
                if '}' in part:
                    var_name, rest = part.split('}', 1)
                    var_value = self._get_variable_value(var_name)
                    result += var_value + rest
                else:
                    result += '${' + part
            return result
        return value
    
    def _get_variable_value(self, var_path: str) -> str:
        """获取变量路径对应的值"""
        path_parts = var_path.split('.')
        value = self._style_config
        for part in path_parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return var_path
        return str(value) if value is not None else var_path

    @staticmethod
    def get_default_config_dir() -> str:
        """获取默认配置目录路径"""
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config"
        )