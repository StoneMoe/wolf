from pywebio.io_ctrl import Output


class OutputHandler(Output):
    """PyWebIO.OutputHandler Stub"""

    def __del__(self):
        pass

    def __init__(self, spec, scope):
        super().__init__(spec)

    def reset(self, *outputs):
        pass

    def append(self, *outputs):
        pass

    def insert(self, idx, *outputs):
        pass
