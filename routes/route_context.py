_datastore = None
_parser_manager = None


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
