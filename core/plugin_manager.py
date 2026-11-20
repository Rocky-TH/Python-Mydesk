import importlib
import os
import sys

from .menu_registry import MenuRegistry
from utils.logger import Logger


class PluginManager:
    def __init__(self, config_manager=None):
        self.plugins = {}
        self.plugin_configs = {}
        self._config_manager = config_manager
        # 主窗口引用：由 MainWindow 注入，供插件按需调用框架能力（如显示/隐藏视图）
        self.main_window = None
        # 统一状态接口：插件通过此回调向框架汇报自身状态
        self._status_callback = None
        # 保存每个插件最新上报的状态文本
        self._plugin_status = {}
        self._logger = Logger.get_instance()

    def load_plugins(self, plugin_configs, config_manager=None):
        if config_manager:
            self._config_manager = config_manager
        for config in plugin_configs:
            try:
                self.load_plugin(config)
            except Exception as e:
                self._logger.error(
                    f"加载插件失败: {config.get('name', 'unknown')}: {e}",
                    exc_info=True
                )

    def load_plugin(self, config):
        name = config['name']
        module_name = config['module']
        class_name = config['main_class']

        # Add plugin directory to path
        plugin_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "plugins"
        )
        if plugin_dir not in sys.path:
            sys.path.insert(0, plugin_dir)

        # Import module and get class
        module = importlib.import_module(module_name)
        plugin_class = getattr(module, class_name)

        # Instantiate plugin with config and config_manager
        if self._config_manager:
            plugin_instance = plugin_class(config, self._config_manager, self)
        else:
            plugin_instance = plugin_class(config, None, self)

        self.plugins[name] = plugin_instance
        self.plugin_configs[name] = config
        self._logger.info(f"插件已加载: {name} ({module_name}.{class_name})")

    def get_plugin(self, name):
        return self.plugins.get(name)

    def get_all_plugins(self):
        return self.plugins

    def reload_plugin(self, name):
        if name in self.plugin_configs:
            config = self.plugin_configs[name]
            if name in self.plugins:
                del self.plugins[name]
            self.load_plugin(config)

    # ========== 统一状态接口 ==========
    def set_status_callback(self, callback):
        """设置状态更新回调，由 MainWindow 注册

        Args:
            callback: 回调函数，签名 callback(plugin_name: str, status_text: str)
        """
        self._status_callback = callback

    def set_tool_status(self, plugin_name, status_text):
        """工具插件通过此接口更新自身状态

        Args:
            plugin_name: 插件名称
            status_text: 状态文本
        """
        self._plugin_status[plugin_name] = status_text
        if self._status_callback:
            try:
                self._status_callback(plugin_name, status_text)
            except Exception as e:
                self._logger.error(
                    f"插件状态回调执行失败: {plugin_name}: {e}",
                    exc_info=True
                )

    def get_tool_status(self, plugin_name):
        """获取指定插件的最新状态文本"""
        return self._plugin_status.get(plugin_name, '')

    def clear_tool_status(self, plugin_name):
        """清除指定插件的状态文本"""
        self._plugin_status.pop(plugin_name, None)
        if self._status_callback:
            self._status_callback(plugin_name, '')

    # ========== 设置注册接口 ==========
    def collect_plugin_settings(self):
        """收集所有插件注册的设置分组。

        遍历所有已加载插件，调用其 ``register_settings(registry)`` 方法（若存在），
        插件通过 ``registry.add_settings_menu(...)`` 声明「设置 → <工具名>」分组
        并追加设置项，框架统一挂载到平台级「设置」菜单下。

        Returns:
            list[dict]: 设置分组列表，每项为
            ``{'plugin_name': str, 'title': str, 'items': [...]}``。
            按插件加载顺序排列。
        """
        registry = MenuRegistry()
        for plugin_name in self.plugins:
            plugin = self.plugins[plugin_name]
            register_fn = getattr(plugin, 'register_settings', None)
            if register_fn is None:
                continue
            try:
                register_fn(registry)
            except Exception as e:
                self._logger.error(
                    f"收集插件设置失败: {plugin_name}: {e}",
                    exc_info=True
                )
        return registry.get_settings()
