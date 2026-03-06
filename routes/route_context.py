_datastore = None
_parser_manager = None
_voice_assistant = None


def set_datastore(ds):
    global _datastore
    _datastore = ds


def get_datastore():
    return _datastore


def set_parser_manager(pm):
    global _parser_manager
    _parser_manager = pm


def get_parser_manager():
    return _parser_manager


def set_voice_assistant(va):
    global _voice_assistant
    _voice_assistant = va


def get_voice_assistant():
    return _voice_assistant
