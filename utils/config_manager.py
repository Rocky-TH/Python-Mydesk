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
        self._themes: Dict[str, Dict[str, Any]] = {}
        
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
        
        # 加载主题目录下的所有主题
        self._load_themes()
    
    def _load_themes(self) -> None:
        """加载主题目录下的所有主题配置"""
        self._themes = {}
        theme_dir = self._style_config.get('theme_dir', 'theme')
        theme_dir_path = os.path.join(self._config_dir, theme_dir)
        
        if not os.path.exists(theme_dir_path):
            print(f"主题目录不存在: {theme_dir_path}")
            return
        
        for filename in os.listdir(theme_dir_path):
            if filename.endswith('.json'):
                theme_path = os.path.join(theme_dir_path, filename)
                try:
                    with open(theme_path, 'r', encoding='utf-8') as f:
                        theme_data = json.load(f)
                        theme_name = filename[:-5]  # 移除 .json 后缀
                        self._themes[theme_name] = theme_data
                except (json.JSONDecodeError, IOError) as e:
                    print(f"加载主题失败 {filename}: {e}")
    
    def get_available_themes(self) -> Dict[str, Dict[str, Any]]:
        """获取所有可用的主题"""
        return self._themes
    
    def get_theme_list(self) -> List[Dict[str, str]]:
        """获取主题列表（名称和描述）"""
        result = []
        for theme_id, theme_data in self._themes.items():
            result.append({
                'id': theme_id,
                'name': theme_data.get('name', theme_id),
                'description': theme_data.get('description', '')
            })
        return result
    
    def _get_default_style_config(self) -> Dict[str, Any]:
        """获取默认样式配置"""
        return {
            "version": "2.0.0",
            "current_theme": "dark",
            "theme_dir": "theme"
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
    
    def get_current_theme(self) -> str:
        """获取当前主题名称"""
        return self._style_config.get('current_theme', 'dark')
    
    def set_current_theme(self, theme_id: str) -> bool:
        """设置当前主题"""
        if theme_id not in self._themes:
            print(f"主题不存在: {theme_id}")
            return False
        self._style_config['current_theme'] = theme_id
        self.save_style_config()
        return True
    
    def save_style_config(self) -> bool:
        """保存样式配置"""
        if not self._config_dir:
            return False
        style_config_path = os.path.join(self._config_dir, 'style_config.json')
        try:
            with open(style_config_path, 'w', encoding='utf-8') as f:
                json.dump(self._style_config, f, indent=4, ensure_ascii=False)
            return True
        except IOError as e:
            print(f"保存样式配置失败: {e}")
            return False
    
    def get_current_theme_config(self) -> Dict[str, Any]:
        """获取当前主题的完整配置"""
        current_theme = self.get_current_theme()
        if current_theme in self._themes:
            return self._themes[current_theme]
        # 如果找不到当前主题，返回第一个可用主题
        if self._themes:
            return next(iter(self._themes.values()))
        # 返回默认深色主题配置
        return {
            "name": "深色主题",
            "description": "默认深色主题",
            "is_dark": True,
            "colors": {
                "primary": "#007acc",
                "primary-hover": "#005a9e",
                "primary-pressed": "#004575",
                "success": "#28a745",
                "warning": "#ffc107",
                "danger": "#dc3545",
                "info": "#17a2b8",
                "bg-main": "#1e1e1e",
                "bg-secondary": "#252526",
                "bg-tertiary": "#2d2d30",
                "bg-input": "#3c3c3c",
                "bg-input-focus": "#4c4c4c",
                "border": "#3d3d40",
                "border-light": "#4a4a4d",
                "border-focus": "#007acc",
                "text": "#ffffff",
                "text-secondary": "#cccccc",
                "text-hint": "#888888",
                "text-success": "#00ff00",
                "text-warning": "#ffff00",
                "text-danger": "#ff6b6b",
                "text-info": "#00d4ff",
                "selection": "#007acc",
                "selection-text": "#ffffff"
            },
            "fonts": {
                "size-sm": "11px",
                "size-md": "12px",
                "size-lg": "13px",
                "size-xl": "14px",
                "size-xxl": "16px",
                "weight-normal": "500",
                "weight-bold": "bold"
            },
            "radius": {
                "sm": "4px",
                "md": "6px",
                "lg": "8px",
                "xl": "12px"
            },
            "components": {}
        }
    
    def get_color_scheme(self) -> Dict[str, Any]:
        """获取颜色方案配置（兼容旧接口）"""
        return self.get_current_theme_config().get('colors', {})
    
    def get_color(self, key: str, default: str = '#ffffff') -> str:
        """获取单个颜色值（支持新格式和旧格式）"""
        colors = self.get_color_scheme()
        
        # 新格式 key
        if key in colors:
            return colors[key]
        
        # 旧格式兼容
        old_key_map = {
            'background_main': 'bg-main',
            'background_secondary': 'bg-secondary',
            'background_tertiary': 'bg-tertiary',
            'background_input': 'bg-input',
            'background_input_focus': 'bg-input-focus',
            'text_primary': 'text',
            'text_secondary': 'text-secondary',
            'text_hint': 'text-hint',
            'text_success': 'text-success',
            'text_warning': 'text-warning',
            'text_danger': 'text-danger',
            'text_info': 'text-info',
            'border_light': 'border-light',
            'border_focus': 'border-focus',
            'selection_text': 'selection-text',
            'primary_hover': 'primary-hover',
            'primary_pressed': 'primary-pressed'
        }
        
        if key in old_key_map:
            return colors.get(old_key_map[key], default)
        
        return default
    
    def get_font_size(self, key: str, default: str = '12px') -> str:
        """获取字体大小配置（支持新格式和旧格式）"""
        fonts = self.get_current_theme_config().get('fonts', {})
        
        # 新格式 key
        if key in fonts:
            return self._validate_font_size(fonts[key], default)
        
        # 旧格式兼容
        old_key_map = {
            'small': 'size-sm',
            'normal': 'size-md',
            'medium': 'size-lg',
            'large': 'size-xl',
            'extra_large': 'size-xxl'
        }
        
        if key in old_key_map:
            value = fonts.get(old_key_map[key], default)
            return self._validate_font_size(value, default)
        
        return self._validate_font_size(default, default)
    
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
        """获取边框圆角配置（支持新格式和旧格式）"""
        radius = self.get_current_theme_config().get('radius', {})
        
        # 新格式 key
        if key in radius:
            return radius[key]
        
        # 旧格式兼容
        old_key_map = {
            'small': 'sm',
            'normal': 'md',
            'large': 'lg',
            'extra_large': 'xl'
        }
        
        if key in old_key_map:
            return radius.get(old_key_map[key], default)
        
        return default
    
    def get_component_style(self, component_name: str) -> Dict[str, Any]:
        """获取指定组件的样式配置"""
        components = self.get_current_theme_config().get('components', {})
        return components.get(component_name, {})
    
    def get_component_style_value(self, component_name: str, key: str, default: Any = None) -> Any:
        """获取指定组件的样式值（自动解析变量引用）"""
        component = self.get_component_style(component_name)
        value = component.get(key, default)
        if isinstance(value, str):
            return self.resolve_style_value(value)
        return value
    
    def resolve_style_value(self, value: str) -> str:
        """解析样式值中的变量引用，支持两种格式：${xxx} 和 @xxx"""
        if not isinstance(value, str):
            return str(value) if value is not None else ''
        
        # 先处理 @xxx 格式（新格式）
        if '@' in value:
            parts = value.split('@')
            result = parts[0]
            for part in parts[1:]:
                if ' ' in part or '\t' in part or ';' in part or ':' in part:
                    # 变量后面有分隔符
                    var_name = part.split()[0].split(';')[0].split(':')[0]
                    rest = part[len(var_name):]
                    var_value = self._get_variable_value(var_name)
                    result += var_value + rest
                else:
                    var_value = self._get_variable_value(part)
                    result += var_value
            value = result
        
        # 处理 ${xxx} 格式（旧格式兼容）
        if '${' in value and '}' in value:
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
        """获取变量路径对应的值（支持新格式和旧格式）"""
        theme_config = self.get_current_theme_config()
        
        # 新格式：@primary, @bg-main, @fonts.size-md
        path_parts = var_path.split('.')
        if len(path_parts) == 1:
            # 单个 key，先检查 colors
            if path_parts[0] in theme_config.get('colors', {}):
                return theme_config['colors'][path_parts[0]]
            # 检查 fonts
            if path_parts[0] in theme_config.get('fonts', {}):
                return theme_config['fonts'][path_parts[0]]
            # 检查 radius
            if path_parts[0] in theme_config.get('radius', {}):
                return theme_config['radius'][path_parts[0]]
        elif len(path_parts) == 2:
            # 两个部分：fonts.size-md, radius.sm
            category, key = path_parts
            if category == 'colors' and key in theme_config.get('colors', {}):
                return theme_config['colors'][key]
            elif category == 'fonts' and key in theme_config.get('fonts', {}):
                return theme_config['fonts'][key]
            elif category == 'radius' and key in theme_config.get('radius', {}):
                return theme_config['radius'][key]
        
        # 旧格式兼容：color_scheme.primary, font_sizes.medium
        if len(path_parts) >= 2:
            category = path_parts[0]
            key_parts = path_parts[1:]
            key = '.'.join(key_parts)
            
            if category == 'color_scheme':
                return self.get_color(key, var_path)
            elif category == 'font_sizes':
                return self.get_font_size(key, var_path)
            elif category == 'border_radius':
                return self.get_border_radius(key, var_path)
        
        return var_path

    @staticmethod
    def get_default_config_dir() -> str:
        """获取默认配置目录路径"""
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config"
        )