from plugins.script_manager.script_manager_widget import ScriptManagerWidget


class ScriptManagerPlugin:
    """脚本管理插件"""
    
    def __init__(self, config, config_manager=None, plugin_manager=None):
        self.config = config
        self._config_manager = config_manager
        self._plugin_manager = plugin_manager
        self.name = config['name']
        self.display_name = config.get('display_name', config['name'])
        self.widget = None
    
    def get_widget(self):
        if self.widget is None:
            self.widget = ScriptManagerWidget(
                self.config, 
                self._config_manager, 
                self._plugin_manager
            )
        return self.widget
    
    def activate(self):
        pass
    
    def deactivate(self):
        pass
