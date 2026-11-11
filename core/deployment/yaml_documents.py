"""Safe YAML with explicit duplicate keys rejected and merge-key compatibility."""

import yaml


class DuplicateYamlKeyError(yaml.YAMLError):
    pass


class _UniqueKeyLoader(yaml.SafeLoader):
    def flatten_mapping(self, node):
        checked = getattr(self, '_checked_mappings', None)
        if checked is None:
            checked = self._checked_mappings = set()
        if node not in checked:
            keys = set()
            for key_node, _value_node in node.value:
                key = '<<' if key_node.tag == 'tag:yaml.org,2002:merge' else self.construct_object(key_node)
                if not isinstance(key, str) or key in keys:
                    raise DuplicateYamlKeyError(f'Повторный или недопустимый ключ YAML: {key!r}, строка {key_node.start_mark.line + 1}')
                keys.add(key)
            checked.add(node)
        # The base method also visits merge sources; validate each before it is flattened.
        super().flatten_mapping(node)


def load_unique_yaml(text):
    return yaml.load(text, Loader=_UniqueKeyLoader)
