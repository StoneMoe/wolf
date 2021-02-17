import random
import subprocess
from sys import platform


def rand_int(min_value=0, max_value=100):
    return random.randint(min_value, max_value)


def say(text):
    if platform == "darwin":
        subprocess.Popen(['say', '-r', '10000', text])


def add_cancel_button(buttons: list):
    return buttons + [{'label': '放弃', 'type': 'cancel'}]
