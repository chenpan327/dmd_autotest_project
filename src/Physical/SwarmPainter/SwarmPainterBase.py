import time
import allure
from airtest.core.api import *

current_path = os.path.dirname(os.path.abspath(__file__))
root_path = os.path.split(current_path)[0]
auto_setup(__file__, devices=["Windows:///"])
from utils.logger import log_manager


class SwarmPainterBase:
    def __init__(self):
        self.templatePath = os.path.join(root_path, "Protocol", "image")
        self._pos_cache = {}
        self.resolution = (1920, 1080)
        self.cache_timeout = 5

    # =========================
    # 查找
    # =========================
    def find(self, template, timeout=10, cache_timeout=10, use_cache=True):
        cache_key = template.filename

        # =========================
        # 1. 优先读取缓存
        # =========================
        if use_cache:
            cache = self._pos_cache.get(cache_key)
            if cache:
                # 缓存未过期
                if time.time() - cache['time'] < cache_timeout:
                    return cache['pos']

        # =========================
        # 2. 重新识别
        # =========================
        pos = wait(template, timeout=timeout)
        if not pos:
            raise Exception(f"{template.filename} not found")

        # =========================
        # 3. 更新缓存
        # =========================
        self._pos_cache[cache_key] = {
            "pos": pos,
            "time": time.time()
        }

        return pos

    # =========================
    # 等待元素出现
    # =========================
    def wait(self, template, timeout=10, interval=0.5):
        pos = wait(template, timeout=timeout, interval=interval)
        if not pos:
            log_manager.logger.error(f"{template.filename} wait timeout")
            raise AssertionError(f"{template.__repr__()}")

        return pos

    # =========================
    # 点击
    # =========================
    def click(self, template, timeout=10, cache_timeout=5, use_cache=True, right_click=False):
        pos = self.find(template, timeout=timeout, cache_timeout=cache_timeout, use_cache=use_cache)
        touch(pos, right_click=right_click)
        log_manager.logger.info(f"touch :{template.filename}")
        return pos

        # =========================
        # 拖拽
        # =========================

    def calc_vector(self, src_pos, dst_pos):
        screen_w, screen_h = self.resolution
        vector_x = (dst_pos[0] - src_pos[0]) / screen_w
        vector_y = (dst_pos[1] - src_pos[1]) / screen_h
        return [vector_x, vector_y]

    def drag(self, src_template, dst_template, duration=1, timeout=10):
        src = self.find(src_template, timeout=timeout)
        dst = self.find(dst_template, timeout=timeout)
        vector = self.calc_vector(src, dst)
        swipe(
            src,
            vector=vector,
            duration=duration
        )
