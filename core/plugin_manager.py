import importlib
import os
import sys


class PluginManager:
    def __init__(self, config_manager=None):
        self.plugins = {}
        self.plugin_configs = {}
        self._config_manager = config_manager

    def load_plugins(self, plugin_configs, config_manager=None):
        if config_manager:
            self._config_manager = config_manager
        for config in plugin_configs:
            try:
                self.load_plugin(config)
            except Exception as e:
                print(f"Failed to load plugin {config.get('name', 'unknown')}: {e}")

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
            plugin_instance = plugin_class(config, self._config_manager)
        else:
            plugin_instance = plugin_class(config)

        self.plugins[name] = plugin_instance
        self.plugin_configs[name] = config

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
