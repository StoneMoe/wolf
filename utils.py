import random
import socket
import subprocess
import threading
import traceback
from logging import getLogger
from sys import platform

import pyttsx3

logger = getLogger('Utils')
logger.setLevel('DEBUG')


def rand_int(min_value=0, max_value=100):
    return random.randint(min_value, max_value)


def say(text):
    if platform == "darwin":
        subprocess.Popen(['say', '-r', '10000', text])
    elif platform == "win32":
        def wrapper():
            tts = pyttsx3.init()
            tts.say(text)
            tts.runAndWait()

        threading.Thread(target=wrapper).start()

    else:
        logger.warning(f'{platform} 暂不支持TTS语音播报')


def get_interface_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        return s.getsockname()[0] or '获取失败'
    except Exception:
        traceback.print_exc()
        return '获取失败'


def add_cancel_button(buttons: list):
    return buttons + [{'label': '放弃', 'type': 'cancel'}]
