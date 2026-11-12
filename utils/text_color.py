import uiautomation as auto
from PIL import Image
import numpy as np
import cv2
import os


def capture_control_screenshot(control, save_path=None):
    """截取控件区域图像，不使用 mss 库"""
    if not control.Exists():
        return None

    rect = control.BoundingRectangle
    left, top, right, bottom = int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
    width = right - left
    height = bottom - top

    # # 使用 uiautomation 自带的截图功能
    # try:
    #     # 方法1: 使用 uiautomation 的 GetCapturedImage
    #     img = control.GetCapturedImage()
    #     if img is not None:
    #         if save_path:
    #             img.save(save_path)
    #         return img
    # except Exception:
    #     pass

    # 方法2: 使用 PIL.ImageGrab (需要窗口在最前)
    try:
        from PIL import ImageGrab
        # 截取指定区域
        screenshot = ImageGrab.grab(bbox=(left, top, right, bottom))
        if save_path:
            screenshot.save(save_path)
        return screenshot
    except Exception:
        pass

    # 方法3: 使用 win32gui + PIL
    # try:
    #     import win32gui
    #     import win32ui
    #     from ctypes import windll

    #     hwnd = win32gui.GetDesktopWindow()
    #     hwndDC = win32gui.GetWindowDC(hwnd)
    #     mfcDC = win32ui.CreateDCFromHandle(hwndDC)
    #     saveDC = mfcDC.CreateCompatibleDC()

    #     bitmap = win32ui.CreateBitmap()
    #     bitmap.CreateCompatibleBitmap(mfcDC, width, height)
    #     saveDC.SelectObject(bitmap)

    #     result = windll.user32.BitBlt(
    #         saveDC.GetSafeHdc(), 0, 0, width, height,
    #         hwndDC, left, top, 0x00CC0020
    #     )

    #     bmpinfo = bitmap.GetInfo()
    #     bmpstr = bitmap.GetBitmapBits(True)

    #     img = Image.frombuffer(
    #         'RGB',
    #         (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
    #         bmpstr, 'bytes', 0, 1
    #     )

    #     win32gui.DeleteObject(bitmap.GetHandle())
    #     saveDC.DeleteDC()
    #     mfcDC.DeleteDC()
    #     win32gui.ReleaseDC(hwnd, hwndDC)

    #     if save_path:
    #         img.save(save_path)
    #     return img
    # except Exception:
    #     pass

    return None


def detect_red_color(image, threshold=30, red_ratio=0.05):
    """
    检测图像中是否存在红色

    参数:
        image: PIL Image 或 numpy array
        threshold: 红色阈值 (0-255)
        red_ratio: 红色像素占比阈值

    返回:
        bool: 是否存在红色
    """
    if isinstance(image, Image.Image):
        img_array = np.array(image.convert('RGB'))
    else:
        img_array = image

    if len(img_array.shape) == 3 and img_array.shape[2] == 3:
        img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
    else:
        img_bgr = img_array

    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)

    lower_red1 = np.array([0, threshold, threshold])
    upper_red1 = np.array([10, 255, 255])

    lower_red2 = np.array([160, threshold, threshold])
    upper_red2 = np.array([180, 255, 255])

    mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
    mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
    mask = cv2.bitwise_or(mask1, mask2)

    red_pixels = cv2.countNonZero(mask)
    total_pixels = img_array.shape[0] * img_array.shape[1]
    red_percentage = red_pixels / total_pixels

    print(f"[TEST] 风速信息红色像素: {red_pixels}/{total_pixels} (占比{red_percentage*100:.2f}%)")

    return red_percentage >= red_ratio


def check_text_color_red(control, save_screenshot=True):
    """
    检查 TextControl 的文本是否为红色

    参数:
        control: uiautomation 控件
        save_screenshot: 是否保存截图

    返回:
        dict: 包含检测结果和详情
    """
    result = {
        'exists_red': False,
        'screenshot_path': None,
        'bounding_rect': None
    }

    if not control.Exists():
        print("控件不存在")
        return result

    rect = control.BoundingRectangle
    result['bounding_rect'] = rect
    save_path = 'control_screenshot.png' if save_screenshot else None
    img = capture_control_screenshot(control, save_path)
    if img is None:
        print("截图失败")
        return result

    if save_screenshot:
        result['screenshot_path'] = save_path

    has_red = detect_red_color(img, threshold=50, red_ratio=0.1)
    result['exists_red'] = has_red

    if save_screenshot and os.path.exists('control_screenshot.png'):
        os.remove('control_screenshot.png')

    return result

