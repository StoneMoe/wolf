import random
from subprocess import run
import threading
from typing import Text
import pyttsx3
from sys import platform
import subprocess


def rand_int(min_value=0, max_value=100):
    return random.randint(min_value, max_value)


def say(text):
    if platform == "darwin":
        subprocess.Popen(['say', '-r', '10000', text])
    elif platform.system() == "windows":
        def run_pyttsx3(text):
            engine = pyttsx.init()
            engine.say(text)
            engine.runAndWait()
        def start_tts(text):
            try:
                thread.start_new_thread(run_pyttsx3,(text))
            except:
                print("启动tts失败！")
        start_tts(text)
            


def add_cancel_button(buttons: list):
    return buttons + [{'label': '放弃', 'type': 'cancel'}]
